"""Turn failed checks into risk-ranked findings and schedule them into three delivery phases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from genai_review.checks import Result, run_all

if TYPE_CHECKING:
    from genai_review.costmodel import CostModel
    from genai_review.model import Review

RISK_ORDER = {"high": 0, "medium": 1, "low": 2}
EFFORT_ORDER = {"S": 0, "M": 1, "L": 2}
PHASES = ("Weeks 1-2", "Weeks 3-6", "Weeks 7-10")


@dataclass(frozen=True)
class Finding:
    key: str
    check_id: str
    bp_id: str
    bp_title: str
    pillar: str
    title: str
    risk: str
    effort: str
    owner: str
    observed: str
    evidence: tuple[str, ...]
    impact: str
    recommendation: str
    fix: tuple[str, ...]
    monthly_change: float
    depends_on: tuple[str, ...]
    phase: str


def best_practice_index(review: Review) -> dict[str, tuple[dict, dict]]:
    """check id -> (pillar, best practice)."""
    index = {}
    for pillar in review.pillars:
        for bp in pillar["best_practices"]:
            for check_id in bp.get("checks", []):
                index[check_id] = (pillar, bp)
    return index


def lens_status(review: Review, results: dict[str, Result]) -> list[dict]:
    rows = []
    for pillar in review.pillars:
        for bp in pillar["best_practices"]:
            if "checks" in bp:
                status = "met" if all(results[c].passed for c in bp["checks"]) else "not_met"
                evidence = sorted({e for c in bp["checks"] for e in review.checks[c]["evidence"]})
                basis = "scripted check"
            else:
                status, evidence, basis = bp["status"], sorted(bp["evidence"]), "interview and review"
            rows.append(
                {
                    "pillar": pillar["name"],
                    "id": bp["id"],
                    "title": bp["title"],
                    "status": status,
                    "basis": basis,
                    "evidence": evidence,
                }
            )
    return rows


def _phases(failed: list[str], review: Review) -> dict[str, int]:
    """Phase by risk, then pull each dependency forward to the phase of the finding that needs it."""
    phase = {c: RISK_ORDER[review.checks[c]["risk"]] for c in failed}
    changed = True
    while changed:
        changed = False
        for check_id in failed:
            for dep in review.checks[check_id].get("depends_on", []):
                if dep in phase and phase[dep] > phase[check_id]:
                    phase[dep] = phase[check_id]
                    changed = True
    return phase


def build(review: Review, cost: CostModel) -> list[Finding]:
    results = run_all(review)
    index = best_practice_index(review)
    lever_change = {lever: change for lever, _, change in cost.levers}
    failed = [c for c, result in results.items() if not result.passed]

    def change_of(check_id: str) -> float:
        lever = review.checks[check_id].get("lever")
        return lever_change[lever] if lever else 0.0

    ranked = sorted(
        failed,
        key=lambda c: (
            RISK_ORDER[review.checks[c]["risk"]],
            round(change_of(c), 2),
            EFFORT_ORDER[review.checks[c]["effort"]],
            c,
        ),
    )
    keys = {check_id: f"GA-{rank:02d}" for rank, check_id in enumerate(ranked, start=1)}
    phases = _phases(failed, review)
    findings = []
    for check_id in ranked:
        meta = review.checks[check_id]
        pillar, bp = index[check_id]
        findings.append(
            Finding(
                key=keys[check_id],
                check_id=check_id,
                bp_id=bp["id"],
                bp_title=bp["title"],
                pillar=pillar["name"],
                title=meta["finding"],
                risk=meta["risk"],
                effort=meta["effort"],
                owner=meta["owner"],
                observed=results[check_id].observed,
                evidence=tuple(meta["evidence"]),
                impact=" ".join(meta["impact"].split()),
                recommendation=" ".join(meta["recommendation"].split()),
                fix=tuple(meta.get("fix", [])),
                monthly_change=change_of(check_id),
                depends_on=tuple(keys[d] for d in meta.get("depends_on", []) if d in keys),
                phase=PHASES[phases[check_id]],
            )
        )
    return findings
