"""The cost model agrees with an independent recomputation and with the bill."""

from __future__ import annotations

import pytest

import reference
from genai_review import costmodel


@pytest.fixture
def ref(repo_root):
    return reference.load(repo_root)


def test_totals_match_the_independent_recomputation(loaded, ref):
    model = costmodel.build(loaded)
    assert model.before_total == pytest.approx(reference.before_total(ref), abs=0.005)
    assert model.after_total == pytest.approx(reference.after_total(ref), abs=0.005)


def test_levers_add_up_to_the_net_change(loaded):
    model = costmodel.build(loaded)
    assert sum(change for _, _, change in model.levers) == pytest.approx(model.after_total - model.before_total)
    assert [lever for lever, _, _ in model.levers] == [lever for lever, _ in costmodel.LEVERS]


def test_lever_directions(loaded):
    changes = {lever: change for lever, _, change in costmodel.build(loaded).levers}
    for saving in ("model-right-size", "prompt-caching", "batch-inference", "vector-store"):
        assert changes[saving] < 0, saving
    for added in ("guardrail-coverage", "invocation-logging"):
        assert changes[added] > 0, added


def test_as_found_reconciles_with_the_latest_cur_month(loaded, ref):
    model = costmodel.build(loaded)
    assert model.reconciliation_gap < 0.01
    assert model.cur_latest_modeled == pytest.approx(reference.cur_total(ref, "month-3"))


def test_batch_halves_the_enrich_job(loaded):
    state = costmodel.as_found(loaded)
    batched = costmodel.apply(loaded, state, "batch-inference")
    before = costmodel.route_tokens(loaded, state, "enrich")
    assert costmodel.route_tokens(loaded, batched, "enrich") == pytest.approx(before * 0.5)


def test_caching_never_costs_more_at_the_modeled_hit_rate(loaded):
    state = costmodel.as_found(loaded)
    cached = costmodel.apply(loaded, state, "prompt-caching")
    for route in ("ask", "compare"):
        assert costmodel.route_tokens(loaded, cached, route) < costmodel.route_tokens(loaded, state, route)


def test_model_switch_follows_the_evaluation(loaded, ref):
    state = costmodel.recommended(loaded)
    assert state.models["ask"] == "claude-haiku"
    assert state.models["compare"] == "claude-sonnet"
    overall, weakest = reference.pass_rate(ref, "ask", "claude-haiku")
    assert overall >= 0.90
    assert weakest >= 0.85


def test_a_worse_eval_keeps_the_larger_model(review):
    for row in review.snapshot.eval_rows:
        if row["route"] == "ask" and row["model"] == "claude-haiku" and row["category"] == "sizing":
            row["passed"] = "15"
    state = costmodel.recommended(review)
    assert state.models["ask"] == "claude-sonnet"


def test_unknown_lever_is_refused(loaded):
    with pytest.raises(ValueError, match="unknown lever"):
        costmodel.apply(loaded, costmodel.as_found(loaded), "discount")
