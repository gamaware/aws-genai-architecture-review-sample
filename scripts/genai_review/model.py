"""Load and validate the review inputs: workload, pricing, lens scope, checks, evidence and the as-found files."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from genai_review.checks import REGISTRY

BP_ID = re.compile(r"^GEN(OPS|SEC|REL|PERF|COST|SUS)\d{2}-BP\d{2}$")
RISKS = ("high", "medium", "low")
EFFORTS = ("S", "M", "L")


class ReviewError(ValueError):
    """The review data breaks a rule the report depends on."""


@dataclass(frozen=True)
class Snapshot:
    """The as-found evidence, parsed once."""

    resources: dict[str, dict]
    iam_role: dict
    bedrock_settings: dict
    log_events: list[dict]
    eval_rows: list[dict]
    cur_rows: list[dict]
    pipeline: dict

    def resources_of(self, resource_type: str) -> dict[str, dict]:
        return {name: res for name, res in self.resources.items() if res["type"] == resource_type}

    def lambda_env(self, route: str) -> dict[str, str]:
        values = self.resources[f"aws_lambda_function.{route}"]["values"]
        return values["environment"][0]["variables"]


@dataclass(frozen=True)
class Review:
    workload: dict
    pricing: dict
    pillars: list[dict]
    checks: dict[str, dict]
    evidence: dict[str, dict]
    snapshot: Snapshot
    root: Path = field(repr=False)

    @property
    def routes(self) -> dict[str, dict]:
        return self.workload["routes"]


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_snapshot(found: Path) -> Snapshot:
    plan = json.loads((found / "terraform-plan.json").read_text(encoding="utf-8"))
    resources = {res["address"]: res for res in plan["planned_values"]["root_module"]["resources"]}
    events = [
        json.loads(line)
        for line in (found / "app-log-sample.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return Snapshot(
        resources=resources,
        iam_role=json.loads((found / "iam-lambda-role.json").read_text(encoding="utf-8")),
        bedrock_settings=json.loads((found / "bedrock-settings.json").read_text(encoding="utf-8")),
        log_events=events,
        eval_rows=_csv(found / "eval-results.csv"),
        cur_rows=_csv(found / "cur-genai.csv"),
        pipeline=_yaml(found / "ci-pipeline.yaml"),
    )


def load(data_root: Path) -> Review:
    """Load everything under data/ (the directory that holds pricing.yaml and synthetic/)."""
    synthetic = data_root / "synthetic"
    review = Review(
        workload=_yaml(synthetic / "workload.yaml"),
        pricing=_yaml(data_root / "pricing.yaml"),
        pillars=_yaml(synthetic / "lens.yaml")["pillars"],
        checks={entry["id"]: entry for entry in _yaml(synthetic / "checks.yaml")["checks"]},
        evidence={entry["id"]: entry for entry in _yaml(synthetic / "evidence.yaml")["evidence"]},
        snapshot=load_snapshot(synthetic / "as-found"),
        root=data_root,
    )
    validate(review)
    return review


def _validate_lens(review: Review) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    seen_bp: set[str] = set()
    referenced_checks: set[str] = set()
    for pillar in review.pillars:
        for bp in pillar["best_practices"]:
            bp_id = bp["id"]
            if not BP_ID.match(bp_id):
                errors.append(f"{bp_id}: not a Generative AI Lens best-practice ID")
            if bp_id in seen_bp:
                errors.append(f"{bp_id}: listed twice")
            seen_bp.add(bp_id)
            prefix = bp_id.split("-")[0]
            if not bp["question"].startswith(prefix + ":"):
                errors.append(f"{bp_id}: question does not start with {prefix}")
            if "checks" in bp:
                referenced_checks.update(bp["checks"])
                errors += [f"{bp_id}: unknown check {c}" for c in bp["checks"] if c not in review.checks]
            elif bp.get("status") != "met" or not bp.get("evidence"):
                errors.append(f"{bp_id}: without checks it needs status met and evidence")
            errors += [f"{bp_id}: unknown evidence {e}" for e in bp.get("evidence", []) if e not in review.evidence]
    return errors, referenced_checks


def _validate_check(review: Review, check_id: str, meta: dict, referenced: set[str]) -> list[str]:
    errors = []
    if check_id not in REGISTRY:
        errors.append(f"{check_id}: no check function in checks.py")
    if check_id not in referenced:
        errors.append(f"{check_id}: not mapped to a best practice in lens.yaml")
    if meta["risk"] not in RISKS:
        errors.append(f"{check_id}: risk {meta['risk']!r} not in {RISKS}")
    if meta["effort"] not in EFFORTS:
        errors.append(f"{check_id}: effort {meta['effort']!r} not in {EFFORTS}")
    errors += [f"{check_id}: unknown evidence {e}" for e in meta["evidence"] if e not in review.evidence]
    errors += [f"{check_id}: unknown dependency {d}" for d in meta.get("depends_on", []) if d not in review.checks]
    errors += [
        f"{check_id}: fix path {p} does not exist" for p in meta.get("fix", []) if not (review.root.parent / p).exists()
    ]
    return errors


def validate(review: Review) -> None:
    errors, referenced = _validate_lens(review)
    for check_id, meta in review.checks.items():
        errors += _validate_check(review, check_id, meta, referenced)
    errors += [f"{c}: check function has no metadata" for c in REGISTRY if c not in review.checks]
    errors += [
        f"{ev_id}: {ev['path']} does not exist"
        for ev_id, ev in review.evidence.items()
        if not (review.root / "synthetic" / ev["path"]).is_file()
    ]
    if errors:
        raise ReviewError("; ".join(errors))
