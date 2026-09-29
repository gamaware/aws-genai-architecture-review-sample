# 0002. Rank findings by risk, then saving, then effort, and phase them by risk

## Status

Accepted

## Context

A GenAI review mixes security gaps that cost nothing to fix with cost gaps worth thousands a month. Ranking by money
alone would push the guardrail and IAM fixes down the list; ranking by risk alone would hide which medium findings pay
for the work.

## Decision

Findings sort by risk (high, medium, low), then by monthly cost change (largest saving first; fixes that add cost
after those with no cost effect), then by effort (S, M, L), then by check ID. Keys `GA-nn` follow that order. Each
finding starts in the phase of its risk (weeks 1-2, 3-6, 7-10). A finding that another finding depends on moves up to
the earlier phase, so the model switch never lands before the evaluation stage and inference profiles it needs.

## Consequences

- The top three recommendations are always the highest risks, and savings order the medium findings.
- Dependencies are explicit in `checks.yaml` and visible in the report.
- Two findings with the same risk, saving and effort sort by check ID, which is stable but arbitrary.

## Compliance

`tests/test_report.py` checks that the findings table is in risk order and matches `evidence/findings.csv`, and that
the roadmap never schedules a dependency after the finding that needs it.

## Notes

Risk ratings are the reviewer's judgment, recorded per check in `checks.yaml` with the impact that justifies them.
