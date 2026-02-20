#!/bin/bash
set -e

# ── AI Trading Agent — Full GCP Deployment ──────────────────────────────────
#
# This script sets up everything from scratch:
#   1. GCP project + APIs
#   2. Secrets in Secret Manager
#   3. Container image build + push
#   4. Cloud Run Service (Telegram bot with webhook)
#   5. Cloud Run Job (pipeline)
#   6. Cloud Scheduler (automated runs)
#   7. Telegram webhook registration
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Docker installed (or use Cloud Build)
#   - A .env file with all required secrets
#
# Usage:
#   chmod +x cloud/deploy.sh
#   ./cloud/deploy.sh
# ─────────────────────────────────────────────────────────────────────────────

# ── Configuration ────────────────────────────────────────────────────────────

# Load from environment or prompt
PROJECT_ID="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="trading-agent-bot"
JOB_NAME="trading-agent-pipeline"
IMAGE_NAME="trading-agent"

if [ -z "$PROJECT_ID" ]; then
    read -r -p "GCP Project ID: " PROJECT_ID
fi
if [ -z "$REGION" ]; then
    read -r -p "GCP Region [us-central1]: " REGION
    REGION="${REGION:-us-central1}"
fi

REGISTRY="${REGION}-docker.pkg.dev/${PROJECT_ID}/trading-agent"

echo ""
echo "══════════════════════════════════════════════════"
echo "  AI Trading Agent — Cloud Deployment"
echo "══════════════════════════════════════════════════"
echo "  Project:  $PROJECT_ID"
echo "  Region:   $REGION"
echo "  Service:  $SERVICE_NAME"
echo "  Job:      $JOB_NAME"
echo "══════════════════════════════════════════════════"
echo ""

# ── Step 1: Enable APIs ─────────────────────────────────────────────────────

echo "Step 1: Enabling required APIs..."
gcloud services enable \
    run.googleapis.com \
    cloudscheduler.googleapis.com \
    secretmanager.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com \
    --project="$PROJECT_ID"

echo "  Waiting for APIs to propagate..."
sleep 15

# Create Artifact Registry repo if it doesn't exist
gcloud artifacts repositories describe trading-agent \
    --location="$REGION" --project="$PROJECT_ID" 2>/dev/null || \
gcloud artifacts repositories create trading-agent \
    --repository-format=docker \
    --location="$REGION" \
    --project="$PROJECT_ID"

echo "  APIs enabled."

# ── Step 2: Create Secrets ──────────────────────────────────────────────────

echo "Step 2: Creating secrets in Secret Manager..."

create_secret() {
    local name=$1
    local value=$2
    if [ -z "$value" ]; then
        echo "  SKIP $name (empty)"
        return
    fi
    # Create secret if it doesn't exist, then add version
    gcloud secrets describe "$name" --project="$PROJECT_ID" 2>/dev/null || \
        gcloud secrets create "$name" --replication-policy="automatic" --project="$PROJECT_ID"
    echo -n "$value" | gcloud secrets versions add "$name" --data-file=- --project="$PROJECT_ID"
    echo "  SET $name"
}

# Source .env if available
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

create_secret "capital-api-key" "${CAPITAL_API_KEY:-}"
create_secret "capital-identifier" "${CAPITAL_IDENTIFIER:-}"
create_secret "capital-password" "${CAPITAL_PASSWORD:-}"
create_secret "alpha-vantage-key" "${ALPHA_VANTAGE_KEY:-}"
create_secret "finnhub-key" "${FINNHUB_KEY:-}"
create_secret "gemini-api-key" "${GEMINI_API_KEY:-}"
create_secret "telegram-bot-token" "${TELEGRAM_BOT_TOKEN:-}"
create_secret "telegram-chat-id" "${TELEGRAM_CHAT_ID:-}"
create_secret "github-token" "${GITHUB_TOKEN:-}"

echo "  Secrets configured."

# ── Step 3: Build and Push Container Image ──────────────────────────────────

echo "Step 3: Building container image..."
gcloud builds submit \
    --tag="${REGISTRY}/${IMAGE_NAME}:latest" \
    --project="$PROJECT_ID"
echo "  Image built and pushed."

# ── Step 4: Deploy Cloud Run Service (Bot) ──────────────────────────────────

echo "Step 4: Deploying Telegram bot service..."

# Get the compute service account
SA_EMAIL="$(gcloud iam service-accounts list \
    --filter="displayName:Compute Engine default" \
    --format="value(email)" \
    --project="$PROJECT_ID")"

# Grant Secret Manager access to the compute service account
echo "  Granting Secret Manager access..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet > /dev/null 2>&1

