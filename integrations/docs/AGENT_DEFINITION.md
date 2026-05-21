# Agent Definition - Colectica → Purview Sync

**Purpose:** Orchestrate bidirectional integration between Colectica MCP and Purview MCP.

> 📖 **Use cases:** See [USE_CASES.md](./USE_CASES.md) for five concrete integration
> scenarios — metadata sync, lineage propagation, drift detection, tag governance
> round-trip, and natural language cross-system queries.

⚠️ **Framework-Agnostic:** This pattern works with ANY agent framework. See [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) for:

- **Claude SDK** (Anthropic) — Quick start example in this repo
- **GitHub Copilot CLI** — Local CLI agent with tool use support
- **GitHub Copilot** (VS Code) — Integrated development experience
- **Microsoft AI Foundry** — Enterprise Azure integration
- **LangChain** — Complex multi-step workflows
- **LlamaIndex** — RAG + agent pipelines
- **Local LLMs** (Ollama, llama.cpp) — Privacy-first, offline
- **Custom** — Full control, minimal dependencies

**Architecture:**
```
┌──────────────────────────────────────────┐
│  Agent (Claude SDK / LangChain / etc)    │
│                                          │
│  Handles:                                │
│  • Workflow orchestration                │
│  • Type transformation                   │
│  • Conflict resolution                   │
│  • Error handling & retry logic          │
└──────────────────────────────────────────┘
         ↓                          ↓
┌──────────────────────┐  ┌──────────────────────┐
│  Colectica MCP       │  │  Purview MCP         │
│  (FastMCP)           │  │  (FastMCP)           │
│                      │  │                      │
│ • search()           │  │ • bulk_import()      │
│ • get_item()         │  │ • search()           │
│ • get_item_json_set()│  │ • manage_entities()  │
│ • call_operation()   │  │ • call_operation()   │
└──────────────────────┘  └──────────────────────┘
         ↓                          ↓
┌──────────────────────┐  ┌──────────────────────┐
│ Colectica REST APIs  │  │ Purview REST APIs    │
└──────────────────────┘  └──────────────────────┘
```

## Workflow Sequence

### Primary: Sync Colectica Items to Purview

1. **Query** — Agent calls `colectica_mcp.search()` to find items matching criteria
2. **Transform** — Agent transforms Colectica items to Purview entity format
3. **Preview** — Agent prepares batch payload (dry-run, no mutations)
4. **Validate** — Agent checks for conflicts or schema mismatches
5. **Import** — Agent calls `purview_mcp.bulk_import()` to create/update entities
6. **Track** — Agent logs sync state (timestamp, item IDs, checkpoints)

### Secondary: Validate Data Consistency

1. **Search Purview** — Verify entities were imported
2. **Compare** — Check for attribute mismatches
3. **Remediate** — Update Purview entities if needed
4. **Audit Trail** — Log all operations

## Required MCP Configurations

**Colectica MCP (local):**
```bash
COLECTICA_BASE_URL=https://your-colectica-portal.example.org
COLECTICA_BEARER_TOKEN=<token> OR COLECTICA_USERNAME=<user> COLECTICA_PASSWORD=<pass>
```

**Purview MCP (local or remote):**
```bash
PURVIEW_ACCOUNT_NAME=your-purview-account
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-service-principal-id
AZURE_CLIENT_SECRET=your-service-principal-secret
```

## Agent Capabilities

### Tool 1: Search & Preview
```
Input:
  - query: "QuestionItem with name containing 'survey'"
  - limit: 50

Output:
  - items: [{id, name, type, description}]
  - estimated_purview_entities: [{typeName, attributes}]
```

### Tool 2: Sync Items
```
Input:
  - colectica_item_ids: ["Q001", "Q002", "Q003"]
  - sync_type: "entities" | "terms" | "lineage"
  - dry_run: true

Output:
  - created: 2
  - updated: 1
  - conflicts: []
  - correlation_id: "sync_20250521_001"
```

### Tool 3: Validate Consistency
```
Input:
  - purview_entity_ids: ["dataset-Q001", "dataset-Q002"]

Output:
  - valid: true
  - mismatches: []
  - last_sync: timestamp
```

## Type Mapping Reference

| Colectica Type | Purview Type | Mapping Logic |
|---|---|---|
| QuestionItem | DataSet | Survey question as a data entity |
| Variable | Column | Survey variable as a column definition |
| VariableStatistic | Column | Statistical variable definition |
| Instrument | Process | Survey instrument as a process |
| ResourcePackage | DataSet | Package as a dataset container |
| ConceptualComponent | Process | Conceptual model component |

## Checkpoint & Resume

Agent maintains checkpoint state:
```json
{
  "last_synced_timestamp": "2025-05-21T14:30:00Z",
  "last_synced_id": "Q_final_item_id",
  "total_items_synced": 147,
  "failed_items": ["Q_broken_item"],
  "correlation_id": "sync_20250521_001"
}
```

Use checkpoint to:
- Resume interrupted syncs
- Track audit trail
- Retry failed items
- Estimate completion time

## Error Handling

**Scenarios:**
- Item not found in Colectica → Log & skip
- Transformation error → Apply defaults or manual review
- Purview API timeout → Retry with exponential backoff
- Authentication failure → Escalate to user
- Schema mismatch → Halt sync & report conflict
