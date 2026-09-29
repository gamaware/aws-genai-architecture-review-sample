# 0003. Price levers in a fixed order and reconcile the model with the bill first

## Status

Accepted

## Context

Savings levers interact: prompt caching saves less once a route moves to a cheaper model, and a guardrail fix adds
cost. Pricing each lever against the as-found state would double-count, and the lever figures would not add up to
the total. A model built from traffic figures is also only as good as those figures.

## Decision

`scripts/genai_review/costmodel.py` prices one month from the traffic in `workload.yaml` and the unit prices in
`pricing.yaml`. Levers apply in a fixed order (model right-size, prompt caching, batch inference, vector store,
guardrail coverage, invocation logging); each lever's figure is the change in the total when the model applies it on top
of the ones before it. The as-found total must reconcile with the latest month of the cost and usage export before
the report states any saving.

## Consequences

- Lever figures add up exactly to the net change, and fixes that add cost show as positive lines.
- A different order gives a different split with the same total; the report says so.
- Unit prices are list prices and need re-checking whenever the report is re-issued.

## Compliance

`tests/test_costmodel.py` requires the lever sum to equal the net change, the reconciliation gap to stay under 1%,
and both totals to match `tests/reference.py`, an independent recomputation from the raw files.

## Notes

The model switch uses the cheapest model that meets the quality bar on the golden set (90% across all questions, 85%
in every category), so a worse evaluation result automatically keeps the larger model.
