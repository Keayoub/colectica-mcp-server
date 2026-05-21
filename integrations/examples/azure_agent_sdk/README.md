# Azure AI Agent SDK — Colectica ↔ Purview Sync Agent

This example hosts the Colectica ↔ Purview governance agent using the
**Azure AI Projects SDK** (`azure-ai-projects`). It supports all five
integration scenarios and can run:

- **Locally** — direct Python execution
- **In AI Foundry** — deployed as an Azure AI Agent
- **In a Container** — via Azure Container Apps or any Docker host

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Azure AI Foundry project | Create at portal.azure.com → AI Foundry |
| Azure Purview account | With data catalog enabled |
| Colectica portal | With REST API and credentials |
| Python 3.10+ | |
| Docker (optional) | For container deployment |

---

## Quick start — local

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set environment variables
cp .env.example .env
# Edit .env with your values

# 3. Run a query
python agent.py "How many Colectica QuestionItems are missing from my Purview catalog?"

# 4. Sync all Variables modified this week
python agent.py "Sync all Variable type items modified in the last 7 days to Purview"
```

---

## Environment variables

Create a `.env` file (copy from `.env.example`):

```env
# Azure AI Foundry
PROJECT_CONNECTION_STRING=<your-connection-string>
AZURE_OPENAI_DEPLOYMENT=gpt-4o

# Colectica MCP
COLECTICA_BASE_URL=https://your-colectica-portal.example.org
COLECTICA_BEARER_TOKEN=your-token
# OR basic auth:
# COLECTICA_USERNAME=user
# COLECTICA_PASSWORD=pass

# Purview MCP
PURVIEW_ACCOUNT_NAME=your-purview-account
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-service-principal-client-id
AZURE_CLIENT_SECRET=your-service-principal-secret
```

Get the `PROJECT_CONNECTION_STRING` from:
Azure portal → AI Foundry → your project → **Overview** → Connection string

---

## Example prompts for each scenario

| Scenario | Example prompt |
|---|---|
| **1. Metadata sync** | `"Sync all QuestionItem types from Colectica to Purview"` |
| **2. Lineage** | `"Show me the lineage of instrument INS-001 from Colectica"` |
| **3. Drift detection** | `"What Colectica items are missing or outdated in Purview this week?"` |
| **4. Tag governance** | `"Push all Colectica tags to Purview classifications"` |
| **5. Cross-system query** | `"How many Variables in Colectica have no matching Purview entity?"` |

---

## Deploy to Azure AI Foundry (managed agent)

The agent is created fresh on each `run_agent()` call and deleted at the end.
For a persistent managed agent:

```python
# In agent.py, replace the create/delete pattern with:
agent = client.agents.create_agent(...)      # create once
# store agent.id somewhere persistent

# On each request:
agent = client.agents.get_agent(agent_id)    # reuse existing agent
```

Then deploy via Azure AI Foundry portal or CI/CD pipeline.

---

## Deploy to Azure Container Apps

```bash
# 1. Build image
docker build -t colectica-purview-agent .

# 2. Push to Azure Container Registry
az acr login --name <your-acr>
docker tag colectica-purview-agent <your-acr>.azurecr.io/colectica-purview-agent:latest
docker push <your-acr>.azurecr.io/colectica-purview-agent:latest

# 3. Create Container App
az containerapp create \
  --name colectica-purview-agent \
  --resource-group <rg> \
  --environment <env> \
  --image <your-acr>.azurecr.io/colectica-purview-agent:latest \
  --secrets \
    project-connection-string=<value> \
    colectica-base-url=<value> \
    colectica-bearer-token=<value> \
    purview-account-name=<value> \
    azure-tenant-id=<value> \
    azure-client-id=<value> \
    azure-client-secret=<value> \
  --env-vars \
    PROJECT_CONNECTION_STRING=secretref:project-connection-string \
    COLECTICA_BASE_URL=secretref:colectica-base-url \
    COLECTICA_BEARER_TOKEN=secretref:colectica-bearer-token \
    PURVIEW_ACCOUNT_NAME=secretref:purview-account-name \
    AZURE_TENANT_ID=secretref:azure-tenant-id \
    AZURE_CLIENT_ID=secretref:azure-client-id \
    AZURE_CLIENT_SECRET=secretref:azure-client-secret
```

For a **long-running service** (e.g. triggered by HTTP or a queue), wrap
`run_agent()` in a FastAPI endpoint:

```python
from fastapi import FastAPI
app = FastAPI()

@app.post("/run")
async def run(body: dict):
    message = body.get("message", "")
    run_agent(message)
    return {"status": "ok"}
```

---

## Architecture

```
Azure Container Apps / AI Foundry
  └── agent.py (Azure AI Projects SDK)
        ├── Azure AI Agent (GPT-4o) ← reasons, selects tools
        ├── MCPBridge → colectica-mcp (stdio subprocess)
        │     └── Colectica REST API
        └── MCPBridge → purview-mcp (stdio subprocess)
              └── Purview REST API
```

The MCP servers run as **subprocess children** of the agent process,
communicating over stdin/stdout (JSON-RPC 2.0).

---

## See Also

- [USE_CASES.md](../../docs/USE_CASES.md) — Integration scenarios in detail
- [AGENT_FOUNDRY.md](../../docs/AGENT_FOUNDRY.md) — AI Foundry setup guide
- [Azure AI Projects SDK docs](https://learn.microsoft.com/azure/ai-foundry/agents)
- [Colectica MCP server](../../../../README.md)
