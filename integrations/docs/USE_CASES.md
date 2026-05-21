# Integration Use Cases — Colectica MCP + Purview MCP

This document describes the five primary integration scenarios enabled by
combining Colectica MCP and Purview MCP. Each scenario lists the goal, the
relevant MCP tools, the workflow steps, a minimal code sketch, and an example
agent prompt you can use right now with GitHub Copilot or Claude.

---

## Type Mapping Reference

All scenarios share the same DDI → Purview type mapping:

| Colectica Type | Purview Type | Meaning |
|---|---|---|
| `QuestionItem` | `DataSet` | Survey question as a data entity |
| `Variable` | `Column` | Survey variable as a column definition |
| `VariableStatistic` | `Column` | Statistical variable definition |
| `Instrument` | `Process` | Survey instrument as a process |
| `ResourcePackage` | `DataSet` | Package as a dataset container |
| `ConceptualComponent` | `Process` | Conceptual model component |

---

## Scenario 1 — Sync Colectica Metadata → Purview Catalog

**Goal:** Make Colectica survey items discoverable inside the Microsoft Purview
data catalog so data stewards have a single place to govern survey metadata.

### When to use

- Initial bulk import of your survey item library into Purview
- Incremental sync after Colectica items are updated or new versions published
- Keeping the Purview catalog current without manual data entry

### MCP tools used

| Step | MCP | Tool |
|---|---|---|
| Find items | Colectica | `search`, `search_advanced` |
| Fetch full graph | Colectica | `get_item_json_set`, `get_item_json_set_filtered` |
| Import entities | Purview | `bulk_import` (or equivalent) |
| Verify import | Purview | `search` |

### Workflow

```
1. Agent calls colectica.search(query, limit)
2. For each result, agent calls colectica.get_item_json_set(agency, id)
3. Agent transforms each item to a Purview entity (see type mapping above)
4. Agent batches entities (≤50 per call) and calls purview.bulk_import(dry_run=true)
5. Agent reviews preview output, confirms no conflicts
6. Agent calls purview.bulk_import(dry_run=false) to commit
7. Agent calls purview.search to verify imported entities exist
8. Agent saves checkpoint for resumability
```

### Code sketch

```python
async def sync_to_purview(query: str, dry_run: bool = True):
    # 1. Search Colectica
    results = await colectica.search({"body": {"searchText": query, "maxResults": 50}})

    entities = []
    for item in results.get("Results", []):
        # 2. Fetch full item graph
        full = await colectica.get_item_json_set(
            agency=item["Agency"],
            identifier=item["Identifier"],
        )
        # 3. Transform
        entities.append({
            "typeName": TYPE_MAP.get(item["ItemType"], "Asset"),
            "attributes": {
                "qualifiedName": f"colectica://{item['Agency']}/{item['Identifier']}",
                "name": item.get("Label", item["Identifier"]),
                "description": item.get("Description", ""),
                "sourceId": item["Identifier"],
                "sourceSystem": "Colectica",
            },
        })

    # 4–6. Import in batches
    for batch in chunks(entities, 50):
        await purview.bulk_import(entities=batch, dry_run=dry_run)
```

### Resumability

Save a checkpoint after each batch:

```json
{
  "last_synced_timestamp": "2026-05-21T19:00:00Z",
  "last_synced_id": "last-identifier-in-batch",
  "total_items_synced": 147,
  "failed_items": []
}
```

### Sample agent prompt

```
Search Colectica for all QuestionItem and Variable types in agency "int.example",
transform each to the matching Purview entity type, preview the import with
dry_run=true, then execute and save a checkpoint.
```

---

## Scenario 2 — Data Lineage Propagation

**Goal:** Register how survey items relate to each other in Purview's lineage
graph so analysts can trace the origin and transformation of each variable.

### When to use

- Compliance requirements mandate lineage tracking
- Data stewards need to trace variable provenance from instrument to dataset
- Impact analysis: "which datasets are affected if I change this variable?"

### MCP tools used

| Step | MCP | Tool |
|---|---|---|
| Discover relationships | Colectica | `search_relationships_by_subject` |
| Get reference graph | Colectica | `get_relationship_matrix`, `get_relationship_matrix_typed` |
| Reverse lookup | Colectica | `search_relationships_by_object` |
| Register lineage | Purview | lineage/process entity write |

