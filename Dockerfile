# ── Stage 1: install dependencies ────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: lean runtime image ───────────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# System dependencies (IMPORTANT)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python env
ENV PYTHONUNBUFFERED=1

COPY --from=builder /install /usr/local

COPY main.py .
COPY agent/ ./agent/
COPY static/ ./static/  

# Cloud Run injects PORT at runtime; 8080 is the expected default
ENV PORT=8080
EXPOSE 8080

# Launch uvicorn, binding to 0.0.0.0 and the dynamic Cloud Run port
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]