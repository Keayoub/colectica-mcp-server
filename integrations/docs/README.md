# Integration Documentation

Complete guide to orchestrating Colectica MCP and Purview MCP.

## Quick Navigation

### 🎯 New Here?

**Start here:** [USE_CASES.md](./USE_CASES.md) — 5 concrete integration scenarios (metadata sync, lineage, drift detection, tag governance, natural language queries)

**Then:** [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) — Overview of all agent frameworks and which to choose

### 📋 Design & Architecture

| Document | Purpose |
|---|---|
| [USE_CASES.md](./USE_CASES.md) | **Start here** — 5 concrete integration scenarios with code |
| [AGENT_DEFINITION.md](./AGENT_DEFINITION.md) | Core architecture, workflows, type mapping |
| [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) | Framework comparison & selection guide |

### 🛠️ Implementation Guides

Choose your deployment target:

| Deployment | Framework | Document | Best For |
|---|---|---|---|
| **VS Code / Copilot Chat** | GitHub Copilot Agent | `.github/agents/ColecticaPurviewAgent.md` + `.github/skills/` | Interactive governance, 5 skills built-in |
| **Azure (cloud-native)** | Azure AI Foundry SDK | [AGENT_FOUNDRY.md](./AGENT_FOUNDRY.md) + [`examples/foundry_agent/`](../examples/foundry_agent/) | Production, Container Apps, managed identity |
| **Docker / local** | docker-compose | `docker-compose.yml` + `Dockerfile` | Local dev, integration testing |
| **Prototyping** | Claude SDK | [`agents/colectica_purview_agent.py`](../agents/colectica_purview_agent.py) | Quick start, local experimentation |
| **LangChain** | LangChain | [AGENT_LANGCHAIN.md](./AGENT_LANGCHAIN.md) | Complex workflows, chains |
| **LlamaIndex** | LlamaIndex | [AGENT_LLAMAINDEX.md](./AGENT_LLAMAINDEX.md) | RAG pipelines, semantic search |
| **Local LLM** | Ollama / GGML | [AGENT_LOCAL_LLM.md](./AGENT_LOCAL_LLM.md) | Privacy, offline, no API costs |
| **Custom** | Any | [AGENT_CUSTOM.md](./AGENT_CUSTOM.md) | Full control, minimal dependencies |

### 📚 References

- **MCP Spec:** https://modelcontextprotocol.io
- **Colectica API:** https://docs.colectica.com
- **Purview API:** https://learn.microsoft.com/en-us/azure/purview
- **Azure AI Foundry:** https://learn.microsoft.com/azure/ai-foundry
- **azure-ai-projects SDK:** https://learn.microsoft.com/python/api/overview/azure/ai-projects-readme

---

## Key Concepts

### Model Context Protocol (MCP)

An open standard for AI assistants to interact with tools and resources.

- **Colectica MCP** — Exposes 80+ Colectica REST API operations as tools
- **Purview MCP** — Exposes Purview management operations as tools
- **Transport:** `stdio` (local/VS Code) or `streamable-http` (container/cloud)

### Transport modes

| Mode | When to use | How to configure |
|---|---|---|
| `stdio` | VS Code Copilot Chat, local agents | Default — no extra config |
| `streamable-http` | Docker, Azure Container Apps, AI Foundry | `COLECTICA_MCP_TRANSPORT=streamable-http` |

### Integration Pattern

