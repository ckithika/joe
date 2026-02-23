#!/usr/bin/env bash
# Quick deploy — rebuild image and update all Cloud Run resources.
# Usage: GCP_PROJECT=my-project ./cloud/quick-deploy.sh
set -euo pipefail

PROJECT="${GCP_PROJECT:?Set GCP_PROJECT}"
REGION="${GCP_REGION:-us-central1}"
IMAGE="gcr.io/${PROJECT}/trading-agent"

echo "=== Quick Deploy ==="
echo "Project: ${PROJECT}"
echo "Region:  ${REGION}"
echo ""

# 1. Build and push image
echo ">>> Building image..."
gcloud builds submit --project="${PROJECT}" --tag="${IMAGE}" .

# 2. Update the bot service
echo ">>> Updating trading-agent-bot service..."
gcloud run services update trading-agent-bot \
  --project="${PROJECT}" --region="${REGION}" \
  --image="${IMAGE}"

# 3. Update jobs
for JOB in trading-agent-pipeline trading-agent-monitor trading-agent-reminder; do
  echo ">>> Updating ${JOB} job..."
  gcloud run jobs update "${JOB}" \
    --project="${PROJECT}" --region="${REGION}" \
    --image="${IMAGE}"
done

echo ""
echo "=== Deploy complete ==="