gcloud run deploy "$SERVICE_NAME" \
    --image="${REGISTRY}/${IMAGE_NAME}:latest" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --platform=managed \
    --allow-unauthenticated \
    --port=8080 \
    --memory=512Mi \
    --min-instances=1 \
    --max-instances=1 \
    --set-env-vars="DEPLOYMENT_MODE=cloud,TELEGRAM_MODE=webhook,CAPITAL_DEMO=true,LOG_LEVEL=INFO,GITHUB_REPO=${GITHUB_REPO:-}" \
    --set-secrets="\
CAPITAL_API_KEY=capital-api-key:latest,\
CAPITAL_IDENTIFIER=capital-identifier:latest,\
CAPITAL_PASSWORD=capital-password:latest,\
ALPHA_VANTAGE_KEY=alpha-vantage-key:latest,\
FINNHUB_KEY=finnhub-key:latest,\
GEMINI_API_KEY=gemini-api-key:latest,\
TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,\
TELEGRAM_CHAT_ID=telegram-chat-id:latest,\
GITHUB_TOKEN=github-token:latest"

# Get the service URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" --project="$PROJECT_ID" \
    --format="value(status.url)")

# Update the service with the webhook URL
gcloud run services update "$SERVICE_NAME" \
    --region="$REGION" --project="$PROJECT_ID" \
    --update-env-vars="WEBHOOK_URL=${SERVICE_URL}"

echo "  Bot deployed at: $SERVICE_URL"

# ── Step 5: Deploy Cloud Run Job (Pipeline) ─────────────────────────────────

echo "Step 5: Creating pipeline job..."
gcloud run jobs create "$JOB_NAME" \
    --image="${REGISTRY}/${IMAGE_NAME}:latest" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --memory=1Gi \
    --task-timeout=900 \
    --set-env-vars="DEPLOYMENT_MODE=cloud,RUN_MODE=pipeline,CAPITAL_DEMO=true,LOG_LEVEL=INFO,GITHUB_REPO=${GITHUB_REPO:-}" \
    --set-secrets="\
CAPITAL_API_KEY=capital-api-key:latest,\
CAPITAL_IDENTIFIER=capital-identifier:latest,\
CAPITAL_PASSWORD=capital-password:latest,\
ALPHA_VANTAGE_KEY=alpha-vantage-key:latest,\
FINNHUB_KEY=finnhub-key:latest,\
GEMINI_API_KEY=gemini-api-key:latest,\
TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,\
TELEGRAM_CHAT_ID=telegram-chat-id:latest,\
GITHUB_TOKEN=github-token:latest" \
    --args="--once,--broker,capital,--push" \
    2>/dev/null || \
gcloud run jobs update "$JOB_NAME" \
    --image="${REGISTRY}/${IMAGE_NAME}:latest" \
    --region="$REGION" --project="$PROJECT_ID" \
    --memory=1Gi \
    --task-timeout=900 \
    --set-env-vars="DEPLOYMENT_MODE=cloud,RUN_MODE=pipeline,CAPITAL_DEMO=true,LOG_LEVEL=INFO,GITHUB_REPO=${GITHUB_REPO:-}" \
    --set-secrets="\
CAPITAL_API_KEY=capital-api-key:latest,\
CAPITAL_IDENTIFIER=capital-identifier:latest,\
CAPITAL_PASSWORD=capital-password:latest,\
ALPHA_VANTAGE_KEY=alpha-vantage-key:latest,\
FINNHUB_KEY=finnhub-key:latest,\
GEMINI_API_KEY=gemini-api-key:latest,\
TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,\
TELEGRAM_CHAT_ID=telegram-chat-id:latest,\
GITHUB_TOKEN=github-token:latest" \
    --args="--once,--broker,capital,--push"

echo "  Pipeline job created."

# ── Step 5b: Deploy Cloud Run Job (Reminder) ────────────────────────────────

REMINDER_JOB_NAME="trading-agent-reminder"

echo "Step 5b: Creating reminder job..."
gcloud run jobs create "$REMINDER_JOB_NAME" \
    --image="${REGISTRY}/${IMAGE_NAME}:latest" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --memory=512Mi \
    --task-timeout=60 \
    --set-env-vars="DEPLOYMENT_MODE=cloud,RUN_MODE=pipeline,LOG_LEVEL=INFO" \
    --set-secrets="\
TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,\
TELEGRAM_CHAT_ID=telegram-chat-id:latest" \
    --args="--remind" \
    2>/dev/null || \