```
GitHub Copilot / AI Foundry / LangChain / Claude
    ↓
MCP tool calls (stdio or HTTPS)
    ↓
Colectica MCP Server   ←→   Purview MCP Server
    ↓                              ↓
Colectica REST API          Purview REST API
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
| VariableStatistic | Column | Statistical variable definition |
| Instrument | Process | Survey instrument → process |
| ResourcePackage | DataSet | Package → dataset container |
| ConceptualComponent | Process | Conceptual model component |

---

## Setup Checklist

### Phase 1: Prepare MCPs

- [ ] Clone this repo + Purview MCP repo
- [ ] Configure `.env` from `.env.example`:
  - `COLECTICA_BASE_URL`, auth credentials
  - `PURVIEW_ENDPOINT`, Azure credentials
  - `AZURE_AI_PROJECT_ENDPOINT` (if using AI Foundry)

### Phase 2: Choose deployment target

**Local / VS Code:**
```bash
# stdio mode (default) — works with Copilot Chat automatically
colectica-mcp --transport stdio
```

**Container / Cloud:**
```bash
docker compose up --build
# colectica-mcp → http://localhost:8000/mcp
# purview-mcp   → http://localhost:8001/mcp
```

### Phase 3: Choose agent framework

- VS Code → use `.github/agents/ColecticaPurviewAgent.md`
- Azure production → use `integrations/examples/foundry_agent/`
- Prototyping → use `integrations/agents/colectica_purview_agent.py`
- Custom → follow [AGENT_CUSTOM.md](./AGENT_CUSTOM.md)

### Phase 4: Test & Deploy

- [ ] Test with `dry_run=true` first
- [ ] Validate transformed data
- [ ] Run actual sync with `dry_run=false`
- [ ] Monitor checkpoint file
- [ ] Production hardening (error handling, logging, monitoring)

---

## GitHub Copilot Agent — 5 Skills

The `.github/agents/ColecticaPurviewAgent.md` agent activates with
`@ColecticaPurviewAgent` in VS Code Copilot Chat and provides five skills:

| Skill file | Scenario | Example prompt |
|---|---|---|
| `sync-metadata.md` | Sync items → Purview | "Sync all QuestionItems to Purview" |
| `lineage-propagation.md` | Build lineage | "Register lineage for instrument INS-2025" |
| `drift-detection.md` | Detect drift | "Which items are missing from Purview?" |
| `tag-governance.md` | Sync tags | "Push all Colectica tags to Purview classifications" |
| `cross-system-query.md` | Q&A | "How many Variables are in Colectica vs Purview?" |

Each skill file contains step-by-step execution instructions, tool call
sequences, error handling rules, and example prompts.

---

## Azure AI Foundry Agent — Pre-built Scenarios

The `integrations/examples/foundry_agent/agent.py` provides ready-to-run
scenarios using the `azure-ai-projects` SDK with native MCP tool support:

```bash
python agent.py sync      # Sync QuestionItems → Purview (dry run)
python agent.py lineage   # Build lineage for a sample item
python agent.py drift     # Detect missing / stale / orphaned entities
python agent.py tags      # Sync tags Colectica → Purview
python agent.py query     # Coverage report across both systems
python agent.py "your question here"
```

The agent connects to your MCP servers over HTTPS — deploy them as containers
using the included `Dockerfile` and `docker-compose.yml`.

---

## Common Questions

**Q: Can I use any agent framework?**  
A: Yes. MCPs expose tools via a standard interface. Any framework that supports
tool calling can orchestrate them.

**Q: Do I need to run the MCPs locally?**  
A: For VS Code / stdio, yes (automatic via Copilot). For AI Foundry or any
cloud agent, run them as containers and point to the HTTPS endpoint.

**Q: What transport should I use?**  
A: `stdio` for local/VS Code. `streamable-http` for containers and cloud agents.
Both transports are built into the server — switch via `COLECTICA_MCP_TRANSPORT`.

**Q: What if I want to use my own LLM?**  
A: See [AGENT_LOCAL_LLM.md](./AGENT_LOCAL_LLM.md) for examples with Ollama.

**Q: How do I handle sync failures?**  
A: Use the checkpoint file (`.sync_checkpoint.json`) to resume from the last
successful item. Failed items are logged for manual review.

**Q: Can I customize the type mapping?**  
A: Yes. Edit `_transform_items()` or the system prompt type mapping table.

---

## Examples directory

| Path | Description |
|---|---|
| `integrations/agents/colectica_purview_agent.py` | Claude SDK agent (prototyping) |
| `integrations/examples/foundry_agent/agent.py` | Azure AI Foundry agent (production) |
| `integrations/examples/foundry_agent/Dockerfile` | Container image for the agent |
| `Dockerfile` | Container image for Colectica MCP server |
| `docker-compose.yml` | Full local stack (both MCPs + agent) |

---

## Support

- **Issues?** Check the framework-specific guide for troubleshooting
- **Custom workflow?** See [AGENT_CUSTOM.md](./AGENT_CUSTOM.md) for full control
- **Questions?** Review [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md)

Happy integrating! 🚀
