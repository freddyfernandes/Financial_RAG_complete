pipeline {
  agent any

  triggers {
    // Every 30 minutes (hashed to spread load)
    cron('* * * * *')
  }

  options {
    timestamps()
    ansiColor('xterm')
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '20'))
  }

  parameters {
    string(name: 'IMAGE_TAG', defaultValue: '', description: 'Optional: override image tag (default = BUILD_NUMBER)')
  }

  environment {
    // Python settings (from your screenshot)
    PYTHON_VERSION = '3.12'
    PYTHONPATH     = "${WORKSPACE}:${WORKSPACE}/multi_doc_chat"

    // API keys (stored as Jenkins Secret Text credentials)
    GROQ_API_KEY   = credentials('groq-api-key')
    GOOGLE_API_KEY = credentials('google-api-key')
    LLM_PROVIDER   = 'google'

    // Azure auth (stored as Jenkins credentials)
    AZURE_TENANT_ID        = credentials('azure-tenant-id')
    AZURE_SUBSCRIPTION_ID  = credentials('azure-subscription-id')
    AZURE_SP               = credentials('azure-sp') 

    // ---- Adjust these to YOUR actual Azure resources ----
    LOCATION          = 'germanywestcentral'
    APP_RESOURCE_GROUP = 'llmops-app'       // your app RG (NOT the Jenkins RG)
    CONTAINER_APP_ENV  = 'llmops-app-env'         // Container Apps Environment name
    CONTAINER_APP_NAME = 'llmops-app'             // Container App name

    // ACR (use the real one from `az acr list -o table`)
    APP_ACR_NAME      = 'llmopsjenkinsacr9163'
    IMAGE_NAME        = 'llmops-app'
    CONTAINER_PORT    = '8080'
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
      }
    }

    stage('Set Image Tag') {
      steps {
        script {
          env.EFFECTIVE_TAG = (params.IMAGE_TAG?.trim())
            ? params.IMAGE_TAG.trim()
            : env.BUILD_NUMBER
          echo "Using image tag: ${env.EFFECTIVE_TAG}"
        }
      }
    }

    stage('Unit Tests') {
      steps {
        sh '''
          set -euo pipefail
          python -V

          # Create venv in workspace to keep agent clean
          python -m venv .venv
          . .venv/bin/activate

          python -m pip install --upgrade pip
          if [ -f requirements.txt ]; then
            pip install -r requirements.txt
          fi
          pip install pytest

          pytest -q
        '''
      }
    }

    stage('Azure Login') {
      steps {
        sh '''
          set -euo pipefail

          az version

          # Login using Service Principal from Jenkins credentials
          az login --service-principal \
            -u "$AZURE_SP_USR" \
            -p "$AZURE_SP_PSW" \
            --tenant "$AZURE_TENANT_ID" \
            >/dev/null

          az account set --subscription "$AZURE_SUBSCRIPTION_ID"

          echo "Azure account:"
          az account show --query "{name:name,id:id,tenantId:tenantId}" -o json
        '''
      }
    }

    stage('Resolve ACR + Login') {
      steps {
        sh '''
          set -euo pipefail

          # Resolve ACR login server
          ACR_LOGIN_SERVER="$(az acr show -n "$APP_ACR_NAME" -g "$APP_RESOURCE_GROUP" --query loginServer -o tsv)"
          echo "ACR_LOGIN_SERVER=$ACR_LOGIN_SERVER" > acr.env

          # Admin must be enabled on ACR for credential show (or use managed identity instead)
          ACR_USERNAME="$(az acr credential show -n "$APP_ACR_NAME" --query username -o tsv)"
          ACR_PASSWORD="$(az acr credential show -n "$APP_ACR_NAME" --query passwords[0].value -o tsv)"
          echo "ACR_USERNAME=$ACR_USERNAME" >> acr.env
          echo "ACR_PASSWORD=$ACR_PASSWORD" >> acr.env

          # Log docker into ACR
          az acr login -n "$APP_ACR_NAME"
        '''
      }
    }

    stage('Build & Push Docker Image') {
      steps {
        sh '''
          set -euo pipefail
          . ./acr.env

          FULL_IMAGE="$ACR_LOGIN_SERVER/$IMAGE_NAME:$EFFECTIVE_TAG"
          echo "Building: $FULL_IMAGE"

          docker build -t "$FULL_IMAGE" .
          docker push "$FULL_IMAGE"

          echo "$FULL_IMAGE" > image.txt
        '''
      }
    }

    stage('Deploy to Azure Container Apps') {
      steps {
        sh '''
          set -euo pipefail
          . ./acr.env
          FULL_IMAGE="$(cat image.txt)"

          # Ensure RG exists
          az group create -n "$APP_RESOURCE_GROUP" -l "$LOCATION" -o none

          # Ensure Container Apps extension is available
          az extension add --name containerapp --upgrade -o none || true

          # Ensure env exists (create if missing)
          if ! az containerapp env show -n "$CONTAINER_APP_ENV" -g "$APP_RESOURCE_GROUP" >/dev/null 2>&1; then
            echo "Creating Container Apps Environment: $CONTAINER_APP_ENV"
            az containerapp env create -n "$CONTAINER_APP_ENV" -g "$APP_RESOURCE_GROUP" -l "$LOCATION" -o none
          else
            echo "Container Apps Environment exists: $CONTAINER_APP_ENV"
          fi

          # Store/update secrets in the Container App (works for both create/update flows)
          # (If app doesn't exist yet, we’ll create it first, then set secrets again if needed.)
          APP_EXISTS=0
          if az containerapp show -n "$CONTAINER_APP_NAME" -g "$APP_RESOURCE_GROUP" >/dev/null 2>&1; then
            APP_EXISTS=1
          fi

          if [ "$APP_EXISTS" -eq 0 ]; then
            echo "Creating Container App: $CONTAINER_APP_NAME"

            az containerapp create \
              -n "$CONTAINER_APP_NAME" \
              -g "$APP_RESOURCE_GROUP" \
              --environment "$CONTAINER_APP_ENV" \
              --image "$FULL_IMAGE" \
              --registry-server "$ACR_LOGIN_SERVER" \
              --registry-username "$ACR_USERNAME" \
              --registry-password "$ACR_PASSWORD" \
              --ingress external \
              --target-port "$CONTAINER_PORT" \
              --secrets groq-api-key="$GROQ_API_KEY" google-api-key="$GOOGLE_API_KEY" \
              --env-vars \
                GROQ_API_KEY=secretref:groq-api-key \
                GOOGLE_API_KEY=secretref:google-api-key \
                LLM_PROVIDER="$LLM_PROVIDER" \
              -o none
          else
            echo "Updating Container App image + env vars: $CONTAINER_APP_NAME"

            # Update secrets (in case keys changed)
            az containerapp secret set \
              -n "$CONTAINER_APP_NAME" \
              -g "$APP_RESOURCE_GROUP" \
              --secrets groq-api-key="$GROQ_API_KEY" google-api-key="$GOOGLE_API_KEY" \
              -o none

            # Update image and env vars
            az containerapp update \
              -n "$CONTAINER_APP_NAME" \
              -g "$APP_RESOURCE_GROUP" \
              --image "$FULL_IMAGE" \
              --set-env-vars \
                GROQ_API_KEY=secretref:groq-api-key \
                GOOGLE_API_KEY=secretref:google-api-key \
                LLM_PROVIDER="$LLM_PROVIDER" \
              -o none
          fi

          # Print URL
          FQDN="$(az containerapp show -n "$CONTAINER_APP_NAME" -g "$APP_RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)"
          echo "APP_URL=https://$FQDN" | tee app_url.txt
        '''
      }
    }

    stage('Show App URL') {
      steps {
        sh '''
          set -euo pipefail
          cat app_url.txt
        '''
      }
    }
  }

  post {
    always {
      echo "Pipeline finished (success or fail)."
    }
    failure {
      echo "If deploy failed, check:"
      echo "  - ACR exists and admin enabled (or switch to managed identity)"
      echo "  - Container Apps Environment exists and region is allowed"
      echo "  - Service principal has Contributor on RG + ACR pull rights"
    }
  }
}
