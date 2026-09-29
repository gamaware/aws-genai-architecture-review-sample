# Review method

How a GenAI architecture, security and cost review runs, from scoping to the fixes. The Harbor Goods sample follows
these steps; each step names the files it produced.

## 1. Scope

A scoping call agrees the workload, the Generative AI Lens best practices in scope, the people to interview and the
read-only exports. `data/synthetic/workload.yaml` and `data/synthetic/lens.yaml` record the scope. The
review never changes the client's accounts.

## 2. Exports

The client runs read-only commands and sends the output. The review needs:

| Export | Answers |
| --- | --- |
| `terraform show -json` of the stack, or the matching describe calls | Guardrails per route, model IDs, caching, log groups, API throttling |
| IAM role and policies of the functions | Scope of Bedrock access |
| `get-model-invocation-logging-configuration`, `list-inference-profiles`, `list-guardrails` | Audit logging, cost attribution, guardrail versions |
| A sample of application log events | Personal data in logs, prompt injection attempts |
| Pipeline definition | Whether anything measures quality before release |
| Cost and usage report lines for Bedrock and the vector store, three months | Trend, and the figure the cost model must reconcile with |

## 3. Golden set and evaluation

The review and the product team agree a golden set of questions with reference answers, grouped by category, and a
quality bar (here 90% across all questions and 85% in every category). The review runs it against the current model
and cheaper candidates, offline, and records the results (`as-found/eval-results.csv`). The golden set stays with the
client and becomes the release gate.

## 4. Checks

Each best practice that the exports can decide has a check in `scripts/genai_review/checks.py`. Checks are plain
functions over the export files, so they re-run on a fresh export after the fixes. The interview confirms the rest,
and `lens.yaml` records them with their evidence.

## 5. Findings

A failed check becomes a finding with the risk, effort, owner, impact and recommendation in
`data/synthetic/checks.yaml`, and the observed text the check produced. Ranking and phasing follow
[ADR 0002](adr/0002-rank-by-risk-then-saving.md).

| Risk | Meaning |
| --- | --- |
| High | Customer data exposure, uncontrolled access, or unfiltered model output to customers |
| Medium | A gap that costs money or answer quality every day, or leaves an incident without a record |
| Low | A gap that limits visibility or efficiency |

## 6. Cost model

The model prices one month twice from the same traffic, as found and after the fixes, and splits the difference by
lever ([ADR 0003](adr/0003-sequential-levers-reconciled-with-cur.md)). The as-found figure must reconcile with the
bill before any saving goes into the report. The model prices the fixes that add cost (guardrail coverage, invocation
logging) too.

## 7. Fixes

Each finding names the file that closes it. Account-level controls are Terraform in `fixes/terraform/`, tested with a
mocked provider; request-path changes are application code in `fixes/app/`, tested against stubbed Bedrock clients;
the release gate is a pipeline stage plus a small script. The client applies them through its own pipeline, staging
first.

## 8. Report and re-review

`make evidence` writes `evidence/` and the generated blocks of the report; `make pdf` renders the PDF. After the
fixes land, the client sends fresh exports and the checks run again: a closed finding disappears from the report.
