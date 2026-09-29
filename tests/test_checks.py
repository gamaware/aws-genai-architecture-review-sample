"""Every scripted check fails on the as-found evidence where the report says it does, and passes once fixed."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from genai_review.checks import REGISTRY, eval_pass_rates, qualifies, run_all
from genai_review.model import Review

EXPECTED_FAILING = {
    "guardrail-every-route",
    "scoped-bedrock-access",
    "pii-in-logs",
    "invocation-logging",
    "api-throttling",
    "eval-in-pipeline",
    "right-sized-model",
    "prompt-caching",
    "vector-store-sizing",
    "batch-for-offline-jobs",
    "application-inference-profiles",
}


def test_as_found_results(loaded):
    results = run_all(loaded)
    assert {c for c, r in results.items() if not r.passed} == EXPECTED_FAILING
    assert {c for c, r in results.items() if r.passed} == {"cross-region-inference", "max-tokens-set"}


def _env(review: Review, route: str) -> dict:
    return review.snapshot.lambda_env(route)


def fix_guardrail(review: Review) -> None:
    _env(review, "compare")["GUARDRAIL_ID"] = "gr-assistant"


def fix_iam(review: Review) -> None:
    statement = review.snapshot.iam_role["InlinePolicies"][0]["PolicyDocument"]["Statement"][0]
    statement["Action"] = ["bedrock:InvokeModel"]
    statement["Resource"] = ["arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/example"]


def fix_pii(review: Review) -> None:
    for event in review.snapshot.log_events:
        event.pop("prompt", None)
    for group in review.snapshot.resources_of("aws_cloudwatch_log_group").values():
        group["values"]["retention_in_days"] = 365
        group["values"]["kms_key_id"] = "arn:aws:kms:us-east-1:111122223333:key/example"


def fix_logging(review: Review) -> None:
    review.snapshot.bedrock_settings["get-model-invocation-logging-configuration"]["loggingConfig"] = {
        "textDataDeliveryEnabled": True
    }


def fix_throttling(review: Review) -> None:
    review.snapshot.resources["aws_api_gateway_method_settings.all"]["values"]["settings"][0][
        "throttling_rate_limit"
    ] = 60
    review.snapshot.resources["aws_api_gateway_usage_plan.web"] = {"type": "aws_api_gateway_usage_plan", "values": {}}


def fix_eval(review: Review) -> None:
    review.snapshot.pipeline["stages"].insert(4, {"name": "evaluate-golden-set"})


def fix_model(review: Review) -> None:
    _env(review, "ask")["MODEL_ID"] = review.pricing["models"]["claude-haiku"]["model_id"]


def fix_caching(review: Review) -> None:
    for route in ("ask", "compare"):
        _env(review, route)["PROMPT_CACHING"] = "true"


def fix_vectors(review: Review) -> None:
    review.snapshot.cur_rows[:] = [r for r in review.snapshot.cur_rows if not r["usage_type"].endswith("OCU")]


def fix_batch(review: Review) -> None:
    _env(review, "enrich")["INFERENCE_MODE"] = "batch"


def fix_profiles(review: Review) -> None:
    listed = review.snapshot.bedrock_settings["list-inference-profiles --type-equals APPLICATION"]
    listed["inferenceProfileSummaries"] = [{"name": route} for route in review.routes]


FIXES: dict[str, Callable[[Review], None]] = {
    "guardrail-every-route": fix_guardrail,
    "scoped-bedrock-access": fix_iam,
    "pii-in-logs": fix_pii,
    "invocation-logging": fix_logging,
    "api-throttling": fix_throttling,
    "eval-in-pipeline": fix_eval,
    "right-sized-model": fix_model,
    "prompt-caching": fix_caching,
    "vector-store-sizing": fix_vectors,
    "batch-for-offline-jobs": fix_batch,
    "application-inference-profiles": fix_profiles,
}


def test_every_failing_check_has_a_fix_test():
    assert set(FIXES) == EXPECTED_FAILING


@pytest.mark.parametrize("check_id", sorted(FIXES))
def test_check_passes_once_fixed(review, check_id):
    assert not REGISTRY[check_id](review).passed
    FIXES[check_id](review)
    assert REGISTRY[check_id](review).passed


def test_all_fixes_together_leave_no_finding(review):
    for fix in FIXES.values():
        fix(review)
    assert all(result.passed for result in run_all(review).values())


def test_single_region_model_id_fails_the_cross_region_check(review):
    _env(review, "enrich")["MODEL_ID"] = "anthropic.claude-sonnet-4-5-20250929-v1:0"
    result = REGISTRY["cross-region-inference"](review)
    assert not result.passed
    assert "enrich" in result.observed


def test_missing_or_large_max_tokens_fails(review):
    _env(review, "compare")["MAX_TOKENS"] = "8192"
    del _env(review, "ask")["MAX_TOKENS"]
    result = REGISTRY["max-tokens-set"](review)
    assert not result.passed
    assert "ask" in result.observed
    assert "compare" in result.observed


def test_quality_bar_uses_overall_and_weakest_category(loaded):
    rates = eval_pass_rates(loaded)
    assert qualifies(rates["ask"]["claude-haiku"])
    assert not qualifies(rates["ask"]["nova-lite"])  # overall under 90% and one category at 80%
    assert not qualifies(rates["compare"]["claude-haiku"])
    assert qualifies(rates["compare"]["claude-sonnet"])
