# Colectica MCP Server — Azure Deployment Plan

## Overview
Deploy Colectica MCP server to Azure Functions (Flex Consumption) with native MCP support and secure secret management via Key Vault.

## Architecture
- **Compute**: Azure Functions (Flex Consumption plan, serverless)
- **Secrets**: Azure Key Vault (bearer token, Colectica credentials)
- **Authentication**: Built-in Entra ID + access keys
- **MCP Endpoint**: `https://<function-app>.azurewebsites.net/runtime/webhooks/mcp`
- **Logging**: Application Insights + Log Analytics

## Prerequisites (User Provided)
- ✅ Azure Key Vault with secrets (COLECTICA_BEARER_TOKEN, etc.)
- ✅ Managed Identity with Key Vault read permissions (auto-created with Functions)

## Resources to Deploy

### Phase 1: Infrastructure (Bicep)
- [ ] Function App (Flex Consumption plan)
- [ ] Storage Account (functions runtime)
- [ ] Application Insights (monitoring)
- [ ] Log Analytics Workspace (logging)

### Phase 2: Application Files
- [ ] function_app.py (main MCP server logic)
- [ ] host.json (Functions configuration)
- [ ] local.settings.json (local development)

### Phase 3: azd Configuration
- [ ] azure.yaml (Functions deployment)
- [ ] infra/main.bicep (Flex Consumption resources)
- [ ] infra/main.parameters.json (configuration)

### Phase 4: User Input Required
- Key Vault name, resource group
- Managed Identity resource ID
- Entra ID app registration (optional, for OAuth)

## Deployment Command (After Setup)
```bash
azd up
```

## Configuration Options
- **Plan**: Flex Consumption (serverless, auto-scales to zero)
- **Runtime**: Python 3.11
- **MCP Endpoint**: `https://<function-app>.azurewebsites.net/runtime/webhooks/mcp`
- **Authentication**: Built-in Entra ID + access keys
- **Cost**: Pay-per-execution (lower than Container Apps minimum)

## Status
- [ ] Plan approved by user
- [ ] Infrastructure created (Functions app + storage)
- [ ] function_app.py configured
- [ ] azd configuration files generated
- [ ] Deployment successful
- [ ] MCP server running in Azure Functions
- [ ] VS Code connected to Azure MCP endpoint
