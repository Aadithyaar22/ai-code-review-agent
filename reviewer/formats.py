"""Render reports as text, JSON, Markdown or SARIF."""

import json

from reviewer.models import Report

ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}
SARIF_LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}


def _loc(f) -> str:
    return f"{f.line_start}" if f.line_start == f.line_end else f"{f.line_start}-{f.line_end}"


def render_text(reports: list[Report]) -> str:
    out = []
    for r in reports:
        s = r.stats
        extra = f"  [{s.get('seconds', 0)}s{', cached' if s.get('chunks') and s.get('cached_chunks') == s.get('chunks') else ''}]"
        out.append(f"\n━━ {r.target} ━━  ⭐ {r.score}/10  ({r.language}){extra}")
        out.append(r.summary)
        for f in r.findings:
            src = f" ({f.rule})" if f.rule else ""
            out.append(f"\n  {ICON.get(f.severity, '•')} {f.severity.upper()} · {f.category} · line {_loc(f)}{src}")
            out.append(f"     {f.title}")
            if f.description and f.description != f.title:
                out.append(f"     {f.description}")
            if f.fix:
                out.append(f"     fix: {f.fix}")
        for p in r.positives:
            out.append(f"  ✅ {p}")
        dropped = sum(v for k, v in s.items() if k.startswith("dropped_"))
        if dropped:
            out.append(f"  (filtered {dropped} unverifiable/low-confidence model finding(s))")
    total = sum(len(r.findings) for r in reports)
    if len(reports) > 1:
        out.append(f"\nTotal: {len(reports)} files, {total} findings")
    return "\n".join(out)


def render_markdown(reports: list[Report]) -> str:
    out = ["# Code review\n"]
    for r in reports:
        out.append(f"## `{r.target}` — {r.score}/10 ({r.language})\n\n{r.summary}\n")
        for f in r.findings:
            out.append(f"- {ICON.get(f.severity, '•')} **{f.severity}** · {f.category} · line {_loc(f)} — "
                       f"**{f.title}**  \n  {f.description}" + (f"  \n  _Fix:_ `{f.fix}`" if f.fix else ""))
        if not r.findings:
            out.append("_No issues found._")
        out.append("")
    return "\n".join(out)


def render_json(reports: list[Report]) -> str:
    return json.dumps([r.model_dump() for r in reports], indent=2)


def render_sarif(reports: list[Report]) -> str:
    results = []
    for r in reports:
        for f in r.findings:
            results.append({
                "ruleId": f.rule or f.category,
                "level": SARIF_LEVEL.get(f.severity, "note"),
                "message": {"text": f"{f.title}. {f.description}".strip() + (f" Fix: {f.fix}" if f.fix else "")},
                "locations": [{"physicalLocation": {
                    "artifactLocation": {"uri": r.target},
                    "region": {"startLine": f.line_start, "endLine": f.line_end}}}],
            })
    return json.dumps({
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [{"tool": {"driver": {"name": "code-review-agent"}}, "results": results}],
    }, indent=2)


RENDERERS = {"text": render_text, "json": render_json, "markdown": render_markdown, "sarif": render_sarif}
