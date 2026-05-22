# Colectica MCP Server — Azure Deployment Guide

## Prerequisites

Before deploying, ensure you have:

1. **Azure CLI** installed: https://docs.microsoft.com/cli/azure/install-azure-cli
2. **Azure Developer CLI (azd)** installed: https://learn.microsoft.com/azure/developer/azure-developer-cli/install-azd
3. **Docker** (for local testing): https://www.docker.com/
4. **Existing Azure resources:**
   - Azure Container Registry (ACR)
   - Azure Key Vault (with COLECTICA_BEARER_TOKEN secret)
   - Container Apps Environment
   - User-assigned Managed Identity (with Key Vault read permissions)

## Step 1: Prepare Azure Resources

### Create Resource Group
```bash
az group create -n colectica-rg -l eastus
```

### Create Container Registry (if not exists)
```bash
az acr create -n colecticaacr -g colectica-rg --sku Basic --admin-enabled true
```

### Create Key Vault (if not exists)
```bash
az keyvault create -n colectica-kv -g colectica-rg -l eastus
```

### Add COLECTICA_BEARER_TOKEN to Key Vault
```bash
az keyvault secret set --vault-name colectica-kv --name colectica-bearer-token --value "<your_bearer_token>"
```

### Create Managed Identity
```bash
az identity create -n colectica-mcp-id -g colectica-rg -l eastus
```

### Grant Managed Identity Key Vault Access
```bash
# Get Managed Identity Object ID
IDENTITY_ID=$(az identity show -n colectica-mcp-id -g colectica-rg --query principalId -o tsv)

# Grant read access to Key Vault
az keyvault set-policy --name colectica-kv --object-id $IDENTITY_ID --secret-permissions get list
```

### Create Container Apps Environment
```bash
az containerapp env create --name colectica-env --resource-group colectica-rg --location eastus
```

## Step 2: Local Testing (Optional)

Test the Docker image locally before deploying to Azure:

```bash
# Build the Docker image
docker build -t colectica-mcp:latest .

# Run locally with docker-compose
docker-compose up -d

# Verify it's running
curl http://localhost:8000/health
```

## Step 3: Build and Push to ACR

```bash
# Login to ACR
az acr login --name colecticaacr

# Build and push the image to ACR
az acr build --registry colecticaacr --image colectica-mcp:latest .

# Verify the image is in ACR
az acr repository list --name colecticaacr
```

## Step 4: Configure azd Variables

Create `.azure/.env` with your Azure resource details:

```env
AZURE_SUBSCRIPTION_ID=<your_subscription_id>
AZURE_RESOURCE_GROUP=colectica-rg
AZURE_LOCATION=eastus
ENVIRONMENT=prod

# Container App configuration
CONTAINER_IMAGE_URL=colecticaacr.azurecr.io/colectica-mcp:latest
CONTAINER_APP_ENV_ID=/subscriptions/<subscription_id>/resourceGroups/colectica-rg/providers/Microsoft.App/managedEnvironments/colectica-env
ACR_LOGIN_SERVER=colecticaacr.azurecr.io
KEY_VAULT_ID=/subscriptions/<subscription_id>/resourceGroups/colectica-rg/providers/Microsoft.KeyVault/vaults/colectica-kv
MANAGED_IDENTITY_ID=/subscriptions/<subscription_id>/resourceGroups/colectica-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/colectica-mcp-id
```

Replace placeholders with your actual Azure resource IDs.

## Step 5: Deploy with azd

```bash
# Initialize azd (one-time)
azd init -t .

# Deploy to Azure
azd up
```

## Step 6: Verify Deployment

```bash
# Get Container App details
az containerapp show -n colectica-mcp -g colectica-rg

# View logs
az containerapp logs show -n colectica-mcp -g colectica-rg --follow

# Test the container app health
CONTAINER_FQDN=$(az containerapp show -n colectica-mcp -g colectica-rg --query properties.configuration.ingress.fqdn -o tsv)
curl https://$CONTAINER_FQDN/health
```

## Step 7: Connect VS Code to Azure MCP

**Note:** Container Apps with no external ingress cannot be accessed from your local machine directly. You have two options:

### Option A: Enable External Ingress (Less Secure)
```bash
# Update Container App to allow external traffic
az containerapp update -n colectica-mcp -g colectica-rg \
  --ingress external \
  --target-port 8000
```

Then update `.vscode/mcp.json`:
```json
{
  "servers": {
    "colectica-mcp-azure": {
      "command": "curl",
      "args": ["https://$CONTAINER_FQDN/"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

### Option B: Use Azure Container Registry (Recommended for Private Setup)
Keep the container app private and use local Docker image instead:
```json
{
  "servers": {
    "colectica-mcp": {
      "command": "${workspaceFolder}/.venv/Scripts/python.exe",
      "args": ["-m", "colectica_mcp.server", "--transport", "stdio"],
      "cwd": "${workspaceFolder}"
    }
  }
}
```

## Environment Variables

The Container App receives these environment variables (automatically injected from Key Vault):

| Variable | Source | Notes |
|----------|--------|-------|
| `COLECTICA_BASE_URL` | Hardcoded in Bicep | Points to midus.colectica.org |
| `COLECTICA_BEARER_TOKEN` | Key Vault | Retrieved via managed identity |
| `PYTHONUNBUFFERED` | Hardcoded in Bicep | For real-time logging |
| `ENVIRONMENT` | `.azure/.env` | dev/staging/prod |

## Cleanup

To delete all Azure resources:

```bash
az group delete -n colectica-rg --yes
```

## Troubleshooting

### Deployment fails with "Image not found"
- Ensure the image is pushed to ACR: `az acr repository list --name colecticaacr`
- Check image URL in `.azure/.env` matches ACR image path

### Container won't start
- View logs: `az containerapp logs show -n colectica-mcp -g colectica-rg --follow`
- Check Managed Identity has Key Vault permissions

### Permission denied on Key Vault
- Verify Managed Identity has "get" and "list" permissions on secrets
- Run: `az keyvault set-policy --name colectica-kv --object-id $IDENTITY_ID --secret-permissions get list`

## Support

For issues with:
- **Azure resources**: Check [Azure Container Apps docs](https://learn.microsoft.com/azure/container-apps/)
- **azd**: See [Azure Developer CLI docs](https://learn.microsoft.com/azure/developer/azure-developer-cli/)
- **Colectica MCP**: Refer to repository README.md
