# AI Code Review Agent

A **local, private** code reviewer. It runs on your own machine with [Ollama](https://ollama.com) — no API key, no cloud, nothing leaves your laptop.

Unlike a plain "paste code into an LLM" tool, it is built to be **trusted**:

| Problem with naive LLM review | What this project does |
|---|---|
| Invents bugs that aren't in the code | Every finding must **quote the offending line verbatim**. Quotes that aren't in the file are discarded as hallucinations. |
| Cites the wrong line numbers | Code is sent with line numbers, and each finding's lines are **snapped to where its quote really is**. |
| Misses things linters catch for free | Python files get **ruff** checks (bugs + security rules) and a syntax check first; the LLM is told not to repeat them. |
| Reviews the whole file when you changed 3 lines | `--staged` / `--diff` review **only your changed lines**, with the rest of the file as context. |
| Score changes every run | Score is **computed from verified findings**, and results are cached (same code = same answer, instantly). |
| Nitpicks (docstrings, type hints…) | Style noise is filtered out by default; severity is calibrated in the prompt. |
| Breaks on big files | Files are split at top-level boundaries into model-sized chunks. |

## Setup

```bash
git clone https://github.com/Aadithyaar22/ai-code-review-agent.git
cd ai-code-review-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

ollama serve &            # if not already running
ollama pull phi4          # default model (any Ollama model works, see OLLAMA_MODEL)
```

## CLI

```bash
python cli.py app.py                  # review a file
python cli.py src/                    # review a whole directory (respects .gitignore)
python cli.py --staged                # review what you're about to commit (changed lines only)
python cli.py --diff main             # review changes against main
cat snippet.js | python cli.py - --language javascript

python cli.py src/ --format markdown -o review.md
python cli.py --staged --format sarif -o review.sarif   # for GitHub code scanning
python cli.py --staged --fail-on critical               # exit 1 only for critical issues

python cli.py --install-hook          # block commits that contain serious issues
```

Exit code: `0` clean, `1` findings at/above `--fail-on` (default `high`), `2` error (e.g. Ollama not running).

Options: `--model`, `--min-severity`, `--include-style`, `--context "Django app, we use pytest"`, `--no-cache`, `--no-static`.

### Project settings

Drop a `.reviewrc.json` in the directory you run from (see `.reviewrc.example.json`):

```json
{
  "model": "phi4",
  "context": "Flask API; we use SQLAlchemy and pytest.",
  "ignore_categories": ["style"],
  "min_severity": "low",
  "ignore_paths": ["migrations/*", "*.generated.py"]
}
```

## GitHub Action (PR review → code-scanning alerts)

`.github/workflows/code-review.yml` runs on every pull request. It installs Ollama on the runner, reviews **only the lines the PR changed**, uploads the result as SARIF (findings appear in the **Security → Code scanning** tab and as annotations on the PR), and writes a Markdown report to the job summary. Nothing leaves the runner — no API key needed.

- **Model:** defaults to `qwen2.5:7b` (practical on CPU-only runners). Set a repository variable `REVIEW_MODEL` (Settings → Secrets and variables → Actions → Variables) to use another, e.g. `llama3.1:8b`. Models are cached between runs.
- **Requirements:** code scanning must be available — free for public repos; private repos need GitHub Code Security. Without it, the job summary still has the full report.
- **Forks:** PRs from forks get a read-only token, so they skip the SARIF upload but keep the job summary.
- **Manual run:** *Actions → AI code review → Run workflow* reviews a whole directory.
- **Speed:** expect a few minutes for the first run (Ollama install + model download), faster once the model is cached.
- The job never fails the PR; to gate merges, require the *Code scanning results* check in branch protection, or change `--fail-on never` to e.g. `--fail-on high` in the workflow.

## Web UI and API

```bash
python main.py        # http://127.0.0.1:8080  (UI)   ·   /docs (Swagger)
```

```bash
curl -X POST localhost:8080/review -H 'Content-Type: application/json' \
  -d '{"code": "def f(a, b):\n    return a / b", "language": "python"}'
```

`GET /health` · `POST /review` (`code`, optional `language`, `filename`). Errors: `400` empty, `413` over 100,000 chars, `502` Ollama problem. The response has the original `bugs` / `security_issues` / `suggestions` lists plus a richer `findings` list (file, line range, severity, category, evidence, fix, confidence, source) and `stats`. The server only accepts browser requests from localhost.

## How it works

```
 file / diff / snippet
        │
        ├─► ruff + syntax check (python) ───────────────┐  deterministic, instant
        │                                               │
        ├─► split into chunks (top-level boundaries)    │
        │        │                                      │
        │        ▼                                      │
        │   numbered code + project context + "already detected" list
        │        │
        │        ▼
        │   Ollama (JSON-schema-constrained output) ── cached in SQLite
        │        │
        │        ▼
        │   verify: quote must exist in file · snap line numbers · drop low confidence / noise
        │        │
        └────────┴─► merge + dedupe (static wins) ─► filter (diff lines, severity, categories)
                              │
                              ▼
                 score + report (text · json · markdown · sarif)
```

```
cli.py              entry point          main.py            FastAPI server + UI
reviewer/
  engine.py         pipeline             verify.py          hallucination filter, dedupe
  prompt.py         prompt + JSON schema static.py          ruff / syntax checks
  llm.py            Ollama client        chunk.py           file splitting
  diffparse.py      unified-diff parser  gitutil.py         git helpers
  cache.py          SQLite cache         config.py          .reviewrc.json
  formats.py        text/md/json/sarif   models.py          Finding, Report, scoring
tests/              unit tests (mocked LLM) + live golden tests
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest              # fast unit tests, no model needed
pytest -m live      # golden tests against your local Ollama model (~2 min)
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `phi4` | Model used for review |
| `OLLAMA_HOST` | `http://localhost:11434` | Where Ollama runs |
| `REVIEW_CACHE_DIR` | `~/.cache/code-review-agent` | Result cache location |
| `PORT` | `8080` | Web server port |

## Limits

- Reviews are only as good as the local model; bigger models (`phi4`, `qwen2.5:14b`+) find more.
- Static checks cover Python only; other languages rely on the LLM plus the evidence check.
- The model sees one chunk at a time, so cross-file issues are out of scope.
