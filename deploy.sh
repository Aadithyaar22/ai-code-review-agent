#!/usr/bin/env bash
# deploy.sh
#
# Builds and deploys the Code Review Agent to Google Cloud Run.
# Uses Secret Manager to store the Gemini API key — no plaintext secrets
# in environment variables or source control.
#
# Prerequisites
# ─────────────
#   1. gcloud CLI installed and authenticated   (gcloud auth login)
#   2. Docker installed and running
#   3. A GCP project you own
#   4. GOOGLE_API_KEY exported (Gemini Developer API key)
#      Get one at: https://aistudio.google.com/app/apikey
#
# Usage
# ─────
#   export GCP_PROJECT_ID=your-project-id
#   export GOOGLE_API_KEY=your-gemini-api-key
#   chmod +x deploy.sh && ./deploy.sh

set -euo pipefail

# ── Config — edit if needed ───────────────────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:?Please export GCP_PROJECT_ID}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="code-review-agent"
SECRET_NAME="gemini-api-key"
REPO_NAME="cloud-run-source-deploy"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:latest"
GOOGLE_API_KEY="${GOOGLE_API_KEY:?Please export GOOGLE_API_KEY}"
# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║       Code Review Agent  —  GCP Deploy       ║"
echo "╚══════════════════════════════════════════════╝"
echo "  Project : ${PROJECT_ID}"
echo "  Region  : ${REGION}"
echo "  Service : ${SERVICE_NAME}"
echo ""

# 1. Set project
echo "▶  Setting GCP project …"
gcloud config set project "${PROJECT_ID}" --quiet

# 2. Enable required APIs
echo "▶  Enabling APIs (Cloud Run, Artifact Registry, Secret Manager, Cloud Build) …"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  --quiet

# 3. Create Artifact Registry repo (idempotent)
echo "▶  Ensuring Artifact Registry repository exists …"
gcloud artifacts repositories describe "${REPO_NAME}" \
  --location="${REGION}" --quiet 2>/dev/null || \
gcloud artifacts repositories create "${REPO_NAME}" \
  --repository-format=docker \
  --location="${REGION}" \
  --quiet
echo "   ✓  Repository: ${REPO_NAME}"

# 4. Store API key in Secret Manager (idempotent)
echo "▶  Storing Gemini API key in Secret Manager …"
if gcloud secrets describe "${SECRET_NAME}" --quiet 2>/dev/null; then
  # Secret exists — add a new version
  echo -n "${GOOGLE_API_KEY}" | \
    gcloud secrets versions add "${SECRET_NAME}" --data-file=- --quiet
  echo "   ✓  Added new version to existing secret: ${SECRET_NAME}"
else
  # Create fresh secret
  echo -n "${GOOGLE_API_KEY}" | \
    gcloud secrets create "${SECRET_NAME}" \
      --data-file=- \
      --replication-policy=automatic \
      --quiet
  echo "   ✓  Created secret: ${SECRET_NAME}"
fi

# 5. Grant Cloud Run's service account access to the secret
echo "▶  Granting Cloud Run SA access to secret …"
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" \
  --format="value(projectNumber)")
CR_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --member="serviceAccount:${CR_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --quiet
echo "   ✓  IAM binding set for ${CR_SA}"

# 6. Build & push Docker image
echo "▶  Authenticating Docker with Artifact Registry …"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

echo "▶  Building Docker image (linux/amd64) …"
docker build --platform linux/amd64 -t "${IMAGE}" .

echo "▶  Pushing image to Artifact Registry …"
docker push "${IMAGE}"
echo "   ✓  Image: ${IMAGE}"

# 7. Deploy to Cloud Run
echo "▶  Deploying to Cloud Run …"
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE}" \
  --platform=managed \
  --region="${REGION}" \
  --allow-unauthenticated \
  --set-secrets="GOOGLE_API_KEY=${SECRET_NAME}:latest" \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=10 \
  --port=8080 \
  --quiet

# 8. Print results
echo ""
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" --format="value(status.url)")

echo "╔══════════════════════════════════════════════╗"
echo "║             ✅  Deploy Successful             ║"
echo "╠══════════════════════════════════════════════╣"
echo "║  URL   : ${SERVICE_URL}"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "  Health check:"
echo "    curl ${SERVICE_URL}/health"
echo ""
echo "  Code review:"
echo "    curl -X POST ${SERVICE_URL}/review \\"
echo "         -H 'Content-Type: application/json' \\"
echo "         -d '{\"code\": \"def divide(a,b): return a/b\", \"language\": \"python\"}'"
echo ""
echo "  Interactive docs:"
echo "    ${SERVICE_URL}/docs"
