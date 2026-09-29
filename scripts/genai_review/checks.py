"""Scripted checks over the as-found evidence. Each check returns whether the best practice holds and what it saw.

The checks read only files under data/synthetic/as-found; they never call AWS. In an engagement the same files come
from read-only exports of the client's account.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from genai_review.model import Review

# The quality bar agreed with the client: a model qualifies for a route when it passes at least 90% of the golden
# questions overall and at least 85% in every category.
EVAL_OVERALL_BAR = 0.90
EVAL_CATEGORY_BAR = 0.85
INTERACTIVE_ROUTES = ("ask", "compare")
MAX_TOKENS_CEILING = 2048
# More than this many GB of vector data per OCU means the collection is not oversized for its data.
GB_PER_OCU_FLOOR = 10.0
EVAL_STAGE_WORDS = ("eval", "golden")
PII_PATTERNS = {
    "phone number": re.compile(r"\b\d{3}-\d{3}-\d{4}\b"),
    "loyalty card number": re.compile(r"\bHG-LOY-\d{8}\b"),
}
CROSS_REGION_PREFIXES = ("us.", "eu.", "apac.", "global.")
WILDCARD_ACTIONS = ("*", "bedrock:*")


@dataclass(frozen=True)
class Result:
    passed: bool
    observed: str


CheckFn = Callable[["Review"], Result]
REGISTRY: dict[str, CheckFn] = {}


def check(check_id: str) -> Callable[[CheckFn], CheckFn]:
    def register(fn: CheckFn) -> CheckFn:
        REGISTRY[check_id] = fn
        return fn

    return register


def _lambda_routes(review: Review) -> list[str]:
    return sorted(name.split(".", 1)[1] for name in review.snapshot.resources_of("aws_lambda_function"))


@check("guardrail-every-route")
def guardrail_every_route(review: Review) -> Result:
    missing = [r for r in INTERACTIVE_ROUTES if not review.snapshot.lambda_env(r).get("GUARDRAIL_ID")]
    if missing:
        return Result(False, f"GUARDRAIL_ID is empty on: {', '.join(missing)}")
    return Result(True, "every interactive route sets GUARDRAIL_ID")


@check("scoped-bedrock-access")
def scoped_bedrock_access(review: Review) -> Result:
    broad = []
    for policy in review.snapshot.iam_role["InlinePolicies"]:
        for statement in policy["PolicyDocument"]["Statement"]:
            actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            resources = statement["Resource"] if isinstance(statement["Resource"], list) else [statement["Resource"]]
            if statement["Effect"] == "Allow" and any(a in WILDCARD_ACTIONS for a in actions) and "*" in resources:
                broad.append(f"{policy['PolicyName']}/{statement.get('Sid', '?')} allows `{', '.join(actions)}` on `*`")
    if broad:
        return Result(False, "; ".join(broad))
    return Result(True, "no statement allows a Bedrock wildcard action on every resource")


@check("pii-in-logs")
def pii_in_logs(review: Review) -> Result:
    hits: dict[str, int] = defaultdict(int)
    for event in review.snapshot.log_events:
        for label, pattern in PII_PATTERNS.items():
            if pattern.search(event.get("prompt", "")):
                hits[label] += 1
    groups = review.snapshot.resources_of("aws_cloudwatch_log_group")
    unencrypted = sum(1 for g in groups.values() if not g["values"].get("kms_key_id"))
    no_expiry = sum(1 for g in groups.values() if not g["values"].get("retention_in_days"))
    if hits or no_expiry:
        found = " and ".join(f"{count} {label}{'s' if count > 1 else ''}" for label, count in sorted(hits.items()))
        return Result(
            False,
            f"{len(review.snapshot.log_events)} sampled log events hold {found or 'no PII'}; "
            f"{unencrypted} of {len(groups)} log groups have no KMS key and {no_expiry} never expire",
        )
    return Result(True, "no PII in the sampled prompts and every log group expires")


@check("invocation-logging")
def invocation_logging(review: Review) -> Result:
    config = review.snapshot.bedrock_settings["get-model-invocation-logging-configuration"]
    if not config.get("loggingConfig"):
        return Result(False, "get-model-invocation-logging-configuration returns no loggingConfig")
    return Result(True, "model invocation logging is configured")


@check("api-throttling")
def api_throttling(review: Review) -> Result:
    settings = [
        s
        for res in review.snapshot.resources_of("aws_api_gateway_method_settings").values()
        for s in res["values"]["settings"]
    ]
    throttled = any(s.get("throttling_rate_limit", -1) > 0 for s in settings)
    plans = review.snapshot.resources_of("aws_api_gateway_usage_plan")
    if not throttled or not plans:
        return Result(
            False,
            f"stage throttling {'set' if throttled else 'unset (rate limit -1)'}; {len(plans)} usage plans",
        )
    return Result(True, f"stage throttling set and {len(plans)} usage plans")


@check("eval-in-pipeline")
def eval_in_pipeline(review: Review) -> Result:
    stages = [stage["name"] for stage in review.snapshot.pipeline["stages"]]
    if not any(word in name for name in stages for word in EVAL_STAGE_WORDS):
        return Result(False, f"pipeline stages: {', '.join(stages)}")
    return Result(True, "the pipeline has an evaluation stage")


def eval_pass_rates(review: Review) -> dict[str, dict[str, dict[str, float]]]:
    """route -> model -> {"overall": rate, "min_category": rate}."""
    totals: dict[tuple[str, str], list[tuple[int, int]]] = defaultdict(list)
    for row in review.snapshot.eval_rows:
        totals[(row["route"], row["model"])].append((int(row["questions"]), int(row["passed"])))
    rates: dict[str, dict[str, dict[str, float]]] = defaultdict(dict)
    for (route, model), cats in sorted(totals.items()):
        rates[route][model] = {
            "overall": sum(p for _, p in cats) / sum(q for q, _ in cats),
            "min_category": min(p / q for q, p in cats),
        }
    return dict(rates)


def qualifies(rate: dict[str, float]) -> bool:
    return rate["overall"] >= EVAL_OVERALL_BAR and rate["min_category"] >= EVAL_CATEGORY_BAR


def model_key(review: Review, model_id: str) -> str:
    for key, model in review.pricing["models"].items():
        if model["model_id"] == model_id:
            return key
    raise KeyError(f"model {model_id} has no price in data/pricing.yaml")


def blended_price(review: Review, key: str, route: dict) -> float:
    """Price of one average request on a route, for ranking candidate models."""
    model = review.pricing["models"][key]
    tokens_in = route["system_prompt_tokens"] + route["context_tokens"] + route["user_tokens"]
    return tokens_in * model["input"] + route["output_tokens"] * model["output"]


def cheapest_qualifying(review: Review, route: str) -> str:
    rates = eval_pass_rates(review)[route]
    candidates = [key for key, rate in rates.items() if qualifies(rate)]
    return min(candidates, key=lambda key: blended_price(review, key, review.routes[route]))


@check("right-sized-model")
def right_sized_model(review: Review) -> Result:
    oversized = []
    for route in INTERACTIVE_ROUTES:
        current = model_key(review, review.snapshot.lambda_env(route)["MODEL_ID"])
        best = cheapest_qualifying(review, route)
        if best != current:
            rate = eval_pass_rates(review)[route][best]
            oversized.append(
                f"{route} uses {current}; {best} passes {rate['overall']:.1%} overall, "
                f"{rate['min_category']:.0%} in its weakest category"
            )
    if oversized:
        return Result(False, "; ".join(oversized))
    return Result(True, "each interactive route uses the cheapest model that meets the bar")


@check("prompt-caching")
def prompt_caching(review: Review) -> Result:
    off = [r for r in INTERACTIVE_ROUTES if review.snapshot.lambda_env(r).get("PROMPT_CACHING") != "true"]
    if off:
        tokens = ", ".join(f"{r} {review.routes[r]['system_prompt_tokens']:,}" for r in off)
        return Result(False, f"PROMPT_CACHING is off on {', '.join(off)} (system prompt tokens: {tokens})")
    return Result(True, "prompt caching is on for every interactive route")


@check("vector-store-sizing")
def vector_store_sizing(review: Review) -> Result:
    hours = review.workload["assumptions"]["hours_per_month"]
    latest = max(row["billing_period"] for row in review.snapshot.cur_rows)
    ocu_hours = sum(
        float(row["usage_amount"])
        for row in review.snapshot.cur_rows
        if row["billing_period"] == latest and row["usage_type"].endswith("OCU")
    )
    ocus = ocu_hours / hours
    gigabytes = review.workload["knowledge_base"]["vector_data_gb"]
    if ocus and gigabytes / ocus < GB_PER_OCU_FLOOR:
        return Result(False, f"{ocus:g} OCUs on average for {gigabytes:g} GB of vector data")
    return Result(True, f"{ocus:g} OCUs for {gigabytes:g} GB of vector data")


@check("batch-for-offline-jobs")
def batch_for_offline_jobs(review: Review) -> Result:
    on_demand = [
        r
        for r, route in review.routes.items()
        if route["latency"] == "offline" and review.snapshot.lambda_env(r).get("INFERENCE_MODE") != "batch"
    ]
    if on_demand:
        return Result(False, f"offline routes on on-demand inference: {', '.join(on_demand)}")
    return Result(True, "offline routes use batch inference")


@check("application-inference-profiles")
def application_inference_profiles(review: Review) -> Result:
    listed = "list-inference-profiles --type-equals APPLICATION"
    profiles = review.snapshot.bedrock_settings[listed]["inferenceProfileSummaries"]
    if len(profiles) < len(review.routes):
        return Result(False, f"{len(profiles)} application inference profiles for {len(review.routes)} routes")
    return Result(True, f"{len(profiles)} application inference profiles")


@check("cross-region-inference")
def cross_region_inference(review: Review) -> Result:
    single = [
        r
        for r in _lambda_routes(review)
        if not review.snapshot.lambda_env(r)["MODEL_ID"].startswith(CROSS_REGION_PREFIXES)
    ]
    if single:
        return Result(False, f"single-Region model IDs on: {', '.join(single)}")
    return Result(True, "every route calls a cross-Region inference profile (us. prefix)")


@check("max-tokens-set")
def max_tokens_set(review: Review) -> Result:
    unset = [
        r
        for r in _lambda_routes(review)
        if not 0 < int(review.snapshot.lambda_env(r).get("MAX_TOKENS", "0")) <= MAX_TOKENS_CEILING
    ]
    if unset:
        return Result(False, f"MAX_TOKENS missing or above {MAX_TOKENS_CEILING} on: {', '.join(unset)}")
    return Result(True, f"every route sets MAX_TOKENS at or below {MAX_TOKENS_CEILING}")


def run_all(review: Review) -> dict[str, Result]:
    return {check_id: REGISTRY[check_id](review) for check_id in review.checks}
