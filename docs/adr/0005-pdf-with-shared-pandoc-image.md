# 0005. Render the PDF with the shared pandoc LaTeX image

## Status

Accepted

## Context

Clients expect a PDF; reviewers want a diff-able source. Keeping two documents in step by hand fails quickly. The
shared `report` workflow in `gamaware/.github` already renders every sample report in CI with a pinned `pandoc/latex`
container. A second, local-only PDF engine would make the committed PDF differ from the one CI proves.

## Decision

`report/REPORT.md` is the canonical report. `make pdf` renders `report/REPORT.pdf` by running the same pinned
`pandoc/latex` image, with the same arguments (xelatex, 2.2 cm margins, table of contents), that the shared `report`
workflow uses. The committed PDF is the only PDF this repository publishes.

## Consequences

- One source for both formats and one PDF engine, locally and in CI.
- `make pdf` needs Docker on the maintainer machine; it downloads no Python packages.
- The `Makefile` repeats the image and its arguments. When the shared workflow changes its pin or
  defaults, the `Makefile` changes with it.
- PDF bytes are not reproducible across runs (timestamps), so no job compares PDFs byte for byte. The maintainer
  regenerates the committed PDF with `make pdf` whenever the report changes.

## Compliance

The `report / pdf` check in `.github/workflows/ci.yml` fails if the report does not render or the PDF is empty. The
`report / evidence` check reruns `make evidence` and fails if `evidence/` differs from the commit.

## Notes

The same decision holds in the other report samples of this portfolio, so every client PDF comes from one engine.
