# Code Review Agent · ADK + Gemini on Cloud Run

An AI-powered code review agent built with **Google ADK** and **Gemini 2.0 Flash**,
deployed on **Google Cloud Run** with secrets stored in **Secret Manager**.

Paste any code snippet → receive a structured JSON report with:
- 🐛 **Bugs** (with severity + fix)
- 🔐 **Security issues** (with severity + fix)
- 💡 **Improvement suggestions** (readability, performance, maintainability)
- ✅ **Positives** (what was done well)
- ⭐ **Overall quality score** (1–10)

---

## Architecture

```
Client
  │
  ▼  POST /review  { "code": "...", "language": "(optional)" }
FastAPI  (main.py)
  │
  ▼
ADK Runner  ──►  InMemorySessionService (ephemeral per-request session)
  │
  ▼
root_agent  (agent/agent.py)   model: gemini-2.0-flash
  │
  ▼
Gemini API  →  structured JSON review
  │
  ▼
{ "session_id": "...", "review": { ... } }
```

**GCP services used:**
| Service | Purpose |
|---|---|
| Cloud Run | Serverless container host |
| Artifact Registry | Docker image storage |
| Secret Manager | Secure Gemini API key storage |
| Cloud Build | (optional) CI/CD |

---

## Project Structure

```
code-review-agent/
├── agent/
│   ├── __init__.py
│   └── agent.py        ← ADK Agent (Gemini model + review instruction)
├── main.py             ← FastAPI server + ADK Runner wiring
├── requirements.txt
├── Dockerfile
├── deploy.sh           ← One-command GCP deployment
└── README.md
```

---

## Local Development

```bash
# 1. Create venv
python -m venv .venv && source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set Gemini API key  (https://aistudio.google.com/app/apikey)
export GOOGLE_API_KEY=your-key-here

# 4. Run
python main.py
```

### Test locally

```bash
# Health check
curl http://localhost:8080/health

# Review a snippet with a division-by-zero bug
curl -X POST http://localhost:8080/review \
     -H "Content-Type: application/json" \
     -d '{
       "code": "def divide(a, b):\n    return a / b\n\nresult = divide(10, 0)",
       "language": "python"
     }'
```

**Example response:**
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
        "description": "No guard against b=0; raises ZeroDivisionError at runtime.",
        "fix": "Add `if b == 0: raise ValueError('Divisor cannot be zero')` before the return statement."
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

## Deploy to Cloud Run

### Prerequisites

| Requirement | How to get it |
|---|---|
| `gcloud` CLI | [Install guide](https://cloud.google.com/sdk/docs/install) |
| Docker | [Install guide](https://docs.docker.com/get-docker/) |
| GCP project | `gcloud projects create <id>` or existing |
| Gemini API key | [aistudio.google.com](https://aistudio.google.com/app/apikey) |

### One command

```bash
chmod +x deploy.sh

export GCP_PROJECT_ID=your-project-id
export GOOGLE_API_KEY=your-gemini-key

./deploy.sh
```

The script:
1. Enables Cloud Run, Artifact Registry, Secret Manager, Cloud Build APIs
2. Stores your Gemini API key in **Secret Manager** (never exposed in env vars or logs)
3. Grants the Cloud Run service account `secretAccessor` permission
4. Builds and pushes a `linux/amd64` Docker image to Artifact Registry
5. Deploys to Cloud Run (unauthenticated, 0–10 instances, 512 MB)
6. Prints the live URL + example curl commands

### After deploy

```bash
# The URL printed by deploy.sh, e.g.:
BASE=https://code-review-agent-xxxx-uc.a.run.app

# Health
curl $BASE/health

# Review
curl -X POST $BASE/review \
     -H "Content-Type: application/json" \
     -d '{"code": "SELECT * FROM users WHERE id = '\''" + user_input + "'\''", "language": "sql"}'

# Swagger UI
open $BASE/docs
```

---

## API Reference

### `GET /health`
```json
{ "status": "ok", "agent": "code_review_agent", "model": "gemini-2.0-flash" }
```

### `POST /review`

**Request:**
```json
{
  "code": "string (required)",
  "language": "string (optional — auto-detected if omitted)"
}
```

**Response:**
```json
{
  "session_id": "uuid",
  "review": {
    "language": "string",
    "overall_score": "integer 1–10",
    "summary": "string",
    "bugs": [{ "line": "string", "severity": "critical|high|medium|low", "description": "string", "fix": "string" }],
    "security_issues": [{ "line": "string", "severity": "string", "description": "string", "fix": "string" }],
    "suggestions": [{ "category": "string", "description": "string", "example": "string|null" }],
    "positives": ["string"]
  }
}
```

**Errors:**
| Code | Reason |
|---|---|
| 400 | `code` field is empty |
| 500 | Gemini returned empty or malformed response |

---

## Environment Variables

| Variable | Source | Description |
|---|---|---|
| `GOOGLE_API_KEY` | Secret Manager (prod) / export (local) | Gemini Developer API key |
| `PORT` | Cloud Run (auto) | HTTP port — defaults to 8080 |
