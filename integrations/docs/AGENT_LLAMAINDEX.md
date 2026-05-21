# LlamaIndex Agent Integration

**Framework:** LlamaIndex  
**Best for:** RAG workflows, document indexing, semantic search + agents

## Setup

### 1. Define Tools

```python
from llama_index.tools import FunctionTool
import json

def colectica_search_tool(query: str, limit: int = 50) -> str:
    """Search Colectica Repository for items."""
    # Call MCP
    result = {"items": [], "total": 0}
    return json.dumps(result)

def purview_bulk_import_tool(entities: str, dry_run: bool = True) -> str:
    """Import entities to Purview."""
    # Parse and call MCP
    entities_list = json.loads(entities)
    result = {"created": len(entities_list), "failed": 0}
    return json.dumps(result)

tools = [
    FunctionTool.from_defaults(
        fn=colectica_search_tool,
        description="Search Colectica items"
    ),
    FunctionTool.from_defaults(
        fn=purview_bulk_import_tool,
        description="Import entities to Purview"
    ),
]
```

### 2. Create Agent

```python
from llama_index.agent import OpenAIAgent
from llama_index.llm import OpenAI

llm = OpenAI(model="gpt-4o", api_key="sk-...")

agent = OpenAIAgent.from_tools(
    tools=tools,
    llm=llm,
    verbose=True,
)
```

### 3. Execute Sync

```python
response = agent.chat(
    "Find all survey questions in Colectica and preview their transformation to Purview"
)
print(response)
```

## Advantages

- ✅ Built-in RAG capabilities
- ✅ Great for semantic search
- ✅ Integrates with knowledge bases
- ✅ Clean API

## See Also

- [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) - All frameworks comparison
- [LlamaIndex Docs](https://docs.llamaindex.ai)
