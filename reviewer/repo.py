"""Whole-repository review.

1. pick the riskiest files (the local model is slow, so coverage is budgeted),
2. review them with the normal engine, 3. scan *every* file for leaked secrets,
4. check project hygiene (tests, CI, lockfiles ...), 5. turn it all into a rating
and a prioritized "changes required" list. Everything except the per-file LLM
review is deterministic.
"""

import asyncio
import fnmatch
import os
import re
import shutil
import tempfile
import time
from contextlib import nullcontext
from pathlib import Path, PurePath
from typing import Callable

from pydantic import BaseModel, Field

from reviewer import gitutil
from reviewer.config import Config
from reviewer.engine import is_reviewable, review_source
from reviewer.llm import DEFAULT_MODEL, LLMError
from reviewer.models import Finding, Report
from reviewer.static import run_static

MAX_FILE_BYTES = 200_000
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".tox",
             "target", "vendor", ".next", ".idea", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
GITHUB_RE = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+?(\.git)?/?$")


class Check(BaseModel):
    id: str
    ok: bool
    weight: float
    message: str
    fix: str = ""


class Action(BaseModel):
    priority: str  # P0 (fix now) .. P3 (nice to have)
    title: str
    location: str = ""
    detail: str = ""
    fix: str = ""
    kind: str = "finding"  # finding | secret | hygiene


class RepoReport(BaseModel):
    root: str
    score: float
    grade: str
    breakdown: dict[str, float]
    files: list[Report] = Field(default_factory=list)
    secrets: list[Finding] = Field(default_factory=list)
    hygiene: list[Check] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    themes: list[str] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)

    def all_findings(self) -> list[Finding]:
        return [f for r in self.files for f in r.findings] + self.secrets


# ── file discovery ────────────────────────────────────────────────────────────
def _ignored(path: str, patterns: list[str]) -> bool:
    parts = PurePath(path).parts
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return True
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(parts[-1], p) for p in patterns)


def list_files(root: str, patterns: list[str]) -> list[str]:
    try:
        files = gitutil.tracked_files_in(root)
    except gitutil.GitError:
        files = []
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in SKIP_DIRS]
            files += [os.path.relpath(os.path.join(dp, f), root) for f in fn]
    return sorted(f for f in files if not _ignored(f, patterns))


TEST_RE = re.compile(r"(^|/)(tests?|__tests__|specs?)/|(^|/)test_[^/]*$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$")
GENERATED_RE = re.compile(r"(^|/)(migrations?|generated|__generated__|fixtures?)/|\.generated\.|_pb2(_grpc)?\.py$|\.min\.")
KEYWORDS = {"auth", "login", "password", "passwd", "secret", "token", "crypto", "session", "sql", "query", "db",
            "database", "api", "route", "routes", "views", "view", "server", "handler", "payment", "billing",
            "upload", "admin", "exec", "shell", "config", "main", "app", "cli", "middleware", "permission", "user"}


def priority(path: str, lines: int, static: list[Finding]) -> float:
    """Higher = review sooner. Size + risky names + what ruff already found."""
    score = min(lines, 600) / 100
    serious = sum(1 for f in static if f.severity in ("critical", "high"))
    score += 4 if serious else 1.5 * min(len(static), 3)
    tokens = set(re.split(r"[^a-z0-9]+", PurePath(path).stem.lower())) | \
        {t for part in PurePath(path).parts[:-1] for t in re.split(r"[^a-z0-9]+", part.lower())}
    if tokens & KEYWORDS:
        score += 3
    if TEST_RE.search(path):
        score -= 5
    if GENERATED_RE.search(path):
        score -= 4
    return score


