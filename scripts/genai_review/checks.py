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
    if hits or no_expiry or unencrypted:
        found = " and ".join(f"{count} {label}{'s' if count > 1 else ''}" for label, count in sorted(hits.items()))
        return Result(
            False,
            f"{len(review.snapshot.log_events)} sampled log events hold {found or 'no PII'}; "
            f"{unencrypted} of {len(groups)} log groups have no KMS key and {no_expiry} never expire",
        )
    return Result(True, "no PII in the sampled prompts; every log group has a KMS key and expires")


@check("invocation-logging")
def invocation_logging(review: Review) -> Result:
    config = review.snapshot.bedrock_settings["get-model-invocation-logging-configuration"]
    logging_config = config.get("loggingConfig")
    if not logging_config:
        return Result(False, "get-model-invocation-logging-configuration returns no loggingConfig")
    if logging_config.get("textDataDeliveryEnabled"):
        # Bedrock logs the original input even when a guardrail anonymizes PII, so text delivery keeps raw prompts.
        return Result(False, "invocation logging delivers text data, which keeps raw prompts and their PII")
    return Result(True, "model invocation logging is configured, metadata and token counts only")


@check("api-throttling")
def api_throttling(review: Review) -> Result:
    settings = [
        s
        for res in review.snapshot.resources_of("aws_api_gateway_method_settings").values()
        for s in res["values"]["settings"]
    ]
    throttled = any(s.get("throttling_rate_limit", -1) > 0 for s in settings)
    plans = review.snapshot.resources_of("aws_api_gateway_usage_plan")
    methods = review.snapshot.resources_of("aws_api_gateway_method")
    keyless = sorted(name for name, res in methods.items() if not res["values"].get("api_key_required"))
    # A usage plan only meters and throttles methods that require an API key; keyless methods bypass its quota.
    if not throttled or not plans or keyless:
        return Result(
            False,
            f"stage throttling {'set' if throttled else 'unset (rate limit -1)'}; {len(plans)} usage plans; "
            f"{len(keyless)} of {len(methods)} methods accept requests without an API key",
        )
    return Result(True, f"stage throttling set, {len(plans)} usage plans and every method requires an API key")


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


APPLICATION_PROFILES = "list-inference-profiles --type-equals APPLICATION"
APPLICATION_PROFILE_ARN = ":application-inference-profile/"


def _application_profile(review: Review, arn: str) -> dict:
    for summary in review.snapshot.bedrock_settings[APPLICATION_PROFILES]["inferenceProfileSummaries"]:
        if summary.get("inferenceProfileArn") == arn:
            return summary
    raise KeyError(f"application inference profile {arn} is not in the Bedrock settings export")


def _profile_models(summary: dict) -> tuple[set[str], set[str]]:
    """Foundation model IDs and Regions behind an application inference profile."""
    models, regions = set(), set()
    for model in summary.get("models", []):
        arn = model["modelArn"]
        models.add(arn.split("foundation-model/", 1)[1])
        regions.add(arn.split(":")[3])
    return models, regions


def model_key(review: Review, model_id: str) -> str:
    """Pricing key of a MODEL_ID: a system inference profile ID or an application inference profile ARN."""
    for key, model in review.pricing["models"].items():
        if model["model_id"] == model_id:
            return key
    if APPLICATION_PROFILE_ARN in model_id:
        models, _ = _profile_models(_application_profile(review, model_id))
        keys = [key for key, model in review.pricing["models"].items() if model["foundation_model"] in models]
        if len(keys) == 1:
            return keys[0]
        raise KeyError(f"application inference profile {model_id} resolves to models {sorted(models)}, not one priced")
    raise KeyError(f"model {model_id} has no price in data/pricing.yaml")


def is_cross_region(review: Review, model_id: str) -> bool:
    """True for a cross-Region system profile ID, or an application profile copied from one (models in 2+ Regions)."""
    if model_id.startswith(CROSS_REGION_PREFIXES):
        return True
    if APPLICATION_PROFILE_ARN in model_id:
        _, regions = _profile_models(_application_profile(review, model_id))
        return len(regions) > 1
    return False


def unit_prices(review: Review, key: str) -> dict[str, float]:
    """Per-1M-token prices of a model, with the geographic premium when its profile is geographic (us., eu., apac.)."""
    model = review.pricing["models"][key]
    factor = 1.0
    if model["model_id"].startswith(tuple(review.pricing["geographic_prefixes"])):
        factor += model["geographic_premium"]
    return {kind: model[kind] * factor for kind in ("input", "output", "cache_write", "cache_read")}


def cacheable(review: Review, route: str, key: str) -> bool:
    """A cache point after the system prompt only takes effect when the prompt reaches the model's minimum."""
    return review.routes[route]["system_prompt_tokens"] >= review.pricing["models"][key]["min_cache_tokens"]


def blended_price(review: Review, key: str, route: dict) -> float:
    """Price of one average request on a route, for ranking candidate models."""
    prices = unit_prices(review, key)
    tokens_in = route["system_prompt_tokens"] + route["context_tokens"] + route["user_tokens"]
    return tokens_in * prices["input"] + route["output_tokens"] * prices["output"]


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
    off, below = [], []
    for route in INTERACTIVE_ROUTES:
        env = review.snapshot.lambda_env(route)
        key = model_key(review, env["MODEL_ID"])
        if not cacheable(review, route, key):
            below.append(f"{route} ({key} caches from {review.pricing['models'][key]['min_cache_tokens']:,} tokens)")
        elif env.get("PROMPT_CACHING") != "true":
            off.append(route)
    if off:
        tokens = ", ".join(f"{r} {review.routes[r]['system_prompt_tokens']:,}" for r in off)
        return Result(False, f"PROMPT_CACHING is off on {', '.join(off)} (system prompt tokens: {tokens})")
    if below:
        return Result(
            True, f"prompt caching is on where it applies; system prompt below the minimum on {', '.join(below)}"
        )
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
    profiles = review.snapshot.bedrock_settings[APPLICATION_PROFILES]["inferenceProfileSummaries"]
    if len(profiles) < len(review.routes):
        return Result(False, f"{len(profiles)} application inference profiles for {len(review.routes)} routes")
    return Result(True, f"{len(profiles)} application inference profiles")


@check("cross-region-inference")
def cross_region_inference(review: Review) -> Result:
    single = [
        r for r in _lambda_routes(review) if not is_cross_region(review, review.snapshot.lambda_env(r)["MODEL_ID"])
    ]
    if single:
        return Result(False, f"single-Region model IDs on: {', '.join(single)}")
    return Result(True, "every route calls a cross-Region inference profile")


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
