# Integration Documentation

Complete guide to orchestrating Colectica MCP and Purview MCP.

## Quick Navigation

### 🎯 New Here?

**Start here:** [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) — Overview of all agent frameworks and which to choose

### 📋 Design & Architecture

| Document | Purpose |
|---|---|
| [AGENT_DEFINITION.md](./AGENT_DEFINITION.md) | Core architecture, workflows, type mapping |
| [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) | Framework comparison & selection guide |

### 🛠️ Implementation Guides

Choose your framework:

| Framework | Document | Best For |
|---|---|---|
| **Claude SDK** | [In repo: `integrations/agents/colectica_purview_agent.py`](../agents/colectica_purview_agent.py) | Quick start, prototyping |
| **AI Foundry** | [AGENT_FOUNDRY.md](./AGENT_FOUNDRY.md) | Enterprise Azure, managed services |
| **AI Foundry Prompt Agent (Statistician)** | [In repo: `integrations/aifoundry/statistician_prompt_agent.py`](../aifoundry/statistician_prompt_agent.py) | Survey metadata workflows on Colectica MCP |
| **LangChain** | [AGENT_LANGCHAIN.md](./AGENT_LANGCHAIN.md) | Complex workflows, local execution |
| **LlamaIndex** | [AGENT_LLAMAINDEX.md](./AGENT_LLAMAINDEX.md) | RAG pipelines, semantic search |
| **Local LLM** | [AGENT_LOCAL_LLM.md](./AGENT_LOCAL_LLM.md) | Privacy, offline, no API costs |
| **Custom** | [AGENT_CUSTOM.md](./AGENT_CUSTOM.md) | Full control, minimal dependencies |

### 📚 References

- **MCP Spec:** https://modelcontextprotocol.io
- **Colectica API:** https://docs.colectica.com
- **Purview API:** https://learn.microsoft.com/en-us/azure/purview

---

## Key Concepts

### Model Context Protocol (MCP)

An open standard for AI assistants to interact with tools and resources.

- **Colectica MCP** — Exposes 80+ Colectica REST API operations as tools
- **Purview MCP** — Exposes Purview management operations as tools
- **Transport:** stdio (local) or HTTP (remote)
- **Usage:** Any agent framework can call these tools

### Integration Pattern

```
Agent (Claude, Foundry, LangChain, etc.)
    ↓
Tool Execution Layer (framework-specific)
    ↓
MCP Tool Schema (framework converts to schema)
    ↓
MCP Servers (stdio transport)
    ↓
REST APIs (Colectica, Purview)
```

### Sync Workflow

1. **Query** — Agent searches Colectica for items
2. **Transform** — Agent converts Colectica items to Purview entities
3. **Validate** — Agent checks for conflicts or errors
4. **Import** — Agent syncs to Purview
5. **Track** — Agent maintains checkpoint for resumability

### Type Mapping

| Colectica | Purview | Meaning |
|---|---|---|
| QuestionItem | DataSet | Survey question → data entity |
| Variable | Column | Variable → column definition |
| Instrument | Process | Survey instrument → process |
| ResourcePackage | DataSet | Package → dataset container |

---

## Setup Checklist

### Phase 1: Prepare MCPs

- [ ] Clone both MCP repositories
- [ ] Install dependencies: `pip install fastmcp httpx mcp`
- [ ] Configure environment:
  - Colectica: `COLECTICA_BASE_URL`, auth credentials
  - Purview: `PURVIEW_ACCOUNT_NAME`, Azure credentials
- [ ] Start both MCPs (see framework guide for terminal setup)

### Phase 2: Choose Framework

- [ ] Review [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) comparison
- [ ] Select framework based on your use case
- [ ] Follow framework-specific implementation guide

### Phase 3: Implement Agent

- [ ] Define tool schemas (map MCP operations)
- [ ] Implement tool execution (call MCPs)
- [ ] Implement agent loop (iterate until done)
- [ ] Add checkpoint management (resume capability)

### Phase 4: Test & Deploy

- [ ] Test with dry_run=true first
- [ ] Validate transformed data
- [ ] Run actual sync with dry_run=false
- [ ] Monitor checkpoint file
- [ ] Production hardening (error handling, logging, monitoring)

---

## Common Questions

**Q: Can I use any agent framework?**  
A: Yes! MCPs expose tools via a standard interface. Any framework that supports tool calling (Claude, LangChain, local LLMs, etc.) can orchestrate them.

**Q: Do I need to run the MCPs locally?**  
A: For development/testing, yes. MCPs communicate via stdio. For production, you can run them on remote servers and expose via HTTP/pipes.

**Q: What if I want to use my own LLM?**  
A: You can use any LLM that supports function calling. See [AGENT_LOCAL_LLM.md](./AGENT_LOCAL_LLM.md) for examples with Ollama and GGML.

**Q: How do I handle sync failures?**  
A: Use the checkpoint file (`.sync_checkpoint.json`) to resume from the last successful item. Failed items are logged for manual review.

**Q: Can I customize the type mapping?**  
A: Yes! Edit `_transform_items()` or equivalent in your framework's agent to change how Colectica items map to Purview entities.

**Q: Do I need Purview MVP installed?**  
A: No, the Purview MCP calls the REST API. You just need a Purview account and appropriate credentials.

---

## Examples

See `integrations/examples/` for working code:

- `orchestration_example.py` — Claude SDK example
- `aifoundry_statistician_prompt_agent_example.py` — Azure AI Foundry example for the Colectica statistician prompt agent
- `aifoundry/colectica_tool_bridge.py` — tool-bridge skeleton for handling Foundry `requires_action` function calls
- More framework examples coming

---

## Support

- **Issues?** Check the framework-specific guide for troubleshooting
- **Custom workflow?** See [AGENT_CUSTOM.md](./AGENT_CUSTOM.md) for full control
- **Questions?** Review [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) comparison table

---

## Next Steps

1. Read [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md)
2. Choose your framework
3. Follow framework-specific implementation guide
4. Run the example from `integrations/examples/`
5. Customize for your use case

Happy integrating! 🚀
