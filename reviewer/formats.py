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
            if f.trigger:
                out.append(f"     fails when: {f.trigger}")
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
                       f"**{f.title}**  \n  {f.description}" + (f"  \n  _Fails when:_ {f.trigger}" if f.trigger else "") + (f"  \n  _Fix:_ `{f.fix}`" if f.fix else ""))
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


# ── repository reports ───────────────────────────────────────────────────────
BD_LABEL = {"code_quality": "Code quality", "security": "Security", "reliability": "Reliability",
            "project_hygiene": "Project hygiene"}
PRI_LABEL = {"P0": "P0 — fix now", "P1": "P1 — fix soon", "P2": "P2 — should fix", "P3": "P3 — nice to have"}


def _bar(v: float, width: int = 10) -> str:
    n = round(v / 10 * width)
    return "█" * n + "░" * (width - n)


def _coverage_line(st: dict) -> str:
    return (f"Reviewed {st['files_reviewed']} of {st['files_total']} source files "
            f"({round(st['coverage'] * 100)}% of the code) — confidence: {st['confidence']}")


def render_repo_text(r, max_actions: int = 25) -> str:
    st = r.stats
    out = [f"\n━━ REPOSITORY RATING ━━  {r.root}",
           f"\n   {r.score}/10   Grade {r.grade}", f"   {_coverage_line(st)}\n"]
    for k, label in BD_LABEL.items():
        out.append(f"   {label:<16} {r.breakdown[k]:>4}  {_bar(r.breakdown[k])}")
    if st["confidence"] == "low":
        out.append("\n   ⚠ Low coverage: raise --max-files for a more reliable rating.")
    out.append("\n━━ CHANGES REQUIRED ━━")
    if not r.actions:
        out.append("  Nothing to fix. 🎉")
    last = None
    for i, a in enumerate(r.actions[:max_actions], 1):
        if a.priority != last:
            out.append(f"\n  {PRI_LABEL[a.priority]}")
            last = a.priority
        out.append(f"   {i:>2}. {a.title}" + (f"  [{a.location}]" if a.location else ""))
        if a.detail:
            out.append("       " + a.detail.replace("\n", "\n       "))
        if a.fix:
            out.append("       fix: " + a.fix.replace("\n", "\n            "))
    if len(r.actions) > max_actions:
        out.append(f"\n  … and {len(r.actions) - max_actions} more (use --format markdown/json for the full list)")
    if r.themes:
        out.append("\n━━ PATTERNS ━━")
        out += [f"  • {t}" for t in r.themes]
    out.append("\n━━ PROJECT CHECKLIST ━━")
    out += [f"  {'✓' if c.ok else '✗'} {c.message}" for c in r.hygiene]
    out.append("\n━━ FILES (worst first) ━━")
    for f in r.files:
        sev = ", ".join(f"{f.count(s)} {s}" for s in ("critical", "high", "medium", "low") if f.count(s))
        out.append(f"  {f.score:>2}/10  {f.target}" + (f"   ({sev})" if sev else ""))
    if st["files_skipped"]:
        out.append(f"\n  Not reviewed ({len(st['files_skipped'])}): " + ", ".join(st["files_skipped"][:8])
                   + (" …" if len(st["files_skipped"]) > 8 else ""))
    if st["errors"]:
        out.append(f"\n  {len(st['errors'])} file(s) failed to review: " + "; ".join(st["errors"][:3]))
    out.append(f"\n  [{st['seconds']}s · model {st['model']}]")
    out.append("  Score = 35% code quality + 25% security + 20% reliability + 20% project hygiene; "
               "any critical issue caps it at 7.")
    return "\n".join(out)


def render_repo_markdown(r) -> str:
    st = r.stats
    out = [f"# Repository review — {r.score}/10 (Grade {r.grade})\n", f"`{r.root}`  \n_{_coverage_line(st)}_\n",
           "| Area | Score |\n|---|---|"]
    out += [f"| {label} | {r.breakdown[k]} {_bar(r.breakdown[k])} |" for k, label in BD_LABEL.items()]
    out.append("\n## Changes required\n")
    last = None
    for a in r.actions:
        if a.priority != last:
            out.append(f"\n### {PRI_LABEL[a.priority]}\n")
            last = a.priority
        out.append(f"- **{a.title}**" + (f" — `{a.location}`" if a.location else "")
                   + (f"  \n  {a.detail}" if a.detail else "") + (f"  \n  _Fix:_ {a.fix}" if a.fix else ""))
    if not r.actions:
        out.append("_Nothing to fix._")
    if r.themes:
        out += ["\n## Patterns\n"] + [f"- {t}" for t in r.themes]
    out += ["\n## Project checklist\n"] + [f"- [{'x' if c.ok else ' '}] {c.message}" for c in r.hygiene]
    out += ["\n## Files (worst first)\n", "| Score | File | Findings |", "|---|---|---|"]
    out += [f"| {f.score}/10 | `{f.target}` | {len(f.findings)} |" for f in r.files]
    return "\n".join(out)


def render_repo_json(r) -> str:
    return r.model_dump_json(indent=2)


def render_repo_sarif(r) -> str:
    from reviewer.models import Report
    reports = list(r.files)
    if r.secrets:
        by_file: dict[str, list] = {}
        for f in r.secrets:
            by_file.setdefault(f.file, []).append(f)
        reports += [Report(target=p, findings=fs) for p, fs in by_file.items()]
    return render_sarif(reports)


REPO_RENDERERS = {"text": render_repo_text, "markdown": render_repo_markdown,
                  "json": render_repo_json, "sarif": render_repo_sarif}
