"""The application fixes, exercised against stubbed Bedrock clients (no AWS calls)."""

from __future__ import annotations

import json
import logging

import pytest

import assistant
import enrich_batch
import eval_gate

CONFIG = assistant.RouteConfig(
    route="ask",
    model_id="arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/example",
    guardrail_id="gr-assistant",
    guardrail_version="1",
    max_tokens=512,
    system_prompt="You answer questions about Harbor Goods products.",
)
QUESTION = assistant.Question(
    request_id="r-1",
    text="Call me at 555-010-0142 about the Harbor tent",
    context=("The Harbor tent is waterproof to 3,000 mm.",),
)
RESPONSE = {
    "output": {"message": {"content": [{"text": "Yes, it is waterproof."}]}},
    "stopReason": "end_turn",
    "usage": {"inputTokens": 120, "outputTokens": 8, "cacheReadInputTokens": 2400},
}


class Throttled(Exception):
    def __init__(self, code: str = "ThrottlingException") -> None:
        super().__init__(f"{code}: slow down, caller 555-010-0199")
        self.response = {"Error": {"Code": code}}


class StubRuntime:
    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = list(failures or [])
        self.calls: list[dict] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        return RESPONSE


def no_wait() -> assistant.RetryPolicy:
    return assistant.RetryPolicy(attempts=3, base_delay=0.2, sleep=lambda _: None)


def test_request_caches_the_system_prompt_and_guards_the_question():
    request = assistant.build_request(CONFIG, QUESTION)
    assert request["system"][-1] == {"cachePoint": {"type": "default"}}
    assert request["guardrailConfig"]["guardrailIdentifier"] == "gr-assistant"
    assert request["guardrailConfig"]["guardrailVersion"] == "1"
    guarded = [block for block in request["messages"][0]["content"] if "guardContent" in block]
    assert guarded == [{"guardContent": {"text": {"text": QUESTION.text}}}]
    assert request["inferenceConfig"]["maxTokens"] == 512


def test_logs_carry_no_prompt_or_answer(caplog):
    with caplog.at_level(logging.INFO):
        result = assistant.answer(StubRuntime(), CONFIG, QUESTION, logging.getLogger("t"), no_wait())
    assert result["text"] == "Yes, it is waterproof."
    record = json.loads(caplog.records[-1].getMessage())
    assert record["cache_read_tokens"] == 2400
    assert "555" not in caplog.text
    assert "waterproof" not in caplog.text


def test_throttling_is_retried_with_backoff():
    delays: list[float] = []
    stub = StubRuntime([Throttled(), Throttled()])
    policy = assistant.RetryPolicy(attempts=3, base_delay=0.2, sleep=delays.append)
    assistant.answer(stub, CONFIG, QUESTION, logging.getLogger("t"), policy)
    assert len(stub.calls) == 3
    assert delays == pytest.approx([0.2, 0.4])


def test_other_errors_fail_fast_with_redacted_logs(caplog):
    stub = StubRuntime([Throttled("ValidationException")])
    with pytest.raises(Throttled), caplog.at_level(logging.ERROR):
        assistant.answer(stub, CONFIG, QUESTION, logging.getLogger("t"), no_wait())
    assert len(stub.calls) == 1
    assert "[PHONE]" in caplog.text
    assert "555-010-0199" not in caplog.text


def test_retries_stop_after_the_last_attempt():
    stub = StubRuntime([Throttled(), Throttled(), Throttled()])
    with pytest.raises(Throttled):
        assistant.answer(stub, CONFIG, QUESTION, logging.getLogger("t"), no_wait())
    assert len(stub.calls) == 3


def test_guardrail_intervention_is_reported():
    class Blocking(StubRuntime):
        def converse(self, **kwargs):
            return {**RESPONSE, "stopReason": "guardrail_intervened"}

    assert assistant.answer(Blocking(), CONFIG, QUESTION, logging.getLogger("t"), no_wait())["guardrail_intervened"]


@pytest.mark.parametrize(
    "overrides",
    [{"guardrail_id": ""}, {"guardrail_version": ""}, {"max_tokens": 0}, {"max_tokens": 4096}],
)
def test_route_config_refuses_unsafe_settings(overrides):
    fields = {**CONFIG.__dict__, **overrides}
    with pytest.raises(ValueError, match="route ask"):
        assistant.RouteConfig(**fields)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("call 555-010-0142", "call [PHONE]"),
        ("card HG-LOY-20481733", "card [LOYALTY]"),
        ("mail shopper@example.com", "mail [EMAIL]"),
    ],
)
def test_redaction(text, expected):
    assert assistant.redact(text) == expected


def test_batch_records_and_request():
    products = [{"sku": f"SKU-{i}", "source_text": f"Product {i}"} for i in range(2)]
    lines = enrich_batch.records(products, "Rewrite for search.", 400).splitlines()
    first = json.loads(lines[0])
    assert first["recordId"] == "SKU-0"
    assert first["modelInput"]["max_tokens"] == 400
    request = enrich_batch.job_request(
        "enrich-nightly",
        "arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/enrich",
        "arn:aws:iam::111122223333:role/product-assistant-batch",
        "s3://example-bucket/enrich/in/",
        "s3://example-bucket/enrich/out/",
    )
    assert request["inputDataConfig"]["s3InputDataConfig"]["s3InputFormat"] == "JSONL"


def test_batch_request_needs_s3_uris():
    with pytest.raises(ValueError, match="not an S3 URI"):
        enrich_batch.job_request("j", "arn", "role", "file:///data/in", "s3://b/out/")


def test_batch_submit_skips_small_nights():
    class Control:
        def __init__(self) -> None:
            self.submitted = 0

        def create_model_invocation_job(self, **kwargs):
            self.submitted += 1
            return {"jobArn": "arn:aws:bedrock:us-east-1:111122223333:model-invocation-job/abc"}

    control = Control()
    assert enrich_batch.submit(control, enrich_batch.MIN_RECORDS - 1, {}) is None
    assert enrich_batch.submit(control, enrich_batch.MIN_RECORDS, {}).endswith("/abc")
    assert control.submitted == 1


def test_eval_gate_on_the_review_results(repo_root, tmp_path, capsys):
    source = repo_root / "data" / "synthetic" / "as-found" / "eval-results.csv"
    rows = source.read_text(encoding="utf-8").splitlines()
    shipping = [rows[0]] + [r for r in rows[1:] if r.startswith(("ask,claude-haiku", "compare,claude-sonnet"))]
    passing = tmp_path / "passing.csv"
    passing.write_text("\n".join(shipping) + "\n", encoding="utf-8")
    assert eval_gate.main([str(passing)]) == 0
    assert "passed" in capsys.readouterr().out

    assert eval_gate.main([str(source)]) == 1
    err = capsys.readouterr().err
    assert "compare/claude-haiku" in err
    assert "ask/nova-lite" in err
    assert "ask/claude-haiku" not in err


def test_eval_gate_blocks_empty_results():
    assert eval_gate.evaluate([], 0.9, 0.85) == ["no evaluation results"]
