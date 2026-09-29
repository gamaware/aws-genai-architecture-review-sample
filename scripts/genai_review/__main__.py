"""Command line: `python -m genai_review generate` writes the outputs; `check` fails if an output is stale."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from genai_review.model import ReviewError, load
from genai_review.render import Renderer

# Markdown files whose BEGIN/END GENERATED blocks are rendered from the data. The README is optional so the tests
# can work on a copy of data/ and report/ alone.
REPORT = "report/REPORT.md"
README = "README.md"


def outputs(repo_root: Path) -> dict[str, str]:
    renderer = Renderer(load(repo_root / "data"))
    files = renderer.files()
    files[REPORT] = renderer.document((repo_root / REPORT).read_text(encoding="utf-8"))
    if (repo_root / README).is_file():
        files[README] = renderer.document((repo_root / README).read_text(encoding="utf-8"))
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="genai_review", description=__doc__)
    parser.add_argument("command", choices=("generate", "check"))
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root (default: current directory)")
    args = parser.parse_args(argv)

    try:
        files = outputs(args.root)
    except (ReviewError, KeyError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    stale = []
    for relative, content in files.items():
        path = args.root / relative
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == content:
            continue
        if args.command == "check":
            stale.append(relative)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            print(f"wrote {relative}")

    if stale:
        print("stale outputs (run `make evidence` and commit):", *stale, sep="\n  ", file=sys.stderr)
        return 1
    if args.command == "check":
        print(f"ok: {len(files)} outputs match data/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
