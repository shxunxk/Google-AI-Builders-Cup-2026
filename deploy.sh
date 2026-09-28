#!/bin/bash
# Cloud Run Deployment Script for Immune City Fraud Scorer
# Usage: ./deploy.sh <PROJECT_ID> <REGION> <SERVICE_NAME>

set -e

PROJECT_ID=${1:-"your-gcp-project-id"}
REGION=${2:-"us-central1"}
SERVICE_NAME=${3:-"immune-city-scorer"}
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "=== Immune City Fraud Scorer Deployment ==="
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Service: ${SERVICE_NAME}"
echo "Image: ${IMAGE_NAME}"
echo ""

# Build and push Docker image
echo "Building Docker image..."
docker build -t ${IMAGE_NAME} .

echo "Pushing to Container Registry..."
docker push ${IMAGE_NAME}

# Deploy to Cloud Run
echo "Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
    --image=${IMAGE_NAME} \
    --platform=managed \
    --region=${REGION} \
    --allow-unauthenticated \
    --port=8080 \
    --memory=1Gi \
    --cpu=1 \
    --min-instances=0 \
    --max-instances=10 \
    --timeout=60 \
    --set-env-vars=MODEL_DIR=/app/model

echo ""
echo "=== Deployment Complete ==="
echo "Service URL: $(gcloud run services describe ${SERVICE_NAME} --platform=managed --region=${REGION} --format='value(status.url)')"