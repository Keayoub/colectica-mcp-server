# LangChain Agent Integration

**Framework:** LangChain  
**Best for:** Complex multi-step workflows, custom logic, local execution

## Setup

### 1. Define Tools

```python
from langchain.tools import Tool
import json

def colectica_search(query: str, limit: int = 50) -> str:
    """Search Colectica Repository."""
    # Call MCP here
    result = {"items": [], "total": 0}
    return json.dumps(result)

def purview_bulk_import(entities: list, dry_run: bool = True) -> str:
    """Import entities to Purview."""
    # Call MCP here
    result = {"created": len(entities), "updated": 0, "failed": 0}
    return json.dumps(result)

tools = [
    Tool(
        name="colectica_search",
        func=colectica_search,
        description="Search Colectica items by query"
    ),
    Tool(
        name="purview_bulk_import",
        func=purview_bulk_import,
        description="Bulk import entities to Purview"
    ),
]
```

### 2. Create Agent

```python
from langchain.chat_models import ChatOpenAI
from langchain.agents import initialize_agent, AgentType

llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    openai_api_key="sk-..."
)

agent = initialize_agent(
    tools=tools,
    llm=llm,
    agent=AgentType.OPENAI_FUNCTIONS,
    verbose=True,
    handle_parsing_errors=True,
)
```

### 3. Execute Sync

```python
result = agent.run(
    "Sync all QuestionItem types from Colectica to Purview with dry_run=true"
)
print(result)
```

## Advantages

- ✅ Mature library
- ✅ Support for many LLM providers
- ✅ Rich ecosystem of integrations
- ✅ Good error handling
- ✅ Easy testing & debugging

## See Also

- [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) - All frameworks comparison
- [LangChain Docs](https://docs.langchain.com)
