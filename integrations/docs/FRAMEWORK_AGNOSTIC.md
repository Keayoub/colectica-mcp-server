# Agent Framework Integration Guide

**Key Concept:** Colectica MCP and Purview MCP are tools/capabilities that any agent framework can orchestrate.

The MCPs are **platform-independent** — they work with:
- Claude SDK (Anthropic)
- Microsoft AI Foundry Agents
- LangChain
- LlamaIndex
- Local agents (open-source LLMs)
- Custom orchestration logic

---

## Architecture (Framework-Agnostic)

```
┌─────────────────────────────────────────────────┐
│         ANY AGENT FRAMEWORK                     │
│  (Claude, Foundry, LangChain, Local LLM, etc)   │
│                                                 │
│  • Orchestrates workflows                       │
│  • Calls tools/functions                        │
│  • Maintains context & state                    │
└─────────────────────────────────────────────────┘
            ↓                          ↓
┌──────────────────────┐  ┌──────────────────────┐
│  Colectica MCP       │  │  Purview MCP         │
│  (stdio transport)   │  │  (stdio transport)   │
└──────────────────────┘  └──────────────────────┘
            ↓                          ↓
┌──────────────────────┐  ┌──────────────────────┐
│ Colectica REST API   │  │ Purview REST API     │
└──────────────────────┘  └──────────────────────┘
```

**Key Point:** MCPs expose tools via stdio. Any agent that can call external tools can orchestrate both MCPs.

---

## Platform-Specific Examples

### Option 1: GitHub Copilot CLI

**Best for:** Local testing, integrated development, command-line workflows

```bash
# Start MCPs
gh copilot mcp start colectica
gh copilot mcp start purview

# Query Colectica
gh copilot ask "Search Colectica for QuestionItem type items"

# Sync to Purview
gh copilot ask "Sync all found items to Purview with dry_run=true"
```

**Setup Required:**
- GitHub CLI (`gh`) installed
- GitHub Copilot subscription
- MCPs registered with `gh copilot mcp register`

**Example:** [AGENT_GITHUB_COPILOT_CLI.md](./AGENT_GITHUB_COPILOT_CLI.md)

---

### Option 2: Claude SDK (Anthropic)

**Best for:** Simple synchronous workflows, quick prototyping

```python
from anthropic import Anthropic

client = Anthropic()

tools = [
    {"name": "colectica_search", ...},
    {"name": "purview_bulk_import", ...},
]

response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=4096,
    tools=tools,
    messages=[...],
)

# Handle tool_use responses in a loop
```

**Provided by:** `integrations/agents/colectica_purview_agent.py`

---

### Option 3: GitHub Copilot (VS Code)

**Best for:** Integrated development, IDE-native agent, chat interface

```
Open VS Code Copilot Chat
Type: @colectica-mcp search QuestionItem
Copilot orchestrates with available MCPs
Results displayed in chat
```

**Setup Required:**
- VS Code with GitHub Copilot Chat extension
- MCPs discoverable by VS Code
- VS Code settings configured for MCP paths

**Example:** [AGENT_GITHUB_COPILOT.md](./AGENT_GITHUB_COPILOT.md)

---

### Option 4: Microsoft AI Foundry Agents

**Best for:** Enterprise, Azure-native, managed services

```python
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import ToolSet

client = AIProjectClient.from_connection_string(connection_string)

agent = client.agents.create(
    name="Colectica-Purview-Sync",
    model="gpt-4o",
    tools=[
        ToolSet(type="function", functions=[...]),
    ],
)

# Execute agent
run = client.agents.create_run(thread_id, agent.id)
```

**Setup Required:**
- Azure AI Foundry project
- Connection string
- RBAC permissions

**Example:** [AGENT_FOUNDRY.md](./AGENT_FOUNDRY.md)

---

### Option 5: LangChain

**Best for:** Multi-step workflows, custom logic, local execution

```python
from langchain.agents import initialize_agent, Tool
from langchain.llms import ChatOpenAI

tools = [
    Tool(
        name="colectica_search",
        func=colectica_search,
        description="Search Colectica items"
    ),
    Tool(
        name="purview_bulk_import",
        func=purview_bulk_import,
        description="Import to Purview"
    ),
]

llm = ChatOpenAI(model="gpt-4o")
agent = initialize_agent(
    tools,
    llm,
    agent="zero-shot-react-description",
    verbose=True
)

result = agent.run("Sync survey items from Colectica to Purview")
```

**Best Practices:**
- Define tool functions that wrap MCP calls
- Use descriptive tool descriptions
- Handle tool errors gracefully

**Example:** [AGENT_LANGCHAIN.md](./AGENT_LANGCHAIN.md)

---

### Option 6: LlamaIndex

**Best for:** RAG, document indexing, semantic search

```python
from llama_index.agent import OpenAIAgent
from llama_index.tools import FunctionTool

def colectica_search_tool(query: str) -> str:
    # Wraps MCP call
    return json.dumps(search_colectica(query))

tools = [
    FunctionTool.from_defaults(
        fn=colectica_search_tool,
        description="Search Colectica items"
    ),
]

agent = OpenAIAgent.from_tools(tools)
response = agent.chat("Find all surveys in Colectica")
```

**Example:** [AGENT_LLAMAINDEX.md](./AGENT_LLAMAINDEX.md)

---

### Option 7: Local LLM (Ollama, GGML)

**Best for:** Privacy, offline, no API costs

