"""Release gate: fail the pipeline when a route's golden-set pass rate falls under the agreed bar.

Input is the evaluation run's CSV (route, model, category, questions, passed). Exit code 0 passes the release,
1 blocks it. Closes the eval-in-pipeline finding together with fixes/pipeline/evaluate-stage.yaml.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path


def evaluate(rows: list[dict[str, str]], min_overall: float, min_category: float) -> list[str]:
    """Return one failure line per route and model under the bar; an empty list means the release may go."""
    grouped: dict[tuple[str, str], list[tuple[str, int, int]]] = defaultdict(list)
    for row in rows:
        grouped[(row["route"], row["model"])].append((row["category"], int(row["questions"]), int(row["passed"])))
    if not grouped:
        return ["no evaluation results"]
    failures = []
    for (route, model), cats in sorted(grouped.items()):
        overall = sum(p for _, _, p in cats) / sum(q for _, q, _ in cats)
        weakest_name, weakest = min(((name, p / q) for name, q, p in cats), key=lambda item: item[1])
        if overall < min_overall or weakest < min_category:
            failures.append(
                f"{route}/{model}: {overall:.1%} overall (bar {min_overall:.0%}), "
                f"{weakest_name} {weakest:.1%} (bar {min_category:.0%})"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--min-overall", type=float, default=0.90)
    parser.add_argument("--min-category", type=float, default=0.85)
    args = parser.parse_args(argv)
    with args.results.open(encoding="utf-8", newline="") as handle:
        failures = evaluate(list(csv.DictReader(handle)), args.min_overall, args.min_category)
    for line in failures:
        print(f"blocked: {line}", file=sys.stderr)
    if not failures:
        print("eval gate: passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
