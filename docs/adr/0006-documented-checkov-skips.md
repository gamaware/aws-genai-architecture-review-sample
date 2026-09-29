# 0006. Skip two Checkov rule groups inline, with the reason next to the resource

## Status

Accepted

## Context

Checkov runs on the Terraform fixes in `make verify`. Two results are false for this change. The KMS key policy uses
`"*"` as its resource, which in a key policy means the key itself (CKV_AWS_109, CKV_AWS_111, CKV_AWS_356). The API
method settings have no response cache (CKV_AWS_225); answers are per shopper and per conversation, so a cache would
serve one shopper's answer to another.

## Decision

Skip those checks inline on the two resources with a `checkov:skip` comment that states the reason. No skip lives in
`.checkov.yaml`, and no other check has a skip.

## Consequences

- The reason sits next to the code a reviewer reads.
- A new key policy or method-settings resource elsewhere is still checked.

## Compliance

`make checkov` reports the skips with their reasons; a reviewer rejects any skip without one.

## Notes

The KMS skip matches the one used for key policies in the Terraform rescue sample of this portfolio.
