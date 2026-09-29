"""Monthly cost model: the workload as found, the recommended state, and the change each lever makes.

Levers apply in a fixed order (LEVERS); each lever's figure is the change in the monthly total when it is applied on
top of the levers before it, so the lever figures add up exactly to the difference between the two states.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from genai_review.checks import INTERACTIVE_ROUTES, cheapest_qualifying, model_key

if TYPE_CHECKING:
    from genai_review.model import Review

MILLION = 1_000_000
GB_PER_TB = 1000
KB_PER_GB = 1_000_000
ALL_GUARDRAIL_POLICIES = ("content_filter", "denied_topics", "sensitive_information")

LEVERS = (
    ("model-right-size", "Right-size the ask route model"),
    ("prompt-caching", "Cache the system prompt"),
    ("batch-inference", "Batch inference for the enrich job"),
    ("vector-store", "Move the knowledge base to S3 Vectors"),
    ("guardrail-coverage", "Guardrail with PII filter on every route"),
    ("invocation-logging", "Model invocation logging"),
)
COMPONENTS = (
    "ask route tokens",
    "compare route tokens",
    "enrich job tokens",
    "embeddings",
    "guardrails",
    "vector store",
    "invocation logging",
)


@dataclass(frozen=True)
class State:
    models: dict[str, str]
    cached: frozenset[str]
    batch: frozenset[str]
    vector_store: str
    guardrails: dict[str, tuple[str, ...]]
    invocation_logging: bool


def as_found(review: Review) -> State:
    snap = review.snapshot
    guardrails = {}
    for route in INTERACTIVE_ROUTES:
        env = snap.lambda_env(route)
        if env.get("GUARDRAIL_ID"):
            guardrails[route] = tuple(p for p in env.get("GUARDRAIL_POLICIES", "").split(",") if p)
    return State(
        models={r: model_key(review, snap.lambda_env(r)["MODEL_ID"]) for r in review.routes},
        cached=frozenset(r for r in review.routes if snap.lambda_env(r).get("PROMPT_CACHING") == "true"),
        batch=frozenset(r for r in review.routes if snap.lambda_env(r).get("INFERENCE_MODE") == "batch"),
        vector_store="opensearch-serverless",
        guardrails=guardrails,
        invocation_logging=bool(
            snap.bedrock_settings["get-model-invocation-logging-configuration"].get("loggingConfig")
        ),
    )


def apply(review: Review, state: State, lever: str) -> State:
    if lever == "model-right-size":
        models = dict(state.models)
        for route in INTERACTIVE_ROUTES:
            models[route] = cheapest_qualifying(review, route)
        return replace(state, models=models)
    if lever == "prompt-caching":
        return replace(state, cached=state.cached | frozenset(INTERACTIVE_ROUTES))
    if lever == "batch-inference":
        offline = frozenset(r for r, route in review.routes.items() if route["latency"] == "offline")
        return replace(state, batch=state.batch | offline)
    if lever == "vector-store":
        return replace(state, vector_store="s3-vectors")
    if lever == "guardrail-coverage":
        return replace(state, guardrails=dict.fromkeys(INTERACTIVE_ROUTES, ALL_GUARDRAIL_POLICIES))
    if lever == "invocation-logging":
        return replace(state, invocation_logging=True)
    raise ValueError(f"unknown lever {lever}")


def recommended(review: Review) -> State:
    state = as_found(review)
    for lever, _ in LEVERS:
        state = apply(review, state, lever)
    return state


def route_tokens(review: Review, state: State, route: str) -> float:
    spec = review.routes[route]
    price = review.pricing["models"][state.models[route]]
    n = spec["requests_per_month"]
    system = spec["system_prompt_tokens"]
    rest = spec["context_tokens"] + spec["user_tokens"]
    if route in state.cached:
        hit = review.workload["assumptions"]["prompt_cache_hit_rate"]
        cost = n * system * (hit * price["cache_read"] + (1 - hit) * price["cache_write"])
        cost += n * rest * price["input"]
    else:
        cost = n * (system + rest) * price["input"]
    cost += n * spec["output_tokens"] * price["output"]
    cost /= MILLION
    if route in state.batch:
        cost *= review.pricing["batch_price_factor"]
    return cost


def interactive_requests(review: Review) -> int:
    return sum(review.routes[r]["requests_per_month"] for r in INTERACTIVE_ROUTES)


def embeddings(review: Review) -> float:
    kb = review.workload["knowledge_base"]
    tokens = kb["embedding_tokens_per_month"] + interactive_requests(review) * kb["query_embedding_tokens"]
    return tokens / MILLION * review.pricing["embeddings"]["per_million_tokens"]


def text_units(review: Review, tokens: int) -> int:
    assumptions = review.workload["assumptions"]
    return math.ceil(tokens * assumptions["chars_per_token"] / assumptions["guardrail_text_unit_chars"])


def guardrails(review: Review, state: State) -> float:
    cost = 0.0
    for route, policies in state.guardrails.items():
        spec = review.routes[route]
        units = spec["requests_per_month"] * (
            text_units(review, spec["user_tokens"]) + text_units(review, spec["output_tokens"])
        )
        cost += units / 1000 * sum(review.pricing["guardrails"][p] for p in policies)
    return cost


def ocu_hours(review: Review) -> float:
    latest = max(row["billing_period"] for row in review.snapshot.cur_rows)
    return sum(
        float(row["usage_amount"])
        for row in review.snapshot.cur_rows
        if row["billing_period"] == latest and row["usage_type"].endswith("OCU")
    )


def vector_store(review: Review, state: State) -> float:
    if state.vector_store == "opensearch-serverless":
        return ocu_hours(review) * review.pricing["opensearch_serverless"]["ocu_hour"]
    price = review.pricing["s3_vectors"]
    gigabytes = review.workload["knowledge_base"]["vector_data_gb"]
    queries = interactive_requests(review)
    return (
        gigabytes * price["storage_gb_month"]
        + queries / MILLION * price["query_per_million"]
        + queries * gigabytes / GB_PER_TB * price["query_data_per_tb"]
    )


def invocation_logging(review: Review, state: State) -> float:
    if not state.invocation_logging:
        return 0.0
    requests = sum(route["requests_per_month"] for route in review.routes.values())
    gigabytes = requests * review.workload["assumptions"]["invocation_log_kb_per_request"] / KB_PER_GB
    price = review.pricing["cloudwatch_logs"]
    return gigabytes * (price["ingestion_per_gb"] + price["storage_gb_month"])


def components(review: Review, state: State) -> dict[str, float]:
    return {
        "ask route tokens": route_tokens(review, state, "ask"),
        "compare route tokens": route_tokens(review, state, "compare"),
        "enrich job tokens": route_tokens(review, state, "enrich"),
        "embeddings": embeddings(review),
        "guardrails": guardrails(review, state),
        "vector store": vector_store(review, state),
        "invocation logging": invocation_logging(review, state),
    }


def total(review: Review, state: State) -> float:
    return sum(components(review, state).values())


@dataclass(frozen=True)
class CostModel:
    before: dict[str, float]
    after: dict[str, float]
    levers: list[tuple[str, str, float]]
    cur_by_period: dict[str, float]
    cur_latest_modeled: float

    @property
    def before_total(self) -> float:
        return sum(self.before.values())

    @property
    def after_total(self) -> float:
        return sum(self.after.values())

    @property
    def reconciliation_gap(self) -> float:
        """Relative difference between the modeled as-found total and the latest CUR month."""
        return abs(self.before_total - self.cur_latest_modeled) / self.cur_latest_modeled


def build(review: Review) -> CostModel:
    start = as_found(review)
    state = start
    levers = []
    for lever, label in LEVERS:
        nxt = apply(review, state, lever)
        levers.append((lever, label, total(review, nxt) - total(review, state)))
        state = nxt
    by_period: dict[str, float] = {}
    for row in review.snapshot.cur_rows:
        by_period[row["billing_period"]] = by_period.get(row["billing_period"], 0.0) + float(row["unblended_cost_usd"])
    by_period = dict(sorted(by_period.items()))
    return CostModel(
        before=components(review, start),
        after=components(review, state),
        levers=levers,
        cur_by_period=by_period,
        cur_latest_modeled=by_period[max(by_period)],
    )
