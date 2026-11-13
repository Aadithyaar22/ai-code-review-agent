<div align="center">

<br/>

```
 ██████╗ ██████╗ ██████╗ ███████╗    ██████╗ ███████╗██╗   ██╗██╗███████╗██╗    ██╗
██╔════╝██╔═══██╗██╔══██╗██╔════╝    ██╔══██╗██╔════╝██║   ██║██║██╔════╝██║    ██║
██║     ██║   ██║██║  ██║█████╗      ██████╔╝█████╗  ██║   ██║██║█████╗  ██║ █╗ ██║
██║     ██║   ██║██║  ██║██╔══╝      ██╔══██╗██╔══╝  ╚██╗ ██╔╝██║██╔══╝  ██║███╗██║
╚██████╗╚██████╔╝██████╔╝███████╗    ██║  ██║███████╗ ╚████╔╝ ██║███████╗╚███╔███╔╝
 ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝    ╚═╝  ╚═╝╚══════╝  ╚═══╝  ╚═╝╚══════╝ ╚══╝╚══╝
```

### *Your AI-powered senior engineer — available 24/7, brutally honest, never tired.*

<br/>

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Ollama](https://img.shields.io/badge/Ollama-local_LLM-000000?style=for-the-badge)](https://ollama.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)

<br/>

**[🚀 Try the Live API](#-live-demo) · [⚙️ Run Locally](#-run-locally-in-4-steps) · [📖 API Docs](#-api-reference)**

<br/>

> **Built with:** Ollama (local LLM) · FastAPI · Python

</div>

---

## 💡 What is this?

Paste any code snippet. Get back a **structured, actionable review** — bugs, security holes, improvements, and a quality score — powered by a local LLM through Ollama.

```
You paste this:                        You get back this:
──────────────────────────────         ──────────────────────────────────────────────
def divide(a, b):              →       ❌ Bug (critical):  ZeroDivisionError on b=0
    return a / b                       🔐 Security:        None found
                                       💡 Suggestion:      Add type hints
result = divide(10, 0)                 ✅ Positive:        Single-purpose function
                                       ⭐ Score:           3 / 10
```

No IDE plugin. No GitHub integration. Just a clean REST API — call it from anywhere.

---

## 🏗️ How it works

```
                    ┌──────────────────────────────┐
                    │   POST /review               │
                    │   { "code": "...",           │
                    │     "language": "python" }   │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │         FastAPI               │  main.py
                    │    (request validation)       │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │      agent/llm.py             │  async HTTP client
                    │   (system prompt + JSON mode) │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     review prompt             │  agent/agent.py
                    │   (strict JSON schema rules)  │
                    │                               │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │      Ollama (localhost)       │
                    │   model: phi4 · no API key    │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     Structured JSON Report    │
                    │  bugs · security · score · +  │
                    └──────────────────────────────┘
```

## 📁 Project layout

```
ai-code-review-agent/
│
├── 📂 agent/
│   ├── agent.py          ← system prompt (JSON schema + review rules)
│   └── llm.py            ← Ollama client, JSON parsing & validation
│
├── main.py               ← FastAPI server (web UI + REST API)
├── cli.py                ← local CLI (files, stdin, git diffs)
├── static/index.html     ← web UI
├── tests/                ← mocked unit tests + live golden tests
└── requirements.txt
```

---

## ⚡ Run locally in 4 steps

```bash
# 1 — Clone and create virtual environment
git clone https://github.com/Aadithyaar22/ai-code-review-agent.git
cd ai-code-review-agent
python -m venv .venv && source .venv/bin/activate

# 2 — Install dependencies
pip install -r requirements.txt

# 3 — Start Ollama and pull a model (no API key needed)
ollama serve &
ollama pull phi4

# 4 — Start the server
python main.py
```

Server runs at `http://localhost:8080` · Swagger UI at `http://localhost:8080/docs`

### Test it immediately

```bash
# Health check
curl http://localhost:8080/health

# Review a snippet with a classic division-by-zero bug
curl -X POST http://localhost:8080/review \
     -H "Content-Type: application/json" \
     -d '{
           "code": "def divide(a, b):\n    return a / b\n\nresult = divide(10, 0)",
           "language": "python"
         }'
```

**What comes back:**

```json
{
  "session_id": "3f8a1b2c-...",
  "review": {
    "language": "python",
    "overall_score": 3,
    "summary": "The function performs division without guarding against division by zero, causing a crash on the very next line.",
    "bugs": [
      {
        "line": "2",
        "severity": "critical",
        "description": "No guard against b=0 — raises ZeroDivisionError at runtime.",
        "fix": "Add `if b == 0: raise ValueError('Divisor cannot be zero')` before the return."
      }
    ],
    "security_issues": [],
    "suggestions": [
      {
        "category": "readability",
        "description": "Add type hints to parameters and return value.",
        "example": "def divide(a: float, b: float) -> float:"
      }
    ],
    "positives": ["Function is concise and single-purpose."]
  }
}
```

---

## 🖥️ Local CLI (no server)

```bash
python cli.py app.py utils.py     # review files
python cli.py --staged            # review `git diff --staged`
python cli.py --diff main         # review changes against main
cat snippet.js | python cli.py -  # review stdin
python cli.py --staged --json     # raw JSON output
```

Exits with code `1` if any critical/high issue is found, so it works as a pre-commit hook:

```bash
printf '#!/bin/sh\n.venv/bin/python cli.py --staged\n' > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

---

## 📖 API Reference

### `GET /health`

```json
{ "status": "ok", "agent": "code_review_agent", "model": "phi4" }
```

---

### `POST /review`

**Request body**

```json
{
  "code": "string  (required)",
  "language": "string  (optional — auto-detected if omitted)"
}
```

**Response schema**

```json
{
  "session_id": "uuid",
  "review": {
    "language":      "string",
    "overall_score": "integer  1–10",
    "summary":       "string",
    "bugs": [{
      "line":        "string",
      "severity":    "critical | high | medium | low",
      "description": "string",
      "fix":         "string"
    }],
    "security_issues": [{
      "line":        "string",
      "severity":    "string",
      "description": "string",
      "fix":         "string"
    }],
    "suggestions": [{
      "category":    "readability | performance | maintainability",
      "description": "string",
      "example":     "string | null"
    }],
    "positives": ["string"]
  }
}
```

**Error codes**

| Code | When |
|---|---|
| `400` | `code` field is missing or empty |
| `413` | `code` is longer than 100,000 characters |
| `502` | Ollama unreachable, model missing, or malformed output |

---

## 🧪 Tests

```bash
pip install -r requirements-dev.txt
pytest              # fast unit tests, LLM mocked
pytest -m live      # golden tests against your local Ollama model
```

---

## 🌍 Environment variables

| Variable | Default | What it does |
|---|---|---|
| `OLLAMA_MODEL` | `phi4` | Which local model reviews the code |
| `OLLAMA_HOST` | `http://localhost:11434` | Where Ollama is running |
| `PORT` | `8080` | HTTP port the server listens on |

---

## 🚧 Limitations & roadmap

| Current limitation | Planned improvement |
|---|---|
| Single-agent, single-turn | Multi-turn conversation for iterative review |
| No file upload support | Accept `.py`, `.js`, `.ts` files directly |
| Unauthenticated endpoint | Add API key auth if exposed beyond localhost |
| No persistent history | Store reviews in SQLite |
| English output only | Multi-language review responses |

---

## 👤 About

Built by **Aadithya** — CSE (AI & ML) undergrad who likes building things that actually work in production.

This project runs entirely on your machine: a local LLM via Ollama, structured JSON output, a FastAPI service, a CLI for git diffs, and tests — nothing leaves your laptop.

<br/>

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/aadithya-a-r)
[![GitHub](https://img.shields.io/badge/GitHub-Follow-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Aadithyaar22)

---

<div align="center">

**If this was useful, drop a ⭐ — it takes 2 seconds and means a lot**

*Runs locally · Powered by Ollama · Built by a human*

</div>