### Workflow

```
1. Agent picks a root item (e.g. an Instrument)
2. Agent calls colectica.get_relationship_matrix({items: [root]})
   → returns all items in the set and edges between them
3. Agent maps each edge to a Purview lineage relationship
   (source entity → process entity → target entity)
4. Agent registers process entities in Purview for each transformation step
5. Agent links source and target column/dataset entities through the process
6. Lineage is now visible in Purview Data Map
```

### Code sketch

```python
async def propagate_lineage(agency: str, root_id: str):
    # 1. Get relationship matrix for the instrument
    matrix = await colectica.get_relationship_matrix({
        "body": {
            "Items": [{"Agency": agency, "Identifier": root_id}]
        }
    })

    for edge in matrix.get("Edges", []):
        source_urn = f"colectica://{edge['SourceAgency']}/{edge['SourceIdentifier']}"
        target_urn = f"colectica://{edge['TargetAgency']}/{edge['TargetIdentifier']}"

        # 2. Register lineage in Purview
        await purview.create_lineage(
            source_qualified_name=source_urn,
            target_qualified_name=target_urn,
            process_name=f"colectica-relationship-{edge['RelationshipType']}",
        )
```

### Sample agent prompt

```
For Instrument "my-instrument-id" in agency "int.example", fetch the full
relationship matrix and register lineage edges in Purview showing how
Variables flow from the Instrument to each DataSet.
```

---

## Scenario 3 — Consistency Validation / Drift Detection

**Goal:** Detect metadata drift — items that exist in Colectica but are
missing or outdated in Purview — and report or remediate automatically.

### When to use

- Scheduled governance audit (daily/weekly)
- Post-release validation after a Colectica batch update
- Incident response: "Purview shows data that no longer exists in Colectica"

### Drift classification

| Status | Meaning | Recommended action |
|---|---|---|
| `in-sync` | Purview matches Colectica | None |
| `stale` | Purview exists but attributes differ | Update Purview entity |
| `missing` | In Colectica, not in Purview | Import to Purview (Scenario 1) |
| `orphan` | In Purview, not in Colectica | Flag for review or delete |

### MCP tools used

| Step | MCP | Tool |
|---|---|---|
| List Colectica items | Colectica | `search`, `get_item_versions`, `get_item_latest_version` |
| Check Purview state | Purview | `search` (by `sourceId` attribute) |
| Update stale entities | Purview | `bulk_import` (upsert) |

### Workflow

```
1. Agent queries Colectica for all items modified since last checkpoint timestamp
2. For each item, agent checks if a matching Purview entity exists
   (match by sourceId = Colectica identifier)
3. If missing → add to "needs import" list
4. If present → compare key attributes (name, description, version)
   → if attributes differ → add to "needs update" list
5. Agent reports the drift summary (counts + item IDs)
6. Agent optionally auto-remediates by syncing the delta (Scenario 1 workflow)
7. Agent saves new checkpoint timestamp
```

### Code sketch

```python
async def detect_drift(since_timestamp: str):
    missing, stale = [], []

    # 1. Items modified since last sync
    results = await colectica.search_advanced({
        "body": {"searchText": "*", "modifiedAfter": since_timestamp}
    })

    for item in results.get("Results", []):
        qname = f"colectica://{item['Agency']}/{item['Identifier']}"

        # 2. Check Purview
        purview_hit = await purview.search({"query": qname})
        if not purview_hit.get("value"):
            missing.append(item)
        else:
            purview_entity = purview_hit["value"][0]
            if purview_entity.get("name") != item.get("Label"):
                stale.append(item)

    return {"missing": len(missing), "stale": len(stale),
            "missing_items": missing, "stale_items": stale}
```

### Sample agent prompt

```
Find all Colectica items modified since 2026-05-01, check each against
Purview for drift, produce a report grouped by status (in-sync / stale /
missing / orphan), and auto-update stale Purview entities.
```

---

## Scenario 4 — Tag Governance Round-trip

**Goal:** Keep classification/tagging consistent across both systems.
Purview classifications can flow back to Colectica as tags, and Colectica
tags can be published to Purview as glossary terms or classifications.

### MCP tools used

