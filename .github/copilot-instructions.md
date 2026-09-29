# Copilot code review instructions

This repository is a fictional sample deliverable: a GenAI architecture, security and cost review of the fictional
retailer Harbor Goods' product assistant, mapped to the AWS Well-Architected Generative AI Lens. When reviewing pull
requests:

- Check that best-practice IDs and titles in `data/synthetic/lens.yaml` match the Generative AI Lens exactly.
- Check that any change to `data/` or `scripts/` comes with regenerated `evidence/` and report blocks
  (`make evidence`), and that `make verify` would still pass.
- Terraform in `fixes/terraform/`: no wildcard IAM actions or resources outside the KMS key policy, KMS encryption,
  and a `terraform test` assertion for each control a finding relies on.
- Application fixes in `fixes/app/`: no prompt or answer text in logs, a guardrail on every model call, and the
  Bedrock client injected so tests use a stub.
- Flag any real AWS account ID, ARN, IP address, email address or organization name. The repository allows only AWS
  documentation example IDs and `example.com`.
- Flag suppressed lint rules; fix violations instead of suppressing them.
- Workflows: `permissions: {}` at the top, SHA-pinned actions, no `pull_request_target`, no cloud credentials.
