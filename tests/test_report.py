"""The report and evidence/ are reproduced from data/.

1. Byte-for-byte: regenerating from the data gives exactly the committed files (the same check as `make check`).
2. Independent: headline numbers printed in the report are recomputed from the raw files by tests/reference.py.
"""

from __future__ import annotations

import csv
import re
import subprocess

import pytest
import yaml

import reference
from genai_review.__main__ import main, outputs
from genai_review.findings import RISK_ORDER
from genai_review.render import Renderer, usd

ALLOWED_ACCOUNT_IDS = {"111122223333", "444455556666", "123456789012"}


@pytest.fixture
def report(repo_root) -> str:
    return (repo_root / "report" / "REPORT.md").read_text(encoding="utf-8")


def table_after(text: str, header_start: str) -> list[list[str]]:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(header_start))
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def test_committed_outputs_match_a_fresh_generation(repo_root, capsys):
    for relative, content in outputs(repo_root).items():
        assert (repo_root / relative).read_text(encoding="utf-8") == content, f"{relative} is stale"
    assert main(["check", "--root", str(repo_root)]) == 0
    assert "outputs match" in capsys.readouterr().out


def test_check_fails_when_the_evidence_changes(repo_copy):
    assert main(["check", "--root", str(repo_copy)]) == 0
    plan = repo_copy / "data" / "synthetic" / "as-found" / "terraform-plan.json"
    plan.write_text(plan.read_text(encoding="utf-8").replace('"GUARDRAIL_ID": "",', '"GUARDRAIL_ID": "gr-x",'))
    assert main(["check", "--root", str(repo_copy)]) == 1


def test_check_reports_bad_data_as_an_error(repo_copy, capsys):
    (repo_copy / "data" / "synthetic" / "as-found" / "ci-pipeline.yaml").unlink()
    assert main(["check", "--root", str(repo_copy)]) == 2
    assert "ci-pipeline.yaml" in capsys.readouterr().err


def test_summary_is_recomputed_independently(repo_root, report):
    ref = reference.load(repo_root)
    summary = dict((row[0], row[1]) for row in table_after(report, "| Measure |"))
    before, after = reference.before_total(ref), reference.after_total(ref)
    assert summary["Modeled monthly cost as found"] == usd(before)
    assert summary["Modeled monthly cost after the fixes"] == usd(after)
    assert summary["Monthly difference"] == f"{usd(after - before)} ({(after - before) / before:.0%})"
    growth = reference.cur_total(ref, "month-3") / reference.cur_total(ref, "month-1") - 1
    assert summary["GenAI spend, month-1 to month-3 (CUR)"].endswith(f"(+{growth:.0%})")


def test_findings_table_is_ranked_by_risk_and_matches_the_csv(repo_root, report):
    rows = table_after(report, "| Key | Risk |")
    risks = [row[1].lower() for row in rows]
    assert risks == sorted(risks, key=RISK_ORDER.__getitem__)
    with (repo_root / "evidence" / "findings.csv").open(encoding="utf-8") as handle:
        exported = list(csv.DictReader(handle))
    assert [r["key"] for r in exported] == [row[0] for row in rows]
    assert [r["best_practice"] for r in exported] == [row[2] for row in rows]


def test_lens_coverage_matches_the_scope_file(repo_root, report):
    lens = yaml.safe_load((repo_root / "data" / "synthetic" / "lens.yaml").read_text(encoding="utf-8"))
    in_scope = [bp["id"] for pillar in lens["pillars"] for bp in pillar["best_practices"]]
    assert [row[0] for row in table_after(report, "| Best practice | Title |")] == in_scope


def test_every_pillar_with_findings_has_a_block(loaded, report):
    renderer = Renderer(loaded)
    names = {p["name"]: p["key"] for p in loaded.pillars}
    for pillar in {f.pillar for f in renderer.findings}:
        assert f"<!-- BEGIN GENERATED: findings:{names[pillar]} -->" in report, pillar
    assert sum(report.count(f"#### {f.key}. ") for f in renderer.findings) == len(renderer.findings)


def test_roadmap_never_schedules_a_dependency_after_its_dependent(loaded):
    findings = Renderer(loaded).findings
    phase = {f.key: f.phase for f in findings}
    for f in findings:
        for dep in f.depends_on:
            assert phase[dep] <= phase[f.key], (f.key, dep)


def test_report_cites_known_evidence_only(repo_root, report):
    known = {e["id"] for e in yaml.safe_load((repo_root / "data/synthetic/evidence.yaml").read_text())["evidence"]}
    assert set(re.findall(r"EV-\d+", report)) <= known


def test_a_malformed_generated_marker_is_refused(loaded, report):
    broken = report.replace("<!-- BEGIN GENERATED: roadmap -->", "<!-- BEGIN GENERATED roadmap -->")
    assert broken != report
    with pytest.raises(ValueError, match="malformed or unpaired"):
        Renderer(loaded).document(broken)


def test_an_unknown_block_is_refused(loaded):
    with pytest.raises(ValueError, match="unknown generated block"):
        Renderer(loaded).block("totals")


def test_only_documentation_example_account_ids_appear(repo_root):
    # Only files git tracks. /usr/bin/git exists on macOS and the Ubuntu CI runner; an absolute literal keeps ruff's
    # S603/S607 satisfied.
    suffixes = {".md", ".yaml", ".yml", ".csv", ".json", ".jsonl", ".py", ".toml", ".tf", ".hcl", ".ini", ".sh"}
    tracked = subprocess.run(
        ["/usr/bin/git", "ls-files", "-z"], cwd=repo_root, check=True, capture_output=True, text=True
    ).stdout.split("\0")
    for name in filter(None, tracked):
        path = repo_root / name
        if path.suffix not in suffixes or not path.is_file():
            continue
        found = set(re.findall(r"(?<!\d)\d{12}(?!\d)", path.read_text(encoding="utf-8", errors="ignore")))
        assert found <= ALLOWED_ACCOUNT_IDS, f"{name}: {found - ALLOWED_ACCOUNT_IDS}"
