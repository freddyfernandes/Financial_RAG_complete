#!/usr/bin/env bash
set -euo pipefail

# -----------------------------
# MSYS/Git-Bash on Windows fix:
# prevents '/var/jenkins_home' -> 'C:\var\jenkins_home' conversion
# (colon ':' breaks ACI mount paths)
# -----------------------------
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

# -----------------------------
# Configuration (EDIT THESE)
# -----------------------------
# Optional: set from PowerShell/GitBash before running:
#   export AZ_SUBSCRIPTION="Azure for Students"
#   export AZ_SUBSCRIPTION="78436bb7-5e74-4b30-bc93-23322eb1edaf"
AZ_SUBSCRIPTION="${AZ_SUBSCRIPTION:-}"

RESOURCE_GROUP="llmops-jenkins-rg-eu"
LOCATION="germanywestcentral"
# Allowed: ["polandcentral","swedencentral","francecentral","germanywestcentral","norwayeast"]

STORAGE_ACCOUNT="llmopsjenkinsstore${RANDOM}"
FILE_SHARE_NAME="jenkins-data"

ACR_NAME="llmopsjenkinsacr${RANDOM}"

CONTAINER_NAME="jenkins-llmops"
DNS_NAME="jenkins-llmops-${RANDOM}"

IMAGE_REPO="jenkins-python"
IMAGE_TAG="latest"

JENKINS_WEB_PORT="8080"
JENKINS_AGENT_PORT="50000"

CPU="2"
MEMORY_GB="4"

# -----------------------------
# Colors
# -----------------------------
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== Azure Jenkins Deployment Script ===${NC}\n"

# -----------------------------
# Prereqs
# -----------------------------
command -v az >/dev/null 2>&1 || { echo "Azure CLI (az) not found."; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Docker not found (required for build/push)."; exit 1; }

echo -e "${GREEN}Step 0: Azure login check...${NC}"
az account show >/dev/null 2>&1 || az login >/dev/null

# Ensure required env vars exist (we pass them as secure env vars)
: "${GROQ_API_KEY:?Set GROQ_API_KEY in your shell before running}"
: "${GOOGLE_API_KEY:?Set GOOGLE_API_KEY in your shell before running}"

# Ensure correct subscription context BEFORE reading subscription id
if [[ -n "$AZ_SUBSCRIPTION" ]]; then
  echo -e "${GREEN}Setting subscription to: ${AZ_SUBSCRIPTION}${NC}"
  az account set --subscription "$AZ_SUBSCRIPTION"
fi

SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"
echo -e "${GREEN}Active subscription:${NC} $(az account show --query name -o tsv)"
echo "Using subscription: $SUBSCRIPTION_ID (tenant: $TENANT_ID)"
echo


echo -e "${GREEN}Ensuring resource providers are registered...${NC}"
for ns in Microsoft.Storage Microsoft.ContainerRegistry Microsoft.ContainerInstance; do
  state="$(az provider show --namespace "$ns" --subscription "$SUBSCRIPTION_ID" --query registrationState -o tsv 2>/dev/null || echo NotRegistered)"
  echo "  $ns: $state"
  if [[ "$state" != "Registered" ]]; then
    az provider register --namespace "$ns" --subscription "$SUBSCRIPTION_ID" -o none
  fi
done

echo "Waiting for Microsoft.Storage to be Registered..."
for i in {1..30}; do
  s="$(az provider show --namespace Microsoft.Storage --subscription "$SUBSCRIPTION_ID" --query registrationState -o tsv)"
  echo "  Microsoft.Storage: $s"
  [[ "$s" == "Registered" ]] && break
  sleep 5
done


# -----------------------------
# Step 1: Create/ensure Resource Group
# -----------------------------
echo -e "${GREEN}Step 1: Ensuring Resource Group...${NC}"
if az group exists --name "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION_ID" | grep -qi true; then
  RG_LOC="$(az group show -n "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION_ID" --query location -o tsv)"
  echo "Resource group exists: $RESOURCE_GROUP (location=$RG_LOC). Skipping create."
else
  az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --subscription "$SUBSCRIPTION_ID" -o none
fi

# -----------------------------
# Step 2: Create Storage Account
# -----------------------------
echo -e "${GREEN}Step 2: Creating Storage Account...${NC}"
az storage account create \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --name "$STORAGE_ACCOUNT" \
  --sku Standard_LRS \
  --subscription "$SUBSCRIPTION_ID" \
  -o none

# -----------------------------
# Step 3: Get Storage Key
# -----------------------------
echo -e "${GREEN}Step 3: Getting Storage Key...${NC}"
STORAGE_KEY="$(
  az storage account keys list \
    --resource-group "$RESOURCE_GROUP" \
    --account-name "$STORAGE_ACCOUNT" \
    --subscription "$SUBSCRIPTION_ID" \
    --query '[0].value' -o tsv
)"

