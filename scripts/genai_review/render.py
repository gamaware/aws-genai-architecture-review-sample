"""Render evidence/ and the generated blocks of report/REPORT.md and README.md.

Output is deterministic: the same data gives byte-identical files, which is what `make check` compares.
"""

from __future__ import annotations

import csv
import io
import json
import re
import textwrap
from typing import TYPE_CHECKING

from genai_review import costmodel
from genai_review import findings as findings_mod
from genai_review.checks import run_all

if TYPE_CHECKING:
    from genai_review.model import Review

BLOCK = re.compile(
    r"(<!-- BEGIN GENERATED: (?P<name>[a-z0-9:-]+) -->\n)(?P<body>.*?)(<!-- END GENERATED: (?P=name) -->)",
    re.DOTALL,
)
ANY_MARKER = re.compile(r"<!-- (BEGIN|END) GENERATED")
RISK_LABEL = {"high": "High", "medium": "Medium", "low": "Low"}
STATUS_LABEL = {"met": "Met", "not_met": "Not met"}
FINDING_COLUMNS = (
    "key",
    "risk",
    "best_practice",
    "pillar",
    "title",
    "effort",
    "owner",
    "phase",
    "monthly_change_usd",
    "depends_on",
    "evidence",
    "observed",
    "recommendation",
    "fix",
)


def _wrap(text: str, indent: str = "") -> str:
    """Wrap prose at 120 characters so generated Markdown passes the same line-length rule as hand-written text."""
    return textwrap.fill(text, width=120, subsequent_indent=indent, break_long_words=False, break_on_hyphens=False)


