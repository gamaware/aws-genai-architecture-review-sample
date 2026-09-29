"""An independent recomputation of the report's cost figures, straight from the YAML and CSV files.

It shares no code with scripts/genai_review: it re-reads the files and prices each route by hand, so an error in the
cost model shows up as a disagreement with this module.
"""

from __future__ import annotations

import csv
import json
from math import ceil
from pathlib import Path

import yaml


def load(root: Path) -> dict:
    data = root / "data"
    found = data / "synthetic" / "as-found"
    with (found / "cur-genai.csv").open(encoding="utf-8") as handle:
        cur = list(csv.DictReader(handle))
    with (found / "eval-results.csv").open(encoding="utf-8") as handle:
        evals = list(csv.DictReader(handle))
    plan = json.loads((found / "terraform-plan.json").read_text(encoding="utf-8"))
    env = {
        r["name"]: r["values"]["environment"][0]["variables"]
        for r in plan["planned_values"]["root_module"]["resources"]
        if r["type"] == "aws_lambda_function"
    }
    return {
        "workload": yaml.safe_load((data / "synthetic" / "workload.yaml").read_text(encoding="utf-8")),
        "prices": yaml.safe_load((data / "pricing.yaml").read_text(encoding="utf-8")),
        "cur": cur,
        "evals": evals,
        "env": env,
    }


def _price(ref: dict, model: str) -> dict:
    """Token prices with the 10% geographic premium on us. Claude profiles; Nova has none."""
    p = ref["prices"]["models"][model]
    geographic = p["model_id"].split(".")[0] in ("us", "eu", "apac")
    factor = 1 + p["geographic_premium"] if geographic else 1
    return {k: p[k] * factor for k in ("input", "output", "cache_write", "cache_read")}


def _tokens(ref: dict, route: str, model: str, cached: bool, batch: bool) -> float:
    r = ref["workload"]["routes"][route]
    p = _price(ref, model)
    n = r["requests_per_month"]
    hit = ref["workload"]["assumptions"]["prompt_cache_hit_rate"]
    # Caching only counts when the system prompt reaches the model's minimum checkpoint size.
    cached = cached and r["system_prompt_tokens"] >= ref["prices"]["models"][model]["min_cache_tokens"]
    prefix_price = (hit * p["cache_read"] + (1 - hit) * p["cache_write"]) if cached else p["input"]
    dollars = (
        n * r["system_prompt_tokens"] * prefix_price
        + n * (r["context_tokens"] + r["user_tokens"]) * p["input"]
        + n * r["output_tokens"] * p["output"]
    ) / 1e6
    return dollars * (ref["prices"]["batch_price_factor"] if batch else 1)


def _units(ref: dict, tokens: int) -> int:
    a = ref["workload"]["assumptions"]
    return ceil(tokens * a["chars_per_token"] / a["guardrail_text_unit_chars"])


def _guardrail(ref: dict, route: str, policies: list[str]) -> float:
    r = ref["workload"]["routes"][route]
    units = r["requests_per_month"] * (_units(ref, r["user_tokens"]) + _units(ref, r["output_tokens"]))
    return units / 1000 * sum(ref["prices"]["guardrails"][p] for p in policies)


def _queries(ref: dict) -> int:
    routes = ref["workload"]["routes"]
    return routes["ask"]["requests_per_month"] + routes["compare"]["requests_per_month"]


def _embeddings(ref: dict) -> float:
    kb = ref["workload"]["knowledge_base"]
    tokens = kb["embedding_tokens_per_month"] + _queries(ref) * kb["query_embedding_tokens"]
    return tokens / 1e6 * ref["prices"]["embeddings"]["per_million_tokens"]


def before_total(ref: dict) -> float:
    ask_policies = ref["env"]["ask"]["GUARDRAIL_POLICIES"].split(",")
    latest = max(row["billing_period"] for row in ref["cur"])
    ocu_hours = sum(
        float(r["usage_amount"]) for r in ref["cur"] if r["billing_period"] == latest and "OCU" in r["usage_type"]
    )
    return (
        _tokens(ref, "ask", "claude-sonnet", cached=False, batch=False)
        + _tokens(ref, "compare", "claude-sonnet", cached=False, batch=False)
        + _tokens(ref, "enrich", "claude-sonnet", cached=False, batch=False)
        + _embeddings(ref)
        + _guardrail(ref, "ask", ask_policies)
        + ocu_hours * ref["prices"]["opensearch_serverless"]["ocu_hour"]
    )


def after_total(ref: dict) -> float:
    all_policies = ["content_filter", "denied_topics", "sensitive_information"]
    kb = ref["workload"]["knowledge_base"]
    s3v = ref["prices"]["s3_vectors"]
    queries = _queries(ref)
    vectors = (
        kb["vector_data_gb"] * s3v["storage_gb_month"]
        + queries / 1e6 * s3v["query_per_million"]
        + queries * kb["vector_data_gb"] / 1000 * s3v["query_data_per_tb"]
    )
    requests = sum(r["requests_per_month"] for r in ref["workload"]["routes"].values())
    log_gb = requests * ref["workload"]["assumptions"]["invocation_log_kb_per_request"] / 1e6
    logs = log_gb * (
        ref["prices"]["cloudwatch_logs"]["ingestion_per_gb"] + ref["prices"]["cloudwatch_logs"]["storage_gb_month"]
    )
    return (
        _tokens(ref, "ask", "claude-haiku", cached=True, batch=False)
        + _tokens(ref, "compare", "claude-sonnet", cached=True, batch=False)
        + _tokens(ref, "enrich", "claude-sonnet", cached=False, batch=True)
        + _embeddings(ref)
        + _guardrail(ref, "ask", all_policies)
        + _guardrail(ref, "compare", all_policies)
        + vectors
        + logs
    )


def cur_total(ref: dict, period: str) -> float:
    return sum(float(r["unblended_cost_usd"]) for r in ref["cur"] if r["billing_period"] == period)


def pass_rate(ref: dict, route: str, model: str) -> tuple[float, float]:
    rows = [r for r in ref["evals"] if r["route"] == route and r["model"] == model]
    overall = sum(int(r["passed"]) for r in rows) / sum(int(r["questions"]) for r in rows)
    weakest = min(int(r["passed"]) / int(r["questions"]) for r in rows)
    return overall, weakest
