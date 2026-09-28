#!/bin/bash
# Vertex AI Model Deployment Script
# Alternative to Cloud Run self-hosted model - uses Vertex AI managed endpoints
# Usage: ./deploy_vertex_ai.sh <PROJECT_ID> <REGION> <MODEL_DISPLAY_NAME>

set -e

PROJECT_ID=${1:-"your-gcp-project-id"}
REGION=${2:-"us-central1"}
MODEL_DISPLAY_NAME=${3:-"immune-city-fraud-scorer"}
ENDPOINT_DISPLAY_NAME="${MODEL_DISPLAY_NAME}-endpoint"

echo "=== Vertex AI Model Deployment ==="
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Model: ${MODEL_DISPLAY_NAME}"
echo ""

# Set project
gcloud config set project ${PROJECT_ID}

# Upload model to Vertex AI Model Registry
echo "Uploading model to Vertex AI Model Registry..."
MODEL_RESOURCE=$(gcloud ai models upload \
    --region=${REGION} \
    --display-name=${MODEL_DISPLAY_NAME} \
    --container-image-uri=us-docker.pkg.dev/vertex-ai/prediction/sklearn-cpu.1-4:latest \
    --artifact-uri=gs://${PROJECT_ID}-vertex-ai-models/${MODEL_DISPLAY_NAME} \
    --format="value(model)" 2>/dev/null || echo "")

if [ -z "${MODEL_RESOURCE}" ]; then
    echo "Model upload failed or model already exists. Checking existing models..."
    MODEL_RESOURCE=$(gcloud ai models list --region=${REGION} --filter="displayName:${MODEL_DISPLAY_NAME}" --format="value(name)" --limit=1)
fi

if [ -z "${MODEL_RESOURCE}" ]; then
    echo "Error: Could not create or find model"
    exit 1
fi

echo "Model resource: ${MODEL_RESOURCE}"

# Create endpoint
echo "Creating Vertex AI Endpoint..."
ENDPOINT_RESOURCE=$(gcloud ai endpoints create \
    --region=${REGION} \
    --display-name=${ENDPOINT_DISPLAY_NAME} \
    --format="value(name)" 2>/dev/null || echo "")

if [ -z "${ENDPOINT_RESOURCE}" ]; then
    echo "Endpoint creation failed or already exists. Checking existing endpoints..."
    ENDPOINT_RESOURCE=$(gcloud ai endpoints list --region=${REGION} --filter="displayName:${ENDPOINT_DISPLAY_NAME}" --format="value(name)" --limit=1)
fi

echo "Endpoint resource: ${ENDPOINT_RESOURCE}"

# Deploy model to endpoint
echo "Deploying model to endpoint..."
gcloud ai endpoints deploy-model ${ENDPOINT_RESOURCE} \
    --region=${REGION} \
    --model=${MODEL_RESOURCE} \
    --display-name=${MODEL_DISPLAY_NAME} \
    --machine-type=n1-standard-2 \
    --min-replica-count=0 \
    --max-replica-count=3 \
    --traffic-split=0=100

echo ""
echo "=== Vertex AI Deployment Complete ==="
echo "Endpoint: ${ENDPOINT_RESOURCE}"
echo ""
echo "To test the endpoint:"
echo "gcloud ai endpoints predict ${ENDPOINT_RESOURCE} --region=${REGION} --json-request='{\"instances\": [{\"step\": 1, \"type\": \"CASH_OUT\", \"amount\": 50000.0, \"nameOrig\": \"C123\", \"oldbalanceOrg\": 50000.0, \"newbalanceOrig\": 0.0, \"nameDest\": \"C456\", \"oldbalanceDest\": 0.0, \"newbalanceDest\": 0.0}]}'"