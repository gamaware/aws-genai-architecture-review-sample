# 0004. Verify offline, with no live test target

## Status

Accepted

## Context

The review's inputs are exports, and the client applies the fixes through its own pipeline. Other samples in
this portfolio have a manual live test; here, a live run would have to create a fictional GenAI stack only to export
it again, and would not prove more than the fixtures do.

## Decision

`make verify` runs offline and needs no AWS account: ruff, pytest (checks, cost model, report, application fixes
against stubbed Bedrock clients), `make check`, Terraform fmt and validation, tflint and `terraform test` with a mocked
provider, Checkov, Trivy and Semgrep. The repository has no `make test-live`.

## Consequences

- CI and a contributor run the same command, with no credentials in either.
- `terraform test` proves the fixes carry the controls each finding needs, not that the apply succeeds in a real
  account. A client applies the change in staging first.
- The first run downloads packages, the provider, rule sets and the Trivy checks bundle.

## Compliance

The `verify` job in `.github/workflows/ci.yml` runs `make verify` and receives no cloud credentials or id-token.

## Notes

A live run of the Terraform would need an existing REST API, roles and a knowledge base role; the variables default
to the fictional client's names for that reason.
