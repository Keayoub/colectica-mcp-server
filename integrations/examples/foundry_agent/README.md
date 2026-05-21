# Colectica ↔ Purview — Azure AI Foundry Agent

A production-ready AI agent that bridges Colectica Repository and Microsoft
Purview using the **Azure AI Projects SDK** (`azure-ai-projects`). Connects to
both MCP servers over HTTPS and executes all five integration scenarios.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Azure AI Foundry (Agent Service)                                        │
│                                                                          │
│  agent.py  ──creates──▶  AI Agent (GPT-4o)                              │
│                               │                                          │
│              ┌────────────────┼────────────────┐                        │
│              ▼                                  ▼                        │
│   MCP Tool: colectica                MCP Tool: purview                   │
│   (COLECTICA_MCP_URL)               (PURVIEW_MCP_URL)                    │
└──────────────────────────────────────────────────────────────────────────┘
```

The Azure AI Agent Service calls your MCP endpoints directly — no local
subprocess needed. This makes the agent cloud-native and fully scalable.

## Quick start (local)

```bash
pip install -r requirements.txt

export AZURE_AI_PROJECT_ENDPOINT="https://<hub>.api.azureml.ms"
export COLECTICA_MCP_URL="https://colectica-mcp.your-domain.com/mcp"
export PURVIEW_MCP_URL="https://purview-mcp.your-domain.com/mcp"

# Log in with your Azure identity
az login

# Run a scenario
python agent.py sync
python agent.py drift
python agent.py "How many QuestionItems are in Colectica but missing from Purview?"
```

## Available scenarios

| CLI arg | Scenario |
|---|---|
| `sync` | Sync Colectica QuestionItems → Purview (dry run) |
| `lineage` | Build lineage graph for a sample item |
| `drift` | Detect missing / stale / orphaned entities |
| `tags` | Sync tags Colectica → Purview classifications |
| `query` | Coverage report across both systems |
| `"<text>"` | Any free-form governance question |

## Deploy to Azure Container Apps

```bash
# Build and push image
az acr build --registry <registry> --image colectica-purview-agent:latest .

# Create Container App
az containerapp create \
  --name colectica-purview-agent \
  --resource-group <rg> \
  --image <registry>.azurecr.io/colectica-purview-agent:latest \
  --environment <env-name> \
  --env-vars \
    AZURE_AI_PROJECT_ENDPOINT="https://<hub>.api.azureml.ms" \
    COLECTICA_MCP_URL="https://colectica-mcp.your-domain.com/mcp" \
    PURVIEW_MCP_URL="https://purview-mcp.your-domain.com/mcp" \
  --mi-system-assigned
```

## Deploy directly in AI Foundry (no container)

Use the Azure AI Foundry Portal:

1. Open your AI Hub → **Agents** → **New agent**
2. Select model `gpt-4o`
3. Add **MCP tool** → enter `COLECTICA_MCP_URL`
4. Add **MCP tool** → enter `PURVIEW_MCP_URL`
5. Paste the system prompt from `agent.py` → `SYSTEM_PROMPT`
6. Save and test in the playground

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `AZURE_AI_PROJECT_ENDPOINT` | ✓ | AI Foundry project endpoint |
| `COLECTICA_MCP_URL` | ✓ | HTTPS URL of Colectica MCP server |
| `PURVIEW_MCP_URL` | ✓ | HTTPS URL of Purview MCP server |
| `AZURE_AI_MODEL` | optional | Defaults to `gpt-4o` |

## Authentication

The agent uses `DefaultAzureCredential` which automatically picks up:
- `az login` (local development)
- Managed Identity (Container Apps, ACI)
- Workload Identity (AKS)

Assign the **Azure AI User** role on the AI Hub to the identity running the agent.

## Extending with new scenarios

Add a new scenario helper function:

```python
def scenario_my_custom(client, agent):
    return run_scenario(
        client, agent,
        "Your natural-language instruction here.",
    )
```

Then add it to `SCENARIOS` dict and it becomes available as a CLI arg.
