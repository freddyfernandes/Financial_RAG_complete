pipeline {
  agent any

  parameters {
  booleanParam(name: 'RUN_DEPLOY', defaultValue: false, description: 'Deploy after tests pass')
}

  triggers {
    // Every 30 minutes
    cron('* * * * *')
  }

  environment {
    // Python settings
    PYTHON_VERSION = '3.12'
    PYTHONPATH     = "${WORKSPACE}:${WORKSPACE}/multi_doc_chat"

    // API keys (taken from Jenkins job env; keep blank if not set)
    GROQ_API_KEY   = "${env.GROQ_API_KEY ?: ''}"
    GOOGLE_API_KEY = "${env.GOOGLE_API_KEY ?: ''}"
    LLM_PROVIDER   = "${env.LLM_PROVIDER ?: 'groq'}"

    // Azure Container Apps config (EDIT THESE)
    APP_LOCATION       = 'germanywestcentral'
    APP_RESOURCE_GROUP = 'llmops-app'
    CONTAINER_APP_ENV  = 'llmops-app-env'
    CONTAINER_APP_NAME = 'llmops-app'

    // ACR (EDIT THIS)
    APP_ACR_NAME       = 'llmopsjenkinsacr9163'

    // App container config
    IMAGE_NAME      = 'llmops-app'
    CONTAINER_PORT  = '8080'
    MIN_REPLICAS    = '1'
    MAX_REPLICAS    = '3'
  }

  stages {
    stage('Checkout') {
      steps {
        echo 'Checking out code from repository...'
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

    stage('Setup Python Environment (uv + venv)') {
      steps {
        sh '''
          set -euo pipefail

          # Install uv (fast Python package manager)
          curl -LsSf https://astral.sh/uv/install.sh | sh
          UV="$HOME/.local/bin/uv"

          # Avoid Azure Files quirks by storing uv data outside Jenkins HOME
          export UV_PYTHON_INSTALL_DIR=/tmp/uv/python
          export XDG_DATA_HOME=/tmp/.local/share
          export XDG_CACHE_HOME=/tmp/.cache

          # Install the requested Python version and create a venv
          "$UV" python install "${PYTHON_VERSION}"
          "$UV" venv --python "${PYTHON_VERSION}" "/tmp/venv-${BUILD_NUMBER}"

          /tmp/venv-${BUILD_NUMBER}/bin/python --version
          "$UV" --version
        '''
      }
    }

    stage('Install Dependencies') {
      steps {
        sh '''
          set -euo pipefail
          UV="$HOME/.local/bin/uv"
          VENV_PY="/tmp/venv-${BUILD_NUMBER}/bin/python"

          export XDG_DATA_HOME=/tmp/.local/share
          export XDG_CACHE_HOME=/tmp/.cache

          # Create a sanitised requirements file removing local-only / OS-specific deps
          SAN_REQ="$(mktemp)"
          cat requirements.txt \
            | sed -E '/^[[:space:]]*llmops-series(==.*)?[[:space:]]*$/d' \
            | sed -E '/^[[:space:]]*pywin32(==.*)?[[:space:]]*$/d' \
            > "$SAN_REQ"

          "$UV" pip install --python "$VENV_PY" -r "$SAN_REQ"
          "$UV" pip install --python "$VENV_PY" pytest pytest-cov

          echo "Using PYTHONPATH=${PYTHONPATH}"
        '''
      }
    }

    stage('Run Tests') {
      steps {
        sh '''
          set -euo pipefail
          . "/tmp/venv-${BUILD_NUMBER}/bin/activate"

          mkdir -p test-reports

          pytest tests/ \
            --verbose \
            --junitxml=test-reports/junit.xml \
            --cov=multi_doc_chat \
            --cov-report=xml:test-reports/coverage.xml \
            --cov-report=term
        '''
      }
      post {
        always {
          echo 'Publishing test reports...'
          junit allowEmptyResults: true, testResults: 'test-reports/junit.xml'
          archiveArtifacts artifacts: 'test-reports/**', allowEmptyArchive: true
        }
      }
    }

    stage('Azure Login') {
      when { expression { return params.RUN_DEPLOY } }
      steps {
        echo 'Logging into Azure...'
        withCredentials([
          string(credentialsId: 'azure-client-id', variable: 'AZURE_CLIENT_ID'),
          string(credentialsId: 'azure-client-secret', variable: 'AZURE_CLIENT_SECRET'),
          string(credentialsId: 'azure-tenant-id', variable: 'AZURE_TENANT_ID'),
          string(credentialsId: 'azure-subscription-id', variable: 'AZURE_SUBSCRIPTION_ID')
        ]) {
          sh '''
            set -euo pipefail
            az version

            az login --service-principal \
              -u "$AZURE_CLIENT_ID" \
              -p "$AZURE_CLIENT_SECRET" \
              --tenant "$AZURE_TENANT_ID" >/dev/null

            az account set --subscription "$AZURE_SUBSCRIPTION_ID"
            az account show --query "{name:name,id:id,tenantId:tenantId}" -o json
          '''
        }
      }
    }

    stage('Build & Push Image to ACR (ACR Tasks)') {
  when { expression { return params.RUN_DEPLOY } }
  steps {
    sh '''
      set -euxo pipefail

      # Resolve login server (for FULL_IMAGE)
      ACR_LOGIN_SERVER="$(az acr show -n "$APP_ACR_NAME" --query loginServer -o tsv)"
      FULL_IMAGE="${ACR_LOGIN_SERVER}/${IMAGE_NAME}:${EFFECTIVE_TAG}"
      echo "Will build and push (in ACR): $FULL_IMAGE"

      # Build in Azure (no local docker required) and push to ACR
      # Uses Dockerfile in repo root; change --file if yours differs
      az acr build \
        --registry "$APP_ACR_NAME" \
        --image "${IMAGE_NAME}:${EFFECTIVE_TAG}" \
        --file Dockerfile \
        .

      echo "$FULL_IMAGE" > image.txt
    '''
  }
}


    stage('Deploy to Azure Container Apps') {
      when { expression { return params.RUN_DEPLOY } }
      steps {
        sh '''
          set -euo pipefail

          FULL_IMAGE="$(cat image.txt)"
          ACR_LOGIN_SERVER="$(az acr show -n "$APP_ACR_NAME" --query loginServer -o tsv)"
          ACR_USERNAME="$(az acr credential show -n "$APP_ACR_NAME" --query username -o tsv)"
          ACR_PASSWORD="$(az acr credential show -n "$APP_ACR_NAME" --query 'passwords[0].value' -o tsv)"

          # Ensure containerapp extension exists
          az extension add --name containerapp --upgrade -o none || true

          # Ensure RG exists
          if [ "$(az group exists -n "$APP_RESOURCE_GROUP")" != "true" ]; then
            az group create -n "$APP_RESOURCE_GROUP" -l "$APP_LOCATION" -o none
          fi

          # Ensure Container Apps environment exists
          if ! az containerapp env show -n "$CONTAINER_APP_ENV" -g "$APP_RESOURCE_GROUP" >/dev/null 2>&1; then
            echo "Creating Container Apps environment: $CONTAINER_APP_ENV"
            az containerapp env create -n "$CONTAINER_APP_ENV" -g "$APP_RESOURCE_GROUP" -l "$APP_LOCATION" -o none
          fi

          # Create or update the Container App
          if az containerapp show -n "$CONTAINER_APP_NAME" -g "$APP_RESOURCE_GROUP" >/dev/null 2>&1; then
            echo "Updating Container App image: $CONTAINER_APP_NAME"

            # Update secrets
            az containerapp secret set \
              -n "$CONTAINER_APP_NAME" -g "$APP_RESOURCE_GROUP" \
              --secrets groq-api-key="$GROQ_API_KEY" google-api-key="$GOOGLE_API_KEY" \
              -o none

            # Update image + env vars
            az containerapp update \
              -n "$CONTAINER_APP_NAME" -g "$APP_RESOURCE_GROUP" \
              --image "$FULL_IMAGE" \
              --set-env-vars \
                GROQ_API_KEY=secretref:groq-api-key \
                GOOGLE_API_KEY=secretref:google-api-key \
                LLM_PROVIDER="$LLM_PROVIDER" \
              -o none
          else
            echo "Creating Container App: $CONTAINER_APP_NAME"

            az containerapp create \
              -n "$CONTAINER_APP_NAME" -g "$APP_RESOURCE_GROUP" \
              --environment "$CONTAINER_APP_ENV" \
              --image "$FULL_IMAGE" \
              --ingress external \
              --target-port "$CONTAINER_PORT" \
              --min-replicas "$MIN_REPLICAS" \
              --max-replicas "$MAX_REPLICAS" \
              --registry-server "$ACR_LOGIN_SERVER" \
              --registry-username "$ACR_USERNAME" \
              --registry-password "$ACR_PASSWORD" \
              --secrets groq-api-key="$GROQ_API_KEY" google-api-key="$GOOGLE_API_KEY" \
              --env-vars \
                GROQ_API_KEY=secretref:groq-api-key \
                GOOGLE_API_KEY=secretref:google-api-key \
                LLM_PROVIDER="$LLM_PROVIDER" \
              -o none
          fi

          # Output URL
          FQDN="$(az containerapp show -n "$CONTAINER_APP_NAME" -g "$APP_RESOURCE_GROUP" --query "properties.configuration.ingress.fqdn" -o tsv)"
          echo "https://${FQDN}" | tee app_url.txt
        '''
      }
    }

    stage('Verify Deployment') {
      when { expression { return params.RUN_DEPLOY } }
      steps {
        sh '''
          set -euo pipefail

          APP_URL="$(cat app_url.txt)"
          echo "Application URL: $APP_URL"

          # Basic health check
          HTTP_CODE="$(curl -o /dev/null -s -w "%{http_code}\n" "$APP_URL/" || echo "000")"
          echo "HTTP status: $HTTP_CODE"

          if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "307" ]; then
            echo "Deployment verified OK."
          else
            echo "Health check failed."
            exit 1
          fi

          # Tail logs (best-effort)
          az containerapp logs show -n "$CONTAINER_APP_NAME" -g "$APP_RESOURCE_GROUP" --tail 50 || true
        '''
      }
    }
  }

  post {
    always {
      echo "Pipeline finished."
      sh '''
        set +e
        rm -rf "/tmp/venv-${BUILD_NUMBER}" 2>/dev/null || true
      '''
    }
    success {
      echo "Pipeline completed successfully."
    }
    failure {
      echo "Pipeline failed. Check console output for details."
    }
  }
}
