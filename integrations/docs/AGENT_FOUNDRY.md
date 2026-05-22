# Azure AI Foundry Agent Integration

**Framework:** Microsoft Azure AI Foundry (azure-ai-projects SDK)  
**Best for:** Enterprise Azure deployments, Container Apps, managed services  
**Working example:** [`integrations/examples/foundry_agent/`](../examples/foundry_agent/)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Azure AI Foundry (Agent Service)                                │
│                                                                  │
│  agent.py ──creates──▶ AI Agent (GPT-4o)                        │
│                              │                                   │
│             ┌────────────────┴────────────────┐                 │
│             ▼                                  ▼                 │
│  MCP Tool: colectica               MCP Tool: purview            │
│  (COLECTICA_MCP_URL)               (PURVIEW_MCP_URL)            │
│         │                                  │                    │
│         ▼                                  ▼                    │
│  colectica-mcp container         purview-mcp container          │
│  (streamable-http :8000)         (streamable-http :8001)        │
└──────────────────────────────────────────────────────────────────┘
```

The AI Foundry Agent Service calls your MCP endpoints over HTTPS directly —
no local subprocess, fully cloud-native, scales to production.

---

## Quick start

### 1. Start MCP servers as containers

```bash
# Both servers + agent in one command
cp .env.example .env   # fill COLECTICA_BASE_URL, PURVIEW_ENDPOINT, AI Foundry vars
docker compose up --build

# Or start Colectica MCP alone
docker run -p 8000:8000 \
  -e COLECTICA_BASE_URL=https://your-colectica.example.com \
  -e COLECTICA_BEARER_TOKEN=your-token \
  colectica-mcp-server:latest
```

### 2. Install agent dependencies

```bash
cd integrations/examples/foundry_agent
pip install -r requirements.txt
```

### 3. Configure environment

```bash
export AZURE_AI_PROJECT_ENDPOINT="https://<hub>.api.azureml.ms"
export COLECTICA_MCP_URL="http://localhost:8000/mcp"   # or your Container App URL
export PURVIEW_MCP_URL="http://localhost:8001/mcp"
export AZURE_AI_MODEL="gpt-4o"

az login   # DefaultAzureCredential picks this up automatically
```

### 4. Run a scenario

```bash
python agent.py sync           # Sync QuestionItems → Purview (dry run)
python agent.py lineage        # Build lineage for a sample item
python agent.py drift          # Detect missing / stale / orphaned entities
python agent.py tags           # Sync tags Colectica→Purview
python agent.py query          # Coverage report across both systems
python agent.py "How many Variables are missing from Purview?"
```

---

## All scenarios

| Scenario | CLI arg | What the agent does |
|---|---|---|
| Metadata sync | `sync` | Search Colectica → transform DDI items → dry-run preview → bulk import to Purview |
| Lineage propagation | `lineage` | Resolve relationship matrix → create Purview lineage edges |
| Drift detection | `drift` | Compare both systems → report missing / stale / orphaned |
| Tag governance | `tags` | Push Colectica tags as Purview classifications |
| Cross-system query | `query` | Natural-language Q&A across both MCPs |

---

## How it works — MCP tool approval flow

```python
# The agent service calls the MCP endpoint directly.
# Your code only approves the tool call:

for tool_call in action.submit_tool_outputs.tool_calls:
    if isinstance(tool_call, RequiredMcpToolCall):
        tool_outputs.append(
            ToolOutput(tool_call_id=tool_call.id, output="approved")
        )
```

The platform handles the actual HTTP call to `COLECTICA_MCP_URL` and
`PURVIEW_MCP_URL`. No subprocess management, no JSON bridging.

---

## Deploy to Azure Container Apps (production)

```bash
# 1. Build and push both MCP containers
az acr build --registry <registry> --image colectica-mcp-server:latest .
az acr build --registry <registry> \
  --image purview-mcp-server:latest ./path/to/purview-mcp

# 2. Create Container Apps
az containerapp create \
  --name colectica-mcp \
  --image <registry>.azurecr.io/colectica-mcp-server:latest \
  --env-vars \
    COLECTICA_BASE_URL=https://your-server.example.com \
    COLECTICA_MCP_TRANSPORT=streamable-http \
    COLECTICA_MCP_HOST=0.0.0.0 \
  --ingress external --target-port 8000 \
  --mi-system-assigned

# 3. Set MCP URLs in the foundry agent
COLECTICA_MCP_URL=https://colectica-mcp.<env>.azurecontainerapps.io/mcp
PURVIEW_MCP_URL=https://purview-mcp.<env>.azurecontainerapps.io/mcp
```

## Deploy directly in AI Foundry Portal (no container required)

1. Open your AI Hub → **Agents** → **New agent**
2. Select model `gpt-4o`
3. **Add tool** → **MCP** → enter `COLECTICA_MCP_URL`
4. **Add tool** → **MCP** → enter `PURVIEW_MCP_URL`
5. Paste the system prompt from `agent.py → SYSTEM_PROMPT`
6. Save and test in the playground

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `AZURE_AI_PROJECT_ENDPOINT` | ✓ | AI Foundry project endpoint |
| `COLECTICA_MCP_URL` | ✓ | HTTPS URL of Colectica MCP (`/mcp` path) |
| `PURVIEW_MCP_URL` | ✓ | HTTPS URL of Purview MCP (`/mcp` path) |
| `AZURE_AI_MODEL` | optional | Defaults to `gpt-4o` |

### Authentication

Uses `DefaultAzureCredential` — works automatically with:
- `az login` (local development)
- Managed Identity (Container Apps, ACI) — recommended for production
- Workload Identity (AKS)
- Service Principal via `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` / `AZURE_TENANT_ID`

Assign the **Azure AI User** role on the AI Hub to the identity running the agent.

---

## Advantages over stdio-based agents

| Feature | stdio agent | Container + Foundry agent |
|---|---|---|
| Remote execution | ❌ local only | ✅ fully cloud-native |
| Scale | single process | ✅ autoscale |
| Auth | env vars | ✅ Managed Identity |
| Monitoring | manual | ✅ built-in AI Foundry traces |
| Multi-tenant | ❌ | ✅ separate containers per tenant |
| CI/CD | manual | ✅ Container Apps revisions |

---

## See Also

- [Working example](../examples/foundry_agent/) — `agent.py`, `Dockerfile`, `requirements.txt`
- [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) — all frameworks comparison
- [USE_CASES.md](./USE_CASES.md) — 5 integration scenarios in detail
- [Azure AI Foundry Docs](https://learn.microsoft.com/azure/ai-foundry)
- [azure-ai-projects SDK](https://learn.microsoft.com/python/api/overview/azure/ai-projects-readme)

