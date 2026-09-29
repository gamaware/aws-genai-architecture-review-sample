"""Release gate: fail the pipeline unless the golden set ran completely and every route meets the agreed bar.

Inputs are the evaluation run's CSV (route, model, category, questions, passed) and the golden-set expectations
(fixes/pipeline/golden-set.json: the model each route ships with and the question count of each category). Exit code
0 passes the release, 1 blocks it. Closes the eval-in-pipeline finding together with fixes/pipeline/evaluate-stage.yaml.

A partial run never passes: every expected route, its shipping model and every category must be present with at least
the expected number of questions, and rows for other routes, models or categories block the release too.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path


def _parse(rows: list[dict[str, str]]) -> tuple[dict[tuple[str, str, str], tuple[int, int]], list[str]]:
    parsed: dict[tuple[str, str, str], tuple[int, int]] = {}
    problems = []
    for number, row in enumerate(rows, start=2):
        key = (row.get("route", ""), row.get("model", ""), row.get("category", ""))
        try:
            questions, passed = int(row["questions"]), int(row["passed"])
        except (KeyError, TypeError, ValueError):
            problems.append(f"line {number}: questions and passed must be whole numbers")
            continue
        if questions <= 0 or not 0 <= passed <= questions:
            problems.append(f"line {number}: {passed} passed of {questions} questions is not a valid result")
        elif key in parsed:
            problems.append(f"line {number}: {'/'.join(key)} appears twice")
        else:
            parsed[key] = (questions, passed)
    return parsed, problems


def _coverage(results: dict[tuple[str, str, str], tuple[int, int]], expected: dict) -> list[str]:
    problems = []
    for route, model, category in sorted(results):
        spec = expected.get(route)
        if spec is None:
            problems.append(f"{route}: not a route of the golden set")
        elif model != spec["model"]:
            problems.append(f"{route}/{model}: not the model {route} ships with ({spec['model']})")
        elif category not in spec["categories"]:
            problems.append(f"{route}/{model}: category {category} is not in the golden set")
    for route, spec in sorted(expected.items()):
        for category, minimum in sorted(spec["categories"].items()):
            questions = results.get((route, spec["model"], category), (0, 0))[0]
            if questions < minimum:
                problems.append(f"{route}/{spec['model']}: {category} has {questions} of {minimum} expected questions")
    return problems


def evaluate(
    rows: list[dict[str, str]], expected: dict[str, dict], min_overall: float, min_category: float
) -> list[str]:
    """Return one line per problem; an empty list means the release may go."""
    if not expected:
        return ["no golden-set expectations"]
    if not rows:
        return ["no evaluation results"]
    results, failures = _parse(rows)
    failures += _coverage(results, expected)
    if failures:
        return failures
    grouped: dict[tuple[str, str], list[tuple[str, int, int]]] = defaultdict(list)
    for (route, model, category), (questions, passed) in results.items():
        grouped[(route, model)].append((category, questions, passed))
    for (route, model), cats in sorted(grouped.items()):
        overall = sum(p for _, _, p in cats) / sum(q for _, q, _ in cats)
        weakest_name, weakest = min(((name, p / q) for name, q, p in sorted(cats)), key=lambda item: item[1])
        if overall < min_overall or weakest < min_category:
            failures.append(
                f"{route}/{model}: {overall:.1%} overall (bar {min_overall:.0%}), "
                f"{weakest_name} {weakest:.1%} (bar {min_category:.0%})"
            )
    return failures


def load_expected(path: Path) -> dict[str, dict]:
    """Route -> {"model": ..., "categories": {category: minimum questions}}."""
    routes = json.loads(path.read_text(encoding="utf-8"))["routes"]
    for route, spec in routes.items():
        if not spec.get("model") or not spec.get("categories"):
            raise ValueError(f"{path}: route {route} needs a model and at least one category")
        if any(not isinstance(n, int) or n <= 0 for n in spec["categories"].values()):
            raise ValueError(f"{path}: route {route} needs a positive question count per category")
    return routes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--expected", type=Path, required=True, help="golden-set expectations (JSON)")
    parser.add_argument("--min-overall", type=float, default=0.90)
    parser.add_argument("--min-category", type=float, default=0.85)
    args = parser.parse_args(argv)
    expected = load_expected(args.expected)
    with args.results.open(encoding="utf-8", newline="") as handle:
        failures = evaluate(list(csv.DictReader(handle)), expected, args.min_overall, args.min_category)
    for line in failures:
        print(f"blocked: {line}", file=sys.stderr)
    if not failures:
        print("eval gate: passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