# -----------------------------
# Step 4: Create File Share
# -----------------------------
echo -e "${GREEN}Step 4: Creating File Share...${NC}"
az storage share create \
  --name "$FILE_SHARE_NAME" \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$STORAGE_KEY" \
  --quota 10 \
  -o none

# -----------------------------
# Step 5: Create Container Registry (ACR)
# -----------------------------
echo -e "${GREEN}Step 5: Creating Azure Container Registry...${NC}"
az acr create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$ACR_NAME" \
  --location "$LOCATION" \
  --sku Basic \
  --subscription "$SUBSCRIPTION_ID" \
  -o none

az acr update --name "$ACR_NAME" --admin-enabled true --subscription "$SUBSCRIPTION_ID" -o none

# -----------------------------
# Step 6: Get ACR Credentials
# -----------------------------
echo -e "${GREEN}Step 6: Getting ACR credentials...${NC}"
ACR_LOGIN_SERVER="$(az acr show --name "$ACR_NAME" --resource-group "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION_ID" --query loginServer -o tsv)"
ACR_USERNAME="$(az acr credential show --name "$ACR_NAME" --subscription "$SUBSCRIPTION_ID" --query username -o tsv)"
ACR_PASSWORD="$(az acr credential show --name "$ACR_NAME" --subscription "$SUBSCRIPTION_ID" --query 'passwords[0].value' -o tsv)"

# -----------------------------
# Step 7: Build and Push Image
# -----------------------------
echo -e "${GREEN}Step 7: Building and pushing Jenkins image...${NC}"
az acr login --name "$ACR_NAME" --subscription "$SUBSCRIPTION_ID" -o none

FULL_IMAGE="${ACR_LOGIN_SERVER}/${IMAGE_REPO}:${IMAGE_TAG}"

docker build --platform linux/amd64 -f Dockerfile.jenkins -t "$FULL_IMAGE" .
docker push "$FULL_IMAGE"

# -----------------------------
# Step 8: Deploy Container (ACI) + Azure Files mount
# -----------------------------
echo -e "${GREEN}Step 8: Deploying Jenkins Container...${NC}"
az container create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$CONTAINER_NAME" \
  --image "$FULL_IMAGE" \
  --os-type Linux \
  --registry-login-server "$ACR_LOGIN_SERVER" \
  --registry-username "$ACR_USERNAME" \
  --registry-password "$ACR_PASSWORD" \
  --dns-name-label "$DNS_NAME" \
  --location "$LOCATION" \
  --ip-address Public \
  --ports "$JENKINS_WEB_PORT" "$JENKINS_AGENT_PORT" \
  --cpu "$CPU" \
  --memory "$MEMORY_GB" \
  --azure-file-volume-account-name "$STORAGE_ACCOUNT" \
  --azure-file-volume-account-key "$STORAGE_KEY" \
  --azure-file-volume-share-name "$FILE_SHARE_NAME" \
  --azure-file-volume-mount-path /var/jenkins_home \
  --secure-environment-variables \
    GROQ_API_KEY="$GROQ_API_KEY" \
    GOOGLE_API_KEY="$GOOGLE_API_KEY" \
  --environment-variables \
    LLM_PROVIDER=google \
  --subscription "$SUBSCRIPTION_ID" \
  -o none

JENKINS_FQDN="$(
  az container show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CONTAINER_NAME" \
    --subscription "$SUBSCRIPTION_ID" \
    --query ipAddress.fqdn -o tsv
)"

echo -e "\n${GREEN}=== Deployment Complete ===${NC}"
echo -e "Jenkins URL: ${BLUE}http://${JENKINS_FQDN}:${JENKINS_WEB_PORT}${NC}"
echo -e "\nInitial admin password (after Jenkins boots):"
echo -e "${BLUE}az container exec --resource-group ${RESOURCE_GROUP} --name ${CONTAINER_NAME} --subscription ${SUBSCRIPTION_ID} --exec-command \"cat /var/jenkins_home/secrets/initialAdminPassword\"${NC}"
 
echo -e "\nWatch logs live:"
echo -e "${BLUE}az container logs -g ${RESOURCE_GROUP} -n ${CONTAINER_NAME} --subscription ${SUBSCRIPTION_ID} --follow${NC}"
