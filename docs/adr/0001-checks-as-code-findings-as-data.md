# 0001. Decide best practices with scripted checks and generate the report from them

## Status

Accepted

## Context

A GenAI review turns exports (Terraform state, IAM policies, account settings, logs, the bill, evaluation results)
into findings. When a reviewer reads the exports by eye and types the report, the same observation gets three
phrasings, a late export leaves stale numbers behind, and nobody can re-run the review after the client fixes something.

## Decision

Each best practice that exports can decide has a check function in `scripts/genai_review/checks.py`. The check reads
only files under `data/synthetic/as-found/` and returns pass or fail with what it observed. The words around a failed
check (finding title, risk, effort, owner, impact, recommendation, fix files) live in `data/synthetic/checks.yaml`;
the Generative AI Lens scope lives in `data/synthetic/lens.yaml`. The same file records best practices without a check
as met, with evidence from the interview. The scripts write every table and finding in `report/REPORT.md` between
`BEGIN GENERATED` and `END GENERATED` markers, plus the files in `evidence/`.

## Consequences

- Re-running the checks on a fresh export after the fixes shows which findings closed.
- The observed text in each finding is what the check saw, not a paraphrase.
- A gap that no export shows cannot be a finding without a check; interview-only gaps need a new check or a new
  export. The sample accepts that: every finding here is reproducible.
- Prose outside the markers stays hand-written and avoids hard-coded numbers.

## Compliance

`make check` fails when a committed output differs from a fresh generation. `tests/test_checks.py` asserts which
checks fail on the as-found data and that each one passes once the test applies its fix to the data. `load()` refuses a
check without metadata, metadata without a check, unknown evidence IDs and fix paths that do not exist.

## Notes

The layout follows the Well-Architected assessment sample in this portfolio, where answers are data and the scripts
generate the report tables.
