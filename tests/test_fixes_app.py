"""The application fixes, exercised against stubbed Bedrock clients (no AWS calls)."""

from __future__ import annotations

import csv
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


COMPARE = assistant.RouteConfig(
    route="compare",
    model_id="arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/compare",
    guardrail_id="gr-assistant",
    guardrail_version="1",
    max_tokens=1024,
    system_prompt="You compare Harbor Goods products.",
    cache_system_prompt=True,
)


def test_cache_point_only_where_the_prompt_reaches_the_model_minimum():
    # compare runs Claude Sonnet 4.5 (1,024-token minimum); ask runs Claude Haiku 4.5 (4,096) with a 2,400-token prompt.
    assert assistant.build_request(COMPARE, QUESTION)["system"][-1] == {"cachePoint": {"type": "default"}}
    assert assistant.build_request(CONFIG, QUESTION)["system"] == [{"text": CONFIG.system_prompt}]


def test_request_guards_the_question():
    request = assistant.build_request(CONFIG, QUESTION)
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


def _golden(repo_root) -> dict:
    return eval_gate.load_expected(repo_root / "fixes" / "pipeline" / "golden-set.json")


def _shipping_rows(repo_root) -> list[dict]:
    source = repo_root / "data" / "synthetic" / "as-found" / "eval-results.csv"
    with source.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [r for r in rows if (r["route"], r["model"]) in {("ask", "claude-haiku"), ("compare", "claude-sonnet")}]


def _write(path, rows: list[dict]) -> str:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["route", "model", "category", "questions", "passed"])
        writer.writeheader()
        writer.writerows(rows)
    return str(path)


def test_eval_gate_passes_the_complete_shipping_run(repo_root, tmp_path, capsys):
    expected = str(repo_root / "fixes" / "pipeline" / "golden-set.json")
    passing = _write(tmp_path / "passing.csv", _shipping_rows(repo_root))
    assert eval_gate.main([passing, "--expected", expected]) == 0
    assert "passed" in capsys.readouterr().out


def test_eval_gate_blocks_the_quality_bar(repo_root):
    rows = _shipping_rows(repo_root)
    for row in rows:
        if row["route"] == "ask" and row["category"] == "sizing":
            row["passed"] = "15"
    failures = eval_gate.evaluate(rows, _golden(repo_root), 0.90, 0.85)
    assert failures == ["ask/claude-haiku: 91.4% overall (bar 90%), sizing 75.0% (bar 85%)"]


def test_eval_gate_blocks_a_run_of_one_passing_question(repo_root):
    rows = [{"route": "ask", "model": "claude-haiku", "category": "availability", "questions": "1", "passed": "1"}]
    failures = eval_gate.evaluate(rows, _golden(repo_root), 0.90, 0.85)
    assert "ask/claude-haiku: availability has 1 of 40 expected questions" in failures
    assert "compare/claude-sonnet: price-value has 0 of 30 expected questions" in failures
    assert len(failures) == 8


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda rows: rows.pop(), "compatibility has 0 of 20 expected questions"),
        (lambda rows: rows[0].update(model="nova-lite"), "ask/nova-lite: not the model ask ships with"),
        (lambda rows: rows[0].update(category="warranty"), "category warranty is not in the golden set"),
        (lambda rows: rows[0].update(route="search"), "search: not a route of the golden set"),
        (lambda rows: rows.append(dict(rows[0])), "appears twice"),
        (lambda rows: rows[0].update(passed="41"), "41 passed of 40 questions"),
        (lambda rows: rows[0].update(questions="many"), "must be whole numbers"),
    ],
)
def test_eval_gate_blocks_incomplete_or_foreign_results(repo_root, change, message):
    rows = _shipping_rows(repo_root)
    change(rows)
    failures = eval_gate.evaluate(rows, _golden(repo_root), 0.90, 0.85)
    assert any(message in line for line in failures), failures


def test_eval_gate_on_all_three_models_blocks_the_release(repo_root, capsys):
    source = repo_root / "data" / "synthetic" / "as-found" / "eval-results.csv"
    expected = str(repo_root / "fixes" / "pipeline" / "golden-set.json")
    assert eval_gate.main([str(source), "--expected", expected]) == 1
    err = capsys.readouterr().err
    assert "compare/claude-haiku: not the model compare ships with" in err
    assert "ask/nova-lite: not the model ask ships with" in err


def test_eval_gate_blocks_empty_results_and_expectations(repo_root):
    assert eval_gate.evaluate([], _golden(repo_root), 0.9, 0.85) == ["no evaluation results"]
    assert eval_gate.evaluate(_shipping_rows(repo_root), {}, 0.9, 0.85) == ["no golden-set expectations"]


def test_golden_set_expectations_are_validated(tmp_path):
    path = tmp_path / "golden.json"
    path.write_text(json.dumps({"routes": {"ask": {"model": "claude-haiku", "categories": {"sizing": 0}}}}))
    with pytest.raises(ValueError, match="positive question count"):
        eval_gate.load_expected(path)