# ── secret scan (all text files, deterministic) ──────────────────────────────
SECRET_PATTERNS = [
    ("AWS access key", "critical", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Private key", "critical", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GitHub token", "critical", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", "critical", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", "critical", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Secret API key", "critical", re.compile(r"\b(?:[sr]k_live_[0-9A-Za-z]{10,}|sk-[A-Za-z0-9_-]{20,})\b")),
    ("Hardcoded credential", "high",
     re.compile(r"""(?i)\b(?:password|passwd|secret|api_?key|access_?token|auth_?token)\b["']?\s*[:=]\s*["']([^"'\s]{8,})["']""")),
]
PLACEHOLDER = re.compile(r"(?i)example|changeme|change_me|your[_-]|xxx|<.+>|\$\{|\{\{|dummy|sample|placeholder|test|\*{3}")
SECRET_EXT = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rb", ".php", ".cs", ".rs", ".sh", ".env",
              ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg", ".properties", ".tf", ".swift", ".kt", ".txt"}
SECRET_FILES = re.compile(r"(^|/)(\.env(\.[\w-]+)?|id_rsa|id_ed25519|credentials\.json|.*\.(pem|key|p12|pfx))$")
SECRET_FILE_OK = re.compile(r"\.(example|sample|template|dist)$|example")


def _redact(s: str) -> str:
    return s[:4] + "…" + f"({len(s)} chars)" if len(s) > 8 else "…"


def scan_secrets(root: str, files: list[str]) -> list[Finding]:
    out: list[Finding] = []
    for rel in files:
        if TEST_RE.search(rel) or rel.endswith((".lock", "package-lock.json", ".md")):
            continue
        if SECRET_FILES.search(rel) and not SECRET_FILE_OK.search(rel):
            out.append(Finding(file=rel, line_start=1, line_end=1, severity="critical", category="security",
                               title="Sensitive file committed to the repo", evidence=rel, source="secret-scan",
                               description="Credential-style files should never be version-controlled.",
                               fix="Remove it from git (git rm --cached), add it to .gitignore, rotate any keys in it.",
                               rule="SECRET"))
            continue
        if PurePath(rel).suffix.lower() not in SECRET_EXT:
            continue
        p = Path(root) / rel
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for label, sev, rx in SECRET_PATTERNS:
                m = rx.search(line)
                if not m:
                    continue
                value = m.group(1) if m.groups() else m.group(0)
                if PLACEHOLDER.search(value) or PLACEHOLDER.search(line) and label == "Hardcoded credential":
                    continue
                out.append(Finding(
                    file=rel, line_start=n, line_end=n, severity=sev, category="security",
                    title=f"{label} committed to the repo", evidence=line.replace(value, _redact(value)).strip()[:160],
                    description="Secrets in source control are exposed to everyone with repo access, including history.",
                    fix="Revoke/rotate the credential, load it from an environment variable or secret manager, "
                        "and purge it from git history (git filter-repo).",
                    source="secret-scan", rule="SECRET"))
                break
    return out


# ── hygiene checks ───────────────────────────────────────────────────────────
LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock", "go.sum",
             "cargo.lock", "gemfile.lock", "composer.lock", "uv.lock"}
MANIFESTS = ("requirements", "pyproject.toml", "package.json", "go.mod", "cargo.toml", "pom.xml",
             "build.gradle", "gemfile", "composer.json", "pipfile")
LINTERS = {"ruff.toml", ".ruff.toml", ".flake8", ".pylintrc", ".eslintrc", ".eslintrc.json", ".eslintrc.js",
           ".eslintrc.cjs", "eslint.config.js", "eslint.config.mjs", ".golangci.yml", ".rubocop.yml", "biome.json",
           ".prettierrc", "tox.ini"}


def hygiene_checks(root: str, files: list[str], secrets: list[Finding]) -> list[Check]:
    root_names = {f.lower() for f in files if "/" not in f}
    has_code = any(is_reviewable(f) for f in files)

    def read(rel: str) -> str:
        try:
            return (Path(root) / rel).read_text(errors="replace")
        except OSError:
            return ""

    readme = next((f for f in files if "/" not in f and f.lower().startswith("readme")), None)
    checks = [
        Check(id="readme", ok=bool(readme), weight=1.5, message="README present",
              fix="Add a README explaining what the project does, how to install, run and test it."),
        Check(id="readme_depth", ok=bool(readme) and len(read(readme).strip()) >= 400, weight=0.5,
              message="README is substantive (≥ 400 characters)", fix="Expand the README: setup, usage, examples."),
        Check(id="license", ok=any(n.startswith(("license", "licence", "copying")) for n in root_names), weight=1.0,
              message="License file present", fix="Add a LICENSE file (e.g. MIT, Apache-2.0) so others know how they may use the code."),
        Check(id="gitignore", ok=".gitignore" in root_names, weight=0.5, message=".gitignore present",
              fix="Add a .gitignore for build output, virtualenvs and local config."),
        Check(id="tests", ok=any(TEST_RE.search(f) for f in files) or not has_code, weight=3.0,
              message="Automated tests exist", fix="Add tests (start with the riskiest modules listed in this report) and run them in CI."),
        Check(id="ci", ok=any(f.startswith((".github/workflows/", ".circleci/")) or f in
                              (".gitlab-ci.yml", "azure-pipelines.yml", "Jenkinsfile", ".travis.yml") for f in files)
              or not has_code, weight=1.5, message="CI pipeline configured",
              fix="Add a CI workflow (GitHub Actions) that installs dependencies and runs tests + linting on every PR."),
        Check(id="linter", ok=any(PurePath(f).name.lower() in LINTERS for f in files)
              or any("[tool.ruff" in read(f) or "[tool.pylint" in read(f) for f in files if f.lower() == "pyproject.toml")
              or not has_code, weight=1.0, message="Linter / formatter configured",
              fix="Configure a linter (ruff, eslint, golangci-lint …) and enforce it in CI."),
    ]
    manifests = [f for f in files if PurePath(f).name.lower().startswith(MANIFESTS) or PurePath(f).name.lower() in MANIFESTS]
    req_files = [f for f in files if re.match(r"(?i)(.*/)?requirements[^/]*\.txt$", f)]
    pinned_ok, why = True, ""
    if req_files:
        lines = [l.strip() for f in req_files for l in read(f).splitlines()
                 if l.strip() and not l.lstrip().startswith(("#", "-"))]
        if lines and sum("==" in l for l in lines) / len(lines) < 0.8 and not (LOCKFILES & root_names):
            pinned_ok, why = False, "most requirements are not pinned (==) and there is no lockfile"
    if any(PurePath(f).name == "package.json" for f in files) and not (LOCKFILES & {PurePath(f).name.lower() for f in files}):
        pinned_ok, why = False, "package.json has no lockfile"
    checks.append(Check(id="dependencies", ok=pinned_ok or not manifests, weight=1.0,
                        message="Dependencies are pinned / locked" + (f" ({why})" if why else ""),
                        fix="Pin versions (==) or commit a lockfile so builds are reproducible."))
    checks.append(Check(id="secrets", ok=not secrets, weight=4.0,
                        message="No secrets committed" + (f" ({len(secrets)} found)" if secrets else ""),
                        fix="Rotate every exposed credential, then remove it from the repo and its history."))
    return checks


