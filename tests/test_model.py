"""Validation refuses data the report cannot stand on."""

from __future__ import annotations

import pytest
import yaml

from genai_review.model import ReviewError, load


def _edit(path, change):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_repository_data_is_valid(repo_root):
    review = load(repo_root / "data")
    assert len(review.checks) == 13


@pytest.mark.parametrize(
    ("file", "change", "message"),
    [
        ("lens.yaml", lambda d: d["pillars"][0]["best_practices"][0].update(id="OPS01-BP01"), "not a Generative AI"),
        ("lens.yaml", lambda d: d["pillars"][0]["best_practices"][1].update(status="partial"), "needs status met"),
        ("lens.yaml", lambda d: d["pillars"][0]["best_practices"][1].update(evidence=["EV-99"]), "unknown evidence"),
        ("lens.yaml", lambda d: d["pillars"][0]["best_practices"][0].update(checks=["nope"]), "unknown check"),
        ("checks.yaml", lambda d: d["checks"][0].update(risk="critical"), "risk 'critical'"),
        ("checks.yaml", lambda d: d["checks"][0].update(effort="XL"), "effort 'XL'"),
        ("checks.yaml", lambda d: d["checks"][0].update(fix=["fixes/missing.tf"]), "does not exist"),
        ("checks.yaml", lambda d: d["checks"][0].update(depends_on=["nope"]), "unknown dependency"),
        ("checks.yaml", lambda d: d["checks"].pop(), "has no metadata"),
        ("evidence.yaml", lambda d: d["evidence"][0].update(path="as-found/missing.json"), "does not exist"),
    ],
)
def test_bad_data_is_refused(repo_copy, file, change, message):
    _edit(repo_copy / "data" / "synthetic" / file, change)
    with pytest.raises(ReviewError, match=message):
        load(repo_copy / "data")


def test_question_must_match_its_best_practice(repo_copy):
    def change(data):
        data["pillars"][1]["best_practices"][0]["question"] = "GENOPS01: wrong question"

    _edit(repo_copy / "data" / "synthetic" / "lens.yaml", change)
    with pytest.raises(ReviewError, match="question does not start with GENSEC01"):
        load(repo_copy / "data")