```python
from llama_cpp import Llama
from pydantic import BaseModel

# Load local model
llm = Llama(model_path="./models/llama-2-7b.gguf", n_gpu_layers=-1)

# Define tools as JSON schema
tools_schema = [
    {
        "name": "colectica_search",
        "description": "Search Colectica",
        "parameters": {...}
    },
]

# Implement tool execution loop manually
system_prompt = "You are a data orchestrator..."
messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": "Sync Colectica to Purview"},
]

# Call local LLM with tools
# Parse response for tool calls
# Execute tools
# Continue loop
```

**Considerations:**
- Smaller models may struggle with complex workflows
- Quantized models (q4, q5) work well on consumer hardware
- Slower than cloud APIs (5-30s per inference)

**Example:** [AGENT_LOCAL_LLM.md](./AGENT_LOCAL_LLM.md)

---

### Option 8: Custom Orchestration

**Best for:** Full control, minimal dependencies, edge cases

```python
import asyncio
from typing import Any

class CustomAgent:
    def __init__(self):
        self.mcp_colectica = MCPClient("colectica")
        self.mcp_purview = MCPClient("purview")
    
    async def sync_workflow(self):
        # Step 1: Query Colectica
        items = await self.mcp_colectica.call("search", query="...")
        
        # Step 2: Transform
        entities = self._transform_items(items)
        
        # Step 3: Validate
        for entity in entities:
            if not self._is_valid(entity):
                # Handle error
                pass
        
        # Step 4: Import to Purview
        result = await self.mcp_purview.call("bulk_import", entities=entities)
        
        # Step 5: Track
        self._update_checkpoint(result)
        
        return result
    
    def _transform_items(self, items) -> list:
        # Custom transformation logic
        return [...]
    
    def _is_valid(self, entity) -> bool:
        # Custom validation
        return True
    
    def _update_checkpoint(self, result):
        # Custom checkpoint logic
        pass
```

**Advantages:**
- No framework overhead
- Maximum flexibility
- Easy to debug

**Example:** [AGENT_CUSTOM.md](./AGENT_CUSTOM.md)

---

## Comparison Table

| Framework | Best For | Ease | Cost | Performance | Local Testing |
|---|---|---|---|---|---|
| GitHub Copilot CLI | CLI workflows | Easy | Included | Fast | ✅ Perfect |
| GitHub Copilot (VS Code) | IDE integration | Very Easy | Included | Fast | ✅ Perfect |
| Claude SDK | Prototyping | Easy | API-based | Fast | ✅ Yes |
| AI Foundry | Enterprise | Hard | Managed | Fast | ⚠️ Cloud |
| LangChain | Complex workflows | Medium | Flexible | Medium | ✅ Yes |
| LlamaIndex | RAG + agents | Medium | Flexible | Medium | ✅ Yes |
| Local LLM | Privacy/offline | Hard | Free | Slow | ✅ Yes |
| Custom | Full control | Hard | Free | Variable | ✅ Yes |

---

## Integration Checklist (Any Framework)

Regardless of which agent framework you choose:

### 1. Start MCPs
```bash
# Terminal 1
python -m colectica_mcp.server

# Terminal 2
python -m purview_mcp.server
```

### 2. Define Tool Schema

Map MCP operations to agent tool schema:
```json
{
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
```

### 3. Implement Tool Execution

Create wrapper functions that call the MCPs:
```python
def execute_tool(tool_name: str, tool_input: dict):
    if tool_name == "colectica_search":
        return call_mcp("colectica", "search", tool_input)
    elif tool_name == "purview_bulk_import":
        return call_mcp("purview", "bulk_import", tool_input)
```

### 4. Run Agent Loop

Execute agent with tool calling:
```
While agent not done:
  1. Call agent with tools schema
  2. Parse response for tool calls
  3. Execute tools
  4. Send results back to agent
  5. Repeat
```

### 5. Handle Checkpoints

Maintain sync state:
```python
checkpoint = SyncCheckpoint.from_file(".sync_checkpoint.json")
# Use checkpoint.last_synced_id to resume
checkpoint.save(".sync_checkpoint.json")
```

---

## System Prompt Template (All Frameworks)

Use this system prompt as a baseline for any agent:

```
You are a data sync orchestrator that bridges Colectica Repository and Microsoft Purview.

Your role:
1. Query Colectica MCP for survey items, variables, and metadata
2. Transform Colectica items to Purview entities
3. Manage the sync workflow between systems
4. Handle conflicts and validation
5. Track sync state for resumable operations

Available Tools:
- colectica_search: Find items in Colectica
- colectica_get_item_json_set: Get full item details
- purview_bulk_import: Import entities to Purview
- purview_search: Find entities in Purview

Type Mapping:
- QuestionItem → DataSet
- Variable → Column
- Instrument → Process

Workflow:
1. Query Colectica for items
2. Transform each to Purview entity
3. Batch into chunks (max 50)
4. Preview with dry_run=true first
5. Import with dry_run=false
6. Validate consistency
7. Update checkpoint

Guidelines:
- Always preview before actual sync
- Handle errors gracefully with retries
- Track failed items
- Use correlation_id for audit trails
- Respect API rate limits
```

---

## Next Steps

1. **Choose your framework** based on your use case
2. **Follow framework-specific guide** in integrations/docs/
3. **Implement tool execution wrapper** for your framework
4. **Test with mock MCPs** first
5. **Deploy real MCPs** when ready
6. **Monitor checkpoints** for resumable syncs

---

## Resources

- **Anthropic Claude:** https://docs.anthropic.com
- **Azure AI Foundry:** https://learn.microsoft.com/en-us/azure/ai-foundry
- **LangChain:** https://docs.langchain.com
- **LlamaIndex:** https://docs.llamaindex.ai
- **Ollama:** https://ollama.com
- **MCP Spec:** https://modelcontextprotocol.io

