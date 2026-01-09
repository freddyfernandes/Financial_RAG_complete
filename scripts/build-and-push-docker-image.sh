#!/usr/bin/env bash
set -euo pipefail

########################################
# Build & Push Docker Image to Azure ACR
########################################
# -----------------------------
# Configuration
# -----------------------------

APP_ACR_NAME="${APP_ACR_NAME:-llmopsjenkinsacr25267}"
IMAGE_NAME="${IMAGE_NAME:-llmops-app}"
IMAGE_TAG="${1:-latest}"
DOCKERFILE="${DOCKERFILE:-Dockerfile}"
DOCKER_REGISTRY=""

echo
echo "============================================================"
echo "      BUILD & PUSH DOCKER IMAGE TO AZURE CONTAINER REGISTRY"
echo "============================================================"
echo

# -----------------------------
# Login to Azure Container Registry
# -----------------------------
echo "Logging in to Azure Container Registry: $APP_ACR_NAME"
az acr login --name "$APP_ACR_NAME"

# Get the full registry login server
DOCKER_REGISTRY="$(az acr show --name "$APP_ACR_NAME" --query "loginServer" -o tsv)"

if [[ -z "$DOCKER_REGISTRY" ]]; then
  echo "ERROR: Could not detect ACR registry login server!"
  exit 1
fi

echo "Registry login server: $DOCKER_REGISTRY"
echo

# -----------------------------
# Build Docker Image
# -----------------------------
echo "Building Docker image..."
echo "  Dockerfile:     $DOCKERFILE"
echo "  Image:          $DOCKER_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
docker build \
  -f "$DOCKERFILE" \
  -t "$DOCKER_REGISTRY/$IMAGE_NAME:$IMAGE_TAG" .

echo "Build complete!"
echo

# -----------------------------
# Push to ACR
# -----------------------------
echo "Pushing Docker image to registry..."
docker push "$DOCKER_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
echo "Push complete!"
echo

# -----------------------------
# Done
# -----------------------------
echo "============================================================"
echo "  IMAGE PUSHED SUCCESSFULLY!"
echo "  $DOCKER_REGISTRY/$IMAGE_NAME:$IMAGE_TAG"
echo "============================================================"
echo
