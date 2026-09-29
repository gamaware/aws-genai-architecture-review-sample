"""Every scripted check fails on the as-found evidence where the report says it does, and passes once fixed."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from genai_review import costmodel
from genai_review.checks import REGISTRY, eval_pass_rates, model_key, qualifies, run_all, unit_prices
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
        "textDataDeliveryEnabled": False
    }


def fix_throttling(review: Review) -> None:
    review.snapshot.resources["aws_api_gateway_method_settings.all"]["values"]["settings"][0][
        "throttling_rate_limit"
    ] = 60
    review.snapshot.resources["aws_api_gateway_usage_plan.web"] = {"type": "aws_api_gateway_usage_plan", "values": {}}
    for method in review.snapshot.resources_of("aws_api_gateway_method").values():
        method["values"]["api_key_required"] = True


def fix_eval(review: Review) -> None:
    review.snapshot.pipeline["stages"].insert(4, {"name": "evaluate-golden-set"})


PROFILE_ARN = "arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/{}"
US_REGIONS = ("us-east-1", "us-east-2", "us-west-2")
# What the delivered Terraform creates: one application profile per route, copied from the us. system profile, so
# each lists the foundation model in the three US Regions. The functions then call the profile ARN as MODEL_ID.
ROUTE_MODELS = {"ask": "claude-haiku", "compare": "claude-sonnet", "enrich": "claude-sonnet"}


def fix_profiles(review: Review) -> None:
    listed = review.snapshot.bedrock_settings["list-inference-profiles --type-equals APPLICATION"]
    listed["inferenceProfileSummaries"] = [
        {
            "inferenceProfileName": f"product-assistant-{route}",
            "inferenceProfileArn": PROFILE_ARN.format(route),
            "type": "APPLICATION",
            "status": "ACTIVE",
            "models": [
                {
                    "modelArn": f"arn:aws:bedrock:{region}::foundation-model/"
                    + review.pricing["models"][ROUTE_MODELS[route]]["foundation_model"]
                }
                for region in US_REGIONS
            ],
        }
        for route in review.routes
    ]


def fix_model(review: Review) -> None:
    fix_profiles(review)
    _env(review, "ask")["MODEL_ID"] = PROFILE_ARN.format("ask")


def use_profile_arns(review: Review) -> None:
    """Every function calls its application inference profile ARN, as the delivered fix tells the client to."""
    fix_profiles(review)
    for route in review.routes:
        _env(review, route)["MODEL_ID"] = PROFILE_ARN.format(route)


def fix_caching(review: Review) -> None:
    for route in ("ask", "compare"):
        _env(review, route)["PROMPT_CACHING"] = "true"


def fix_vectors(review: Review) -> None:
    review.snapshot.cur_rows[:] = [r for r in review.snapshot.cur_rows if not r["usage_type"].endswith("OCU")]


def fix_batch(review: Review) -> None:
    _env(review, "enrich")["INFERENCE_MODE"] = "batch"


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
    use_profile_arns(review)
    results = run_all(review)
    assert all(result.passed for result in results.values()), {
        c: r.observed for c, r in results.items() if not r.passed
    }


def test_a_rerun_on_the_fixed_state_prices_the_profile_arns(review, loaded):
    for fix in FIXES.values():
        fix(review)
    use_profile_arns(review)
    state = costmodel.as_found(review)
    assert state.models == ROUTE_MODELS
    assert state.cached == frozenset({"ask", "compare"})
    # The ask route asks for caching but runs on Claude Haiku, whose 4,096-token minimum its prompt does not reach.
    recommended = costmodel.recommended(loaded)
    for route in ROUTE_MODELS:
        assert costmodel.route_tokens(review, state, route) == pytest.approx(
            costmodel.route_tokens(loaded, recommended, route)
        )


def test_application_profile_arn_resolves_to_its_model(review):
    use_profile_arns(review)
    assert model_key(review, PROFILE_ARN.format("ask")) == "claude-haiku"
    assert model_key(review, PROFILE_ARN.format("compare")) == "claude-sonnet"
    with pytest.raises(KeyError, match="not in the Bedrock settings export"):
        model_key(review, PROFILE_ARN.format("unknown"))


def test_single_region_application_profile_fails_the_cross_region_check(review):
    use_profile_arns(review)
    assert REGISTRY["cross-region-inference"](review).passed
    summary = review.snapshot.bedrock_settings["list-inference-profiles --type-equals APPLICATION"][
        "inferenceProfileSummaries"
    ][2]
    summary["models"] = summary["models"][:1]
    result = REGISTRY["cross-region-inference"](review)
    assert not result.passed
    assert "enrich" in result.observed


def test_invocation_logging_with_text_delivery_fails(review):
    config = review.snapshot.bedrock_settings["get-model-invocation-logging-configuration"]
    config["loggingConfig"] = {"textDataDeliveryEnabled": True}
    result = REGISTRY["invocation-logging"](review)
    assert not result.passed
    assert "raw prompts" in result.observed


def test_usage_plans_without_api_keys_fail(review):
    fix_throttling(review)
    review.snapshot.resources["aws_api_gateway_method.compare"]["values"]["api_key_required"] = False
    result = REGISTRY["api-throttling"](review)
    assert not result.passed
    assert "1 of 2 methods" in result.observed


def test_caching_is_not_required_below_the_model_minimum(review):
    fix_model(review)
    _env(review, "compare")["PROMPT_CACHING"] = "true"
    result = REGISTRY["prompt-caching"](review)
    assert result.passed
    assert "4,096" in result.observed
    _env(review, "compare")["PROMPT_CACHING"] = "false"
    assert not REGISTRY["prompt-caching"](review).passed


def test_geographic_profiles_carry_the_premium(review):
    assert unit_prices(review, "claude-sonnet")["input"] == pytest.approx(3.30)
    assert unit_prices(review, "claude-haiku")["cache_read"] == pytest.approx(0.11)
    assert unit_prices(review, "nova-lite")["input"] == pytest.approx(0.06)
    review.pricing["models"]["claude-sonnet"]["model_id"] = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    assert unit_prices(review, "claude-sonnet")["input"] == pytest.approx(3.00)


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