| Direction | MCP | Tool |
|---|---|---|
| Read Colectica tags | Colectica | `get_tags` |
| Write Colectica tags | Colectica | `add_tag`, `remove_tag` |
| Read Purview classifications | Purview | `get_entity_classifications` |
| Write Purview classifications | Purview | `add_classification` |

### Workflow — Colectica → Purview (push tags as glossary terms)

```
1. For each Colectica item, agent calls colectica.get_tags(agency, id, version)
2. Agent maps each tag to a Purview glossary term or classification name
3. Agent calls purview.add_classification(entity_id, classification_name)
```

### Workflow — Purview → Colectica (pull classifications back as tags)

```
1. Agent queries Purview for entities with a specific classification
   (e.g. "PII", "Confidential", "Approved")
2. Agent maps each Purview entity back to its Colectica sourceId
3. Agent calls colectica.add_tag(agency, id, version, tag)
4. Colectica items are now tagged to match Purview governance decisions
```

### Code sketch

```python
async def push_purview_classifications_to_colectica(classification: str):
    # 1. Find all Purview entities with this classification
    entities = await purview.search({"query": f"classification:{classification}"})

    for entity in entities.get("value", []):
        source_id = entity.get("attributes", {}).get("sourceId")
        agency = entity.get("attributes", {}).get("sourceAgency")
        if not source_id or not agency:
            continue

        # 2. Get latest version
        version_info = await colectica.get_item_latest_version(agency, source_id)
        version = version_info.get("Version", 1)

        # 3. Apply tag in Colectica
        await colectica.add_tag(agency, source_id, version, classification.lower())
```

---

## Scenario 5 — Natural Language Cross-System Queries

**Goal:** Let an AI agent answer governance questions that require data from
both systems without the user knowing which system holds which data.

### Example questions an agent can answer

| Question | Tools required |
|---|---|
| "How many Variables in Colectica are not yet in Purview?" | `colectica.search` + `purview.search` |
| "Show me all Instruments modified since last month." | `colectica.search_advanced` |
| "Which items have the tag 'approved' in Colectica but no matching Purview entity?" | `colectica.search` + `colectica.get_tags` + `purview.search` |
| "Sync everything that changed this week." | `colectica.search_advanced` + Scenario 1 workflow |
| "What is the lineage of Variable Q047?" | `colectica.search_relationships_by_subject` + `colectica.get_relationship_matrix` |

### How to enable with GitHub Copilot CLI (simplest)

Add both MCPs to your VS Code MCP config (`settings.json`):

```json
{
  "mcp": {
    "servers": {
      "colectica": {
        "command": "colectica-mcp",
        "args": ["--transport", "stdio"],
        "env": {
          "COLECTICA_BASE_URL": "https://your-colectica-portal",
          "COLECTICA_BEARER_TOKEN": "your-token"
        }
      },
      "purview": {
        "command": "purview-mcp",
        "args": ["--transport", "stdio"],
        "env": {
          "PURVIEW_ACCOUNT_NAME": "your-account",
          "AZURE_TENANT_ID": "your-tenant"
        }
      }
    }
  }
}
```

Then ask naturally in Copilot Chat:

```
How many Colectica QuestionItems are missing from my Purview catalog?
```

Copilot will automatically call the right tools from both MCPs, combine the
results, and give you a direct answer.

### How to enable with Claude SDK

See `integrations/agents/colectica_purview_agent.py` for a working
implementation. The key is registering both MCP servers as tool sources and
letting the agent decide which tool to call for each step.

---

## Choosing a Scenario

| If you want to… | Start with |
|---|---|
| Populate Purview with existing Colectica metadata | Scenario 1 |
| Show how survey data flows through your systems | Scenario 2 |
| Run a nightly governance check | Scenario 3 |
| Keep tags/classifications in sync across both systems | Scenario 4 |
| Ask questions across both systems in plain language | Scenario 5 |
| Do all of the above in one agent | Combine Scenarios 1–5 with a checkpoint loop |

---

## See Also

- [AGENT_DEFINITION.md](./AGENT_DEFINITION.md) — Core architecture and type mapping
- [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) — Which agent framework to use
- [AGENT_CUSTOM.md](./AGENT_CUSTOM.md) — Full-control Python implementation
- [AGENT_FOUNDRY.md](./AGENT_FOUNDRY.md) — Azure enterprise deployment
- [README.md](./README.md) — Quick navigation