# ── scoring ──────────────────────────────────────────────────────────────────
SEV_W = {"critical": 4.0, "high": 2.0, "medium": 0.75, "low": 0.25}


AI_WEIGHT = 0.6  # model-only findings are less certain than static analysis / secret scans


def penalty_score(findings: list[Finding], loc: int) -> float:
    """Serious findings count in full; minor ones are scaled by repo size.

    Findings that only the AI reported count at 60%: they are usually right but the model can
    misjudge, and one shaky finding should not sink a whole repository's rating.
    """
    def w(f: Finding) -> float:
        return SEV_W[f.severity] * (AI_WEIGHT if f.source == "llm" else 1.0)
    hard = sum(w(f) for f in findings if f.severity in ("critical", "high"))
    soft = sum(w(f) for f in findings if f.severity not in ("critical", "high"))
    return max(1.0, min(10.0, 10 - hard - soft / max(1.0, loc / 1000)))


def grade(score: float) -> str:
    return "A" if score >= 9 else "B" if score >= 8 else "C" if score >= 6.5 else "D" if score >= 5 else "F"


def compute_scores(files: list[Report], secrets: list[Finding], hygiene: list[Check]) -> tuple[float, dict]:
    loc = sum(r.stats.get("lines", 0) for r in files)
    weights = [(r.score, max(20, min(r.stats.get("lines", 0), 400))) for r in files]
    code = sum(s * w for s, w in weights) / sum(w for _, w in weights) if weights else 10.0
    findings = [f for r in files for f in r.findings] + secrets
    security = penalty_score([f for f in findings if f.category == "security"], loc)
    reliability = penalty_score([f for f in findings if f.category == "bug"], loc)
    total_w = sum(c.weight for c in hygiene) or 1
    hyg = 10 * sum(c.weight for c in hygiene if c.ok) / total_w
    overall = 0.35 * code + 0.25 * security + 0.20 * reliability + 0.20 * hyg
    if any(f.severity == "critical" for f in findings):
        overall = min(overall, 7.0)  # a critical issue always caps the rating
    bd = {"code_quality": code, "security": security, "reliability": reliability, "project_hygiene": hyg}
    return round(max(1.0, overall), 1), {k: round(v, 1) for k, v in bd.items()}


# ── action plan ──────────────────────────────────────────────────────────────
def build_actions(files: list[Report], secrets: list[Finding], hygiene: list[Check]) -> list[Action]:
    acts: list[Action] = []
    sev_pri = {"critical": "P0", "high": "P1", "medium": "P2", "low": "P3"}

    def loc(f: Finding) -> str:
        return f"{f.file}:{f.line_start}" if f.line_start == f.line_end else f"{f.file}:{f.line_start}-{f.line_end}"

    for f in secrets:
        acts.append(Action(priority="P0", kind="secret", title=f.title, location=loc(f),
                           detail=f.evidence, fix=f.fix))
    for r in files:
        for f in r.findings:
            acts.append(Action(priority=sev_pri.get(f.severity, "P3"), title=f.title, location=loc(f),
                               detail=f.description if f.description not in f.title else "", fix=f.fix))
    for c in hygiene:
        if not c.ok and c.id != "secrets":
            acts.append(Action(priority="P1" if c.weight >= 3 else "P2" if c.weight >= 1 else "P3", kind="hygiene",
                               title=f"Missing: {c.message}", fix=c.fix))
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return sorted(acts, key=lambda a: (order[a.priority], a.kind != "secret", a.location))