def _table(header: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(str(v).replace("|", "\\|") for v in row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def usd(value: float) -> str:
    sign = "-" if round(value, 2) < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def signed_usd(value: float) -> str:
    return ("+" if round(value, 2) > 0 else "") + usd(value)


def _json(data: object) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _csv_safe(value: object) -> object:
    """Stop spreadsheet apps from running a cell as a formula when the findings are imported."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


class Renderer:
    def __init__(self, review: Review) -> None:
        self.review = review
        self.results = run_all(review)
        self.cost = costmodel.build(review)
        self.findings = findings_mod.build(review, self.cost)
        self.lens = findings_mod.lens_status(review, self.results)

    # Figures used in several places ---------------------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        return {risk: sum(f.risk == risk for f in self.findings) for risk in ("high", "medium", "low")}

    def savings(self) -> float:
        return self.cost.before_total - self.cost.after_total

    def growth(self) -> float:
        periods = list(self.cost.cur_by_period.values())
        return periods[-1] / periods[0] - 1

    # Evidence files -------------------------------------------------------------------------------------------

    def files(self) -> dict[str, str]:
        return {
            "evidence/findings.csv": self.findings_csv(),
            "evidence/findings.json": _json([self._finding_dict(f) for f in self.findings]),
            "evidence/check-results.json": _json(
                {c: {"passed": r.passed, "observed": r.observed} for c, r in self.results.items()}
            ),
            "evidence/lens-status.json": _json(self.lens),
            "evidence/cost-model.json": _json(self._cost_dict()),
        }

    def _finding_dict(self, f: findings_mod.Finding) -> dict:
        return {
            "key": f.key,
            "check": f.check_id,
            "risk": f.risk,
            "best_practice": f.bp_id,
            "pillar": f.pillar,
            "title": f.title,
            "effort": f.effort,
            "owner": f.owner,
            "phase": f.phase,
            "monthly_change_usd": round(f.monthly_change, 2),
            "depends_on": list(f.depends_on),
            "evidence": list(f.evidence),
            "observed": f.observed,
            "recommendation": f.recommendation,
            "fix": list(f.fix),
        }

    def _cost_dict(self) -> dict:
        return {
            "before": {k: round(v, 2) for k, v in self.cost.before.items()},
            "after": {k: round(v, 2) for k, v in self.cost.after.items()},
            "before_total": round(self.cost.before_total, 2),
            "after_total": round(self.cost.after_total, 2),
            "levers": [{"lever": lever, "label": label, "change": round(c, 2)} for lever, label, c in self.cost.levers],
            "cur_by_period": {k: round(v, 2) for k, v in self.cost.cur_by_period.items()},
            "reconciliation_gap": round(self.cost.reconciliation_gap, 4),
        }

    def findings_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(FINDING_COLUMNS)
        for f in self.findings:
            row = self._finding_dict(f)
            writer.writerow(
                _csv_safe(";".join(v) if isinstance(v, list) else v) for v in (row[c] for c in FINDING_COLUMNS)
            )
        return buffer.getvalue()

    # Report blocks --------------------------------------------------------------------------------------------

    def block(self, name: str) -> str:
        if name.startswith("findings:"):
            return self._findings_detail(name.split(":", 1)[1])
        renderers = {
            "headline": self._headline,
            "summary": self._summary,
            "top-recommendations": self._top,
            "findings-table": self._findings_table,
            "lens-coverage": self._lens_coverage,
            "cost-components": self._cost_components,
            "cost-levers": self._cost_levers,
            "cur-trend": self._cur_trend,
            "roadmap": self._roadmap,
            "evidence-register": self._evidence_register,
            "fix-map": self._fix_map,
        }
        if name not in renderers:
            raise ValueError(f"unknown generated block {name}")
        return renderers[name]()

    def _headline(self) -> str:
        counts = self.counts()
        met = sum(row["status"] == "met" for row in self.lens)
        text = (
            f"{len(self.lens)} Generative AI Lens best practices reviewed, {met} met. {len(self.findings)} findings: "
            f"{counts['high']} high, {counts['medium']} medium and {counts['low']} low risk. The recommended changes "
            f"take the modeled monthly bill from {usd(self.cost.before_total)} to {usd(self.cost.after_total)} "
            f"({usd(self.savings())} less, {self.savings() / self.cost.before_total:.0%}), after paying for the added "
            "guardrail coverage and invocation logging."
        )
        return "\n" + _wrap(text) + "\n\n"

    def _summary(self) -> str:
        counts = self.counts()
        periods = list(self.cost.cur_by_period)
        rows = [
            ["Best practices reviewed (met)", f"{len(self.lens)} ({sum(r['status'] == 'met' for r in self.lens)})"],
            [
                "Findings (high, medium, low)",
                f"{len(self.findings)} ({counts['high']}, {counts['medium']}, {counts['low']})",
            ],
            ["Scripted checks (passed)", f"{len(self.results)} ({sum(r.passed for r in self.results.values())})"],
            [
                f"GenAI spend, {periods[0]} to {periods[-1]} (CUR)",
                f"{usd(self.cost.cur_by_period[periods[0]])} to {usd(self.cost.cur_by_period[periods[-1]])} "
                f"(+{self.growth():.0%})",
            ],
            ["Modeled monthly cost as found", usd(self.cost.before_total)],
            ["Modeled monthly cost after the fixes", usd(self.cost.after_total)],
            ["Monthly difference", f"{usd(-self.savings())} ({-self.savings() / self.cost.before_total:.0%})"],
            ["Model reconciliation with the latest CUR month", f"within {self.cost.reconciliation_gap:.1%}"],
        ]
        return "\n" + _table(["Measure", "Value"], rows) + "\n"

    def _top(self) -> str:
        lines = []
        for i, f in enumerate(self.findings[:3], start=1):
            text = f"{i}. **{f.title}** ({f.bp_id}, {RISK_LABEL[f.risk]} risk, effort {f.effort}). {f.recommendation}"
            lines.append(_wrap(text, indent="   "))
        return "\n" + "\n".join(lines) + "\n\n"

    def _findings_table(self) -> str:
        rows = [
            [
                f.key,
                RISK_LABEL[f.risk],
                f.bp_id,
                f.title,
                f.effort,
                signed_usd(f.monthly_change) if f.monthly_change else "-",
            ]
            for f in self.findings
        ]
        header = ["Key", "Risk", "Best practice", "Finding", "Effort", "Monthly cost change"]
        return "\n" + _table(header, rows) + "\n"

    def _findings_detail(self, pillar_key: str) -> str:
        names = {p["key"]: p["name"] for p in self.review.pillars}
        if pillar_key not in names:
            raise ValueError(f"unknown pillar {pillar_key}")
        chunks = []
        for f in (f for f in self.findings if f.pillar == names[pillar_key]):
            fixes = ", ".join(f"[`{p}`](../{p})" for p in f.fix) or "None"
            chunk = [
                f"#### {f.key}. {f.title}",
                "",
                _wrap(
                    f"*{f.bp_id} {f.bp_title}.* {RISK_LABEL[f.risk]} risk, effort {f.effort}, owner: {f.owner}, "
                    f"{f.phase}."
                ),
                "",
                _wrap(f"- **Observed:** {f.observed} ({', '.join(f.evidence)}).", indent="  "),
                _wrap(f"- **Risk if left open:** {f.impact}", indent="  "),
                _wrap(f"- **Recommendation:** {f.recommendation}", indent="  "),
                _wrap(f"- **Fix delivered:** {fixes}.", indent="  "),
            ]
            if f.monthly_change:
                chunk.append(f"- **Monthly cost change:** {signed_usd(f.monthly_change)}.")
            if f.depends_on:
                chunk.append(f"- **Depends on:** {', '.join(f.depends_on)}.")
            chunks.append("\n".join(chunk))
        if not chunks:
            raise ValueError(f"pillar {pillar_key} has no findings; remove its block from the report")
        return "\n" + "\n\n".join(chunks) + "\n\n"

    def _lens_coverage(self) -> str:
        rows = [
            [r["id"], r["title"], STATUS_LABEL[r["status"]], r["basis"], ", ".join(r["evidence"])] for r in self.lens
        ]
        return "\n" + _table(["Best practice", "Title", "Status", "Basis", "Evidence"], rows) + "\n"

    def _cost_components(self) -> str:
        rows = [
            [
                name,
                usd(self.cost.before[name]),
                usd(self.cost.after[name]),
                signed_usd(self.cost.after[name] - self.cost.before[name]),
            ]
            for name in costmodel.COMPONENTS
        ]
        rows.append(
            [
                "**Total**",
                f"**{usd(self.cost.before_total)}**",
                f"**{usd(self.cost.after_total)}**",
                f"**{signed_usd(-self.savings())}**",
            ]
        )
        return "\n" + _table(["Component", "As found", "After fixes", "Change"], rows) + "\n"

    def _cost_levers(self) -> str:
        keys = {self.review.checks[f.check_id].get("lever"): f.key for f in self.findings}
        rows = [[label, keys.get(lever, "-"), signed_usd(change)] for lever, label, change in self.cost.levers]
        rows.append(["**Net change**", "-", f"**{signed_usd(-self.savings())}**"])
        return "\n" + _table(["Lever (applied in this order)", "Finding", "Monthly change"], rows) + "\n"

    def _cur_trend(self) -> str:
        rows = [[period, usd(amount)] for period, amount in self.cost.cur_by_period.items()]
        return "\n" + _table(["Billing period", "Bedrock and OpenSearch Serverless (CUR)"], rows) + "\n"

    def _roadmap(self) -> str:
        rows = []
        for phase in findings_mod.PHASES:
            items = [f for f in self.findings if f.phase == phase]
            rows.append([phase, ", ".join(f"{f.key} ({f.effort})" for f in items) or "-"])
        return "\n" + _table(["Phase", "Findings (effort)"], rows) + "\n"

    def _evidence_register(self) -> str:
        rows = [
            [ev_id, ev["title"], ev["kind"], f"`data/synthetic/{ev['path']}`"]
            for ev_id, ev in sorted(self.review.evidence.items())
        ]
        return "\n" + _table(["ID", "Evidence", "Kind", "File"], rows) + "\n"

    def _fix_map(self) -> str:
        paths: dict[str, list[str]] = {}
        for f in self.findings:
            for path in f.fix:
                paths.setdefault(path, []).append(f.key)
        rows = [[f"`{p}`", ", ".join(keys)] for p, keys in sorted(paths.items())]
        return "\n" + _table(["File", "Closes"], rows) + "\n"

    # Whole documents ------------------------------------------------------------------------------------------

    def document(self, text: str) -> str:
        """Replace the body of every generated block; refuse text with a marker that does not pair up."""
        paired = len(BLOCK.findall(text)) * 2
        if paired != len(ANY_MARKER.findall(text)):
            raise ValueError("a BEGIN/END GENERATED marker is malformed or unpaired")
        return BLOCK.sub(lambda m: m.group(1) + self.block(m.group("name")) + m.group(4), text)
