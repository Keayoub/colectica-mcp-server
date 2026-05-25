# Azure AI Foundry Agent Integration

**Framework:** Microsoft Azure AI Foundry  
**Best for:** Enterprise Azure deployments, managed services, RBAC governance

## Setup

### 1. Create AI Foundry Project

```bash
# Create project in Azure portal or via CLI
az ai foundry project create \
  --name colectica-purview-sync \
  --resource-group your-rg \
  --hub-name your-hub
```

### 2. Connect MCPs to Project

```python
from azure.ai.projects import AIProjectClient

connection_string = "..."
client = AIProjectClient.from_connection_string(connection_string)

# Register tools from MCPs
tools = [
    {
        "type": "function",
        "function": {
            "name": "colectica_search",
            "description": "Search Colectica Repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 50}
                },
                "required": ["query"]
            }
        }
    },
    # ... more tools
]
```

### 3. Create Agent

```python
agent = client.agents.create(
    name="Colectica-Purview-Sync",
    model="gpt-4o",
    instructions="""
    You are a data sync orchestrator for Colectica and Purview.
    Use the available tools to orchestrate data integration.
    """,
    tools=tools,
)
```

### 4. Execute Sync

```python
from azure.ai.projects.models import MessageRole

thread = client.agents.create_thread()
response = client.agents.create_message(
    thread_id=thread.id,
    role=MessageRole.USER,
    content="Sync all survey questions from Colectica to Purview"
)

run = client.agents.create_run(
    thread_id=thread.id,
    assistant_id=agent.id,
)

# Poll for completion
while run.status in ["queued", "in_progress"]:
    run = client.agents.get_run(thread_id, run.id)
```

### 5. Handle Tool Calls (`requires_action`)

For function tools, your runtime must execute tool calls and submit outputs back to the run.

This repo includes a bridge skeleton:

- `integrations/aifoundry/colectica_tool_bridge.py`
- `integrations/examples/aifoundry_statistician_prompt_agent_example.py`

The bridge provides:

- extraction of pending tool calls from `run.required_action`
- dispatch to an executor callback
- formatting and submission of `tool_outputs`

Default behavior is non-destructive (echoes tool calls). Replace the bridge executor with your real Colectica MCP transport (stdio or HTTP) for production.

## Advantages

- ✅ Native Azure integration
- ✅ Managed service (no servers to maintain)
- ✅ Built-in monitoring & logging
- ✅ RBAC & compliance features
- ✅ Scalable to enterprise workloads

## See Also

- [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) - All frameworks comparison
- [Azure AI Foundry Docs](https://learn.microsoft.com/azure/ai-foundry)