gcloud run jobs update "$REMINDER_JOB_NAME" \
    --image="${REGISTRY}/${IMAGE_NAME}:latest" \
    --region="$REGION" --project="$PROJECT_ID" \
    --memory=512Mi \
    --task-timeout=60 \
    --set-env-vars="DEPLOYMENT_MODE=cloud,RUN_MODE=pipeline,LOG_LEVEL=INFO" \
    --set-secrets="\
TELEGRAM_BOT_TOKEN=telegram-bot-token:latest,\
TELEGRAM_CHAT_ID=telegram-chat-id:latest" \
    --args="--remind"

echo "  Reminder job created."

# ── Step 6: Create Cloud Scheduler Jobs ─────────────────────────────────────

echo "Step 6: Setting up scheduled runs..."

# Helper to create or update a scheduler job
schedule_job() {
    local name=$1
    local cron=$2
    local tz=$3
    local description=$4

    gcloud scheduler jobs delete "$name" \
        --location="$REGION" --project="$PROJECT_ID" --quiet 2>/dev/null || true

    gcloud scheduler jobs create http "$name" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="$cron" \
        --time-zone="$tz" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
        --http-method=POST \
        --oauth-service-account-email="$SA_EMAIL" \
        --description="$description"

    echo "  Created: $name ($cron $tz)"
}

TZ="US/Eastern"

# Helper for reminder scheduler jobs (uses the reminder job)
schedule_reminder() {
    local name=$1
    local cron=$2
    local tz=$3
    local description=$4

    gcloud scheduler jobs delete "$name" \
        --location="$REGION" --project="$PROJECT_ID" --quiet 2>/dev/null || true

    gcloud scheduler jobs create http "$name" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="$cron" \
        --time-zone="$tz" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${REMINDER_JOB_NAME}:run" \
        --http-method=POST \
        --oauth-service-account-email="$SA_EMAIL" \
        --description="$description"

    echo "  Created: $name ($cron $tz)"
}

# Reminders — 30 min before each weekday pipeline run
schedule_reminder "reminder-morning" "30 8 * * 1-5" "$TZ" "Reminder: morning pipeline in 30 min"
schedule_reminder "reminder-afternoon" "30 14 * * 1-5" "$TZ" "Reminder: afternoon pipeline in 30 min"

# Weekday pipeline runs
schedule_job "pipeline-morning" "0 9 * * 1-5" "$TZ" "Morning pipeline (before US market open)"
schedule_job "pipeline-afternoon" "0 15 * * 1-5" "$TZ" "Afternoon pipeline (before US market close)"

# Crypto runs (daily — crypto never sleeps, no reminder needed)
schedule_job "pipeline-crypto-am" "0 8 * * *" "$TZ" "Crypto morning update"
schedule_job "pipeline-crypto-pm" "0 20 * * *" "$TZ" "Crypto evening update"

echo "  Scheduler configured."

# ── Step 7: Set Telegram Webhook ────────────────────────────────────────────

echo "Step 7: Setting Telegram webhook..."
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    WEBHOOK="${SERVICE_URL}/${TELEGRAM_BOT_TOKEN}"
    curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook?url=${WEBHOOK}" | python3 -m json.tool
    echo "  Webhook set."
else
    echo "  SKIP: TELEGRAM_BOT_TOKEN not set"
fi

# ── Summary ─────────────────────────────────────────────────────────────────

echo ""
echo "══════════════════════════════════════════════════"
echo "  Deployment Complete!"
echo "══════════════════════════════════════════════════"
echo ""
echo "  Bot URL:     $SERVICE_URL"
echo "  Pipeline:    gcloud run jobs execute $JOB_NAME --region=$REGION --project=$PROJECT_ID"
echo ""
echo "  Schedule (US/Eastern):"
echo "    Mon-Fri 8:30 AM  — Reminder (run locally with IBKR?)"
echo "    Mon-Fri 9:00 AM  — Morning pipeline (Capital.com)"
echo "    Mon-Fri 2:30 PM  — Reminder"
echo "    Mon-Fri 3:00 PM  — Afternoon pipeline (Capital.com)"
echo "    Daily   8:00 AM  — Crypto morning"
echo "    Daily   8:00 PM  — Crypto evening"
echo ""
echo "  Workflow:"
echo "    1. You get a Telegram reminder 30 min before each pipeline run"
echo "    2. If at your laptop with TWS open: python main.py --once --push"
echo "       (uses IBKR + Capital.com, pushes richer data to GitHub)"
echo "    3. If away: the cloud job runs automatically with Capital.com only"
echo "    4. To sync cloud data locally: git pull"
echo ""
