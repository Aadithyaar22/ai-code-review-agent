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
[![Gemini](https://img.shields.io/badge/Gemini-2.0_Flash-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://deepmind.google/gemini)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Cloud Run](https://img.shields.io/badge/Cloud_Run-Deployed-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white)](https://cloud.google.com/run)
[![ADK](https://img.shields.io/badge/Google_ADK-Agent_Framework-EA4335?style=for-the-badge&logo=google&logoColor=white)](https://google.github.io/adk-docs)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)

<br/>

**[🚀 Try the Live API](#-live-demo) · [⚙️ Run Locally](#-run-locally-in-4-steps) · [☁️ Deploy to GCP](#-deploy-to-gcp-in-1-command) · [📖 API Docs](#-api-reference)**

<br/>

> **Built with:** Google ADK · Gemini 2.0 Flash · FastAPI · Cloud Run · Secret Manager · Docker

</div>

---

## 💡 What is this?

Paste any code snippet. Get back a **structured, actionable review** — bugs, security holes, improvements, and a quality score — powered by Gemini 2.0 Flash via Google's Agent Development Kit (ADK).

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
                    │         ADK Runner            │  per-request ephemeral session
                    │   (InMemorySessionService)    │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │       root_agent              │  agent/agent.py
                    │   model: gemini-2.0-flash     │
                    │   + structured JSON prompt    │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │        Gemini API             │
                    │   (key via Secret Manager)    │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     Structured JSON Report    │
                    │  bugs · security · score · +  │
                    └──────────────────────────────┘
```

### GCP services at a glance

| Service | Role |
|---|---|
| **Cloud Run** | Serverless container — scales to zero, 0–10 instances |
| **Artifact Registry** | Stores the Docker image |
| **Secret Manager** | Gemini API key — never in env vars or logs |
| **Cloud Build** | Optional CI/CD pipeline |

---

## 📁 Project layout

```
code-review-agent/
│
├── 📂 agent/
│   ├── __init__.py
│   └── agent.py          ← ADK Agent definition (model + system instruction)
│
├── main.py               ← FastAPI server + ADK Runner wiring
├── requirements.txt      ← All dependencies pinned
├── Dockerfile            ← linux/amd64 production image
├── deploy.sh             ← One-command GCP deployment script
└── README.md
```

---

## ⚡ Run locally in 4 steps

```bash
# 1 — Clone and create virtual environment
git clone https://github.com/Aadithyaar22/code-review-agent.git
cd code-review-agent
python -m venv .venv && source .venv/bin/activate

# 2 — Install dependencies
pip install -r requirements.txt

# 3 — Set your Gemini API key  →  https://aistudio.google.com/app/apikey
export GOOGLE_API_KEY=your-key-here

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

## ☁️ Deploy to GCP in 1 command

### Prerequisites

| Tool | How to get it |
|---|---|
| `gcloud` CLI | [cloud.google.com/sdk](https://cloud.google.com/sdk/docs/install) |
| Docker | [docs.docker.com](https://docs.docker.com/get-docker/) |
| GCP project | `gcloud projects create <id>` or use existing |
| Gemini API key | [aistudio.google.com](https://aistudio.google.com/app/apikey) |

### Deploy

```bash
chmod +x deploy.sh

export GCP_PROJECT_ID=your-project-id
export GOOGLE_API_KEY=your-gemini-key

./deploy.sh
```

### What the script does — step by step

```
Step 1 →  Enables Cloud Run, Artifact Registry, Secret Manager, Cloud Build APIs
Step 2 →  Stores Gemini key in Secret Manager (never exposed in logs or env vars)
Step 3 →  Grants Cloud Run service account secretAccessor permission
Step 4 →  Builds linux/amd64 Docker image + pushes to Artifact Registry
Step 5 →  Deploys to Cloud Run (unauthenticated · 0–10 instances · 512 MB RAM)
Step 6 →  Prints live URL + ready-to-use curl commands
```

### After deploy

```bash
BASE=https://code-review-agent-xxxx-uc.a.run.app   # printed by deploy.sh

# Health
curl $BASE/health

# Review an SQL injection vulnerability
curl -X POST $BASE/review \
     -H "Content-Type: application/json" \
     -d '{"code": "SELECT * FROM users WHERE id = '\''\" + user_input + \"'\''", "language": "sql"}'

# Interactive Swagger UI
open $BASE/docs
```

---

## 📖 API Reference

### `GET /health`

```json
{ "status": "ok", "agent": "code_review_agent", "model": "gemini-2.0-flash" }
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
| `500` | Gemini returned empty or malformed response |

---

## 🌍 Environment variables

| Variable | In production | In local dev | What it does |
|---|---|---|---|
| `GOOGLE_API_KEY` | Secret Manager | `export` in terminal | Authenticates with Gemini API |
| `PORT` | Set by Cloud Run | Defaults to `8080` | HTTP port the server listens on |

---

## 🧰 Tech stack

```
AI Agent Framework    Google ADK (Agent Development Kit)
LLM                   Gemini 2.0 Flash
API Server            FastAPI + Uvicorn
Containerisation      Docker (linux/amd64)
Cloud Hosting         Google Cloud Run (serverless)
Image Registry        Google Artifact Registry
Secret Management     Google Secret Manager
```

---

## 🚧 Limitations & roadmap

| Current limitation | Planned improvement |
|---|---|
| Single-agent, single-turn | Multi-turn conversation for iterative review |
| No file upload support | Accept `.py`, `.js`, `.ts` files directly |
| Unauthenticated endpoint | Add API key auth or Google OAuth |
| No persistent history | Store reviews in Firestore per user |
| English output only | Multi-language review responses |

---

## 👤 About

Built by **Aadithya** — CSE (AI & ML) undergrad who likes building things that actually work in production.

This project demonstrates end-to-end cloud-native AI engineering: agent design with Google ADK, structured LLM output, containerised deployment, and secrets management on GCP — the full stack, not just a notebook.

<br/>

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/aadithya-a-r)
[![GitHub](https://img.shields.io/badge/GitHub-Follow-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/Aadithyaar22)

---

<div align="center">

**If this was useful, drop a ⭐ — it takes 2 seconds and means a lot**

*Deployed on Google Cloud Run · Powered by Gemini 2.0 Flash · Built by a human*

</div>