def build_themes(files: list[Report]) -> list[str]:
    rules: dict[str, list[Finding]] = {}
    for r in files:
        for f in r.findings:
            if f.rule:
                rules.setdefault(f.rule, []).append(f)
    out = []
    for rule, fs in sorted(rules.items(), key=lambda kv: -len(kv[1])):
        n_files = len({f.file for f in fs})
        if len(fs) >= 3:
            out.append(f"{rule} appears {len(fs)}× across {n_files} file(s): {fs[0].title.split(': ', 1)[-1]}")
    return out[:6]


# ── orchestration ────────────────────────────────────────────────────────────
async def clone(url: str) -> tuple[str, str]:
    """Shallow-clone a public GitHub repo into a temp dir. Returns (tmp, repo_dir)."""
    if not GITHUB_RE.match(url):
        raise ValueError("Only https://github.com/<owner>/<repo> URLs are supported.")
    tmp = tempfile.mkdtemp(prefix="review-")
    dest = os.path.join(tmp, "repo")
    proc = await asyncio.create_subprocess_exec(
        "git", "clone", "--depth", "1", "--quiet", url, dest,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=180)
    except asyncio.TimeoutError:
        proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError("git clone timed out") from None
    if proc.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError(f"git clone failed: {err.decode(errors='replace').strip()[:200]}")
    return tmp, dest


async def review_repo(root: str, config: Config | None = None, max_files: int = 25, *,
                      on_progress: Callable[[dict], None] | None = None,
                      lock: asyncio.Lock | None = None) -> RepoReport:
    cfg = config or Config()
    t0 = time.time()
    emit = on_progress or (lambda _e: None)
    root = str(Path(root).resolve())
    files = list_files(root, cfg.ignore_paths)
    if not files:
        raise ValueError(f"No files found in {root}")

    emit({"phase": "scanning", "done": 0, "total": 0, "current": ""})
    candidates: list[tuple[float, str, str, int]] = []  # (priority, path, code, lines)
    total_loc = 0
    for rel in files:
        if not is_reviewable(rel):
            continue
        p = Path(root) / rel
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            code = p.read_text(errors="replace")
        except OSError:
            continue
        n = len(code.splitlines())
        if n < 3 or not code.strip():
            continue
        lang = "python" if rel.endswith(".py") else "other"
        static = run_static(rel, code, lang) if cfg.use_static else []
        total_loc += n
        candidates.append((priority(rel, n, static), rel, code, n))
    if not candidates:
        raise ValueError("No reviewable source files found (supported: py, js, ts, java, go, rs, c/c++, …).")
    candidates.sort(key=lambda c: -c[0])
    chosen, rest = candidates[:max_files], candidates[max_files:]

    secrets = scan_secrets(root, files)
    reports: list[Report] = []
    errors: list[str] = []
    for i, (_, rel, code, _n) in enumerate(chosen):
        emit({"phase": "reviewing", "done": i, "total": len(chosen), "current": rel})
        try:
            async with (lock or nullcontext()):
                reports.append(await review_source(rel, code, config=cfg))
        except LLMError as e:
            if not reports and ("cannot reach" in str(e) or "not found" in str(e)):
                raise  # Ollama down / model missing: no point continuing
            errors.append(f"{rel}: {e}")
    emit({"phase": "scoring", "done": len(chosen), "total": len(chosen), "current": ""})

    hygiene = hygiene_checks(root, files, secrets)
    score, breakdown = compute_scores(reports, secrets, hygiene)
    reviewed_loc = sum(r.stats.get("lines", 0) for r in reports)
    coverage = reviewed_loc / total_loc if total_loc else 1.0
    actions = build_actions(reports, secrets, hygiene)
    reports.sort(key=lambda r: (r.score, -len(r.findings)))
    return RepoReport(
        root=root, score=score, grade=grade(score), breakdown=breakdown, files=reports, secrets=secrets,
        hygiene=hygiene, actions=actions, themes=build_themes(reports),
        stats={
            "files_total": len(candidates), "files_reviewed": len(reports), "files_skipped": [c[1] for c in rest],
            "lines_total": total_loc, "lines_reviewed": reviewed_loc, "coverage": round(coverage, 2),
            "confidence": "high" if coverage >= 0.8 else "medium" if coverage >= 0.4 else "low",
            "seconds": round(time.time() - t0, 1), "model": cfg.model or DEFAULT_MODEL, "errors": errors,
            "actions_total": len(actions),
        })
