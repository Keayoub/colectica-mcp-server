# Colectica MCP Server

MCP server for Colectica Repository REST API with:

- OpenAPI/Swagger discovery
- operation invocation by OpenAPI operationId or synthesized id (`METHOD_path_segments`)
- Basic Auth and Bearer Token support
- stdio transport now, optional streamable-http transport switch

## 1. Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## 2. Configure

Copy `.env.example` to `.env` and set values:

- `COLECTICA_BASE_URL` (your Colectica Portal URL)
- either `COLECTICA_BEARER_TOKEN` or `COLECTICA_USERNAME` + `COLECTICA_PASSWORD` (or both)

Optional:

- `COLECTICA_OPENAPI_CACHE_TTL_SECONDS` (default `300`; set `0` to disable cache)
- `COLECTICA_RETRY_MAX_RETRIES` (default `2`)
- `COLECTICA_RETRY_BASE_SECONDS` (default `0.5`)
- `COLECTICA_RETRY_MAX_SECONDS` (default `8`)

## 3. Run MCP server

### stdio (default)

```powershell
colectica-mcp --transport stdio
```

### streamable-http (optional)

```powershell
colectica-mcp --transport streamable-http --mount-path /mcp
colectica-mcp --transport streamable-http --host 0.0.0.0 --port 9000 --mount-path /mcp
```

Environment variables: `COLECTICA_MCP_HOST` (default `127.0.0.1`), `COLECTICA_MCP_PORT` (default `8000`).

## 4. Available MCP tools

### Discovery and generic invocation

- `health_check(auth_mode="auto")`
- `list_operations(auth_mode="auto")`
- `find_operations(query, auth_mode="auto", limit=50)`
- `find_ddi_operations(auth_mode="auto", limit=50)`
- `call_operation(operation_id, arguments, auth_mode="auto")`
- `call_endpoint(method, path, arguments, auth_mode="auto")`
- `operation_details(operation_id, auth_mode="auto")`
- `call_operation_paginated(operation_id, arguments, auth_mode="auto", max_pages=20, items_path=None)`
- `list_operation_categories(auth_mode="auto")`
- `list_operations_by_category(category, auth_mode="auto", limit=200)`

### Repository

- `get_repository_info(auth_mode="auto")`
- `get_repository_statistics(auth_mode="auto")`

### Items

- `get_item(arguments, auth_mode="auto")`
- `get_item_by_urn(urn, auth_mode="auto")`
- `register_item(arguments, auth_mode="auto")`
- `register_item_body(body, auth_mode="auto")`
- `get_items_list(body, auth_mode="auto")`
- `get_items_list_latest(body, auth_mode="auto")`
- `get_item_descriptions(body, auth_mode="auto")`
- `get_item_description(agency, id, version, auth_mode="auto")`
- `delete_items(body, auth_mode="auto")`
- `update_item_state(body, auth_mode="auto")`

### Item versions and history

- `get_item_versions(agency, id, auth_mode="auto")`
- `get_item_latest_version(agency, id, auth_mode="auto")`
- `get_item_latest_version_by_tag(agency, id, tag, auth_mode="auto")`
- `get_latest_version_numbers(body, auth_mode="auto")`
- `get_item_history(agency, id, auth_mode="auto")`

### DDI and JSON serialization

- `get_ddi_fragment(agency, identifier, version=None, auth_mode="auto")`
- `get_ddi_set_fragment(agency, identifier, version=None, auth_mode="auto")`
- `get_item_json(agency, identifier, version=None, auth_mode="auto")`
- `get_item_json_set(agency, identifier, version=None, auth_mode="auto")`
- `get_item_json_set_filtered(body, auth_mode="auto")`

### Search and query

- `search(arguments, auth_mode="auto")`
- `search_advanced(body, auth_mode="auto")`
- `search_set(body, auth_mode="auto")`
- `search_relationships_by_subject(body, auth_mode="auto")`
- `search_relationships_by_subject_descriptions(body, auth_mode="auto")`
- `search_relationships_by_object(body, auth_mode="auto")`
- `search_relationships_by_object_descriptions(body, auth_mode="auto")`
- `get_relationship_matrix(body, auth_mode="auto")`
- `get_relationship_matrix_typed(body, auth_mode="auto")`

### Item sets

- `get_item_set(agency, id, version=None, auth_mode="auto")`
- `get_item_set_versioned(agency, id, version, auth_mode="auto")`
- `get_item_set_typed(agency, id, version, auth_mode="auto")`

### Tags and ratings

- `get_tags(agency, id, version, auth_mode="auto")`
- `add_tag(agency, id, version, tag, auth_mode="auto")`
- `remove_tag(agency, id, version, tag, auth_mode="auto")`
- `get_ratings(agency, id, version, auth_mode="auto")`
- `add_rating(agency, id, version, rating, auth_mode="auto")`

### Comments

- `get_item_comments(agency, id, auth_mode="auto")`
- `add_item_comment(agency, id, version, body, auth_mode="auto")`
- `get_comment_list(body, auth_mode="auto")`

### Transactions

- `create_transaction(auth_mode="auto")`
- `get_transactions(body, auth_mode="auto")`
- `list_transactions(body, auth_mode="auto")`
- `commit_transaction(body, auth_mode="auto")`
- `cancel_transaction(body, auth_mode="auto")`
- `add_items_to_transaction(body, auth_mode="auto")`
- `get_items_in_transaction(transaction_id, auth_mode="auto")`

### Settings

- `get_settings(auth_mode="auto")`
- `get_setting(setting, auth_mode="auto")`
- `set_setting(body, auth_mode="auto")`
- `delete_setting(setting, auth_mode="auto")`

### Agency

- `create_agency(body, auth_mode="auto")`
- `delete_agency(agency, auth_mode="auto")`

### Permissions

- `add_permissions(body, auth_mode="auto")`
- `delete_permissions(body, auth_mode="auto")`
- `get_permissions(body, auth_mode="auto")`

### Events

- `publish_event(body, auth_mode="auto")`

### Tokens

- `create_token(body, auth_mode="auto")`
- `create_windows_token(auth_mode="auto")`

### Replication

- `get_replication_targets(auth_mode="auto")`
- `create_replication(body, auth_mode="auto")`
- `get_replication_allowed_initial_states(body, auth_mode="auto")`
- `get_replication_allowed_transitions(body, auth_mode="auto")`
- `request_replication_state_change(body, auth_mode="auto")`

## 5. Recommended usage flow

1. `health_check`
2. `list_operations`
3. `list_operation_categories` to see API groups (Agency, Comment, Ddi, Event, Item, Permission, Query, Rating, Replication, Repository, Set, Setting, Tag, Token, Transaction, VersionNumber)
4. `list_operations_by_category` to narrow to one group
5. `call_operation` using operationId and arguments from your Swagger schema

For request bodies, pass `arguments.body`.

If you prefer to execute directly from HTTP route + verb, use `call_endpoint(method, path, arguments, auth_mode)`.

If your OpenAPI spec does not provide operationId values, use synthesized ids in this format:

- `METHOD_<normalized_path>`
- Example: `GET /api/v1/ddi/{agency}/{identifier}` -> `GET_api_v1_ddi_agency_identifier`

Optional for non-JSON operations:

- `arguments.content_type` (for example `application/x-www-form-urlencoded` or `multipart/form-data`)

Use `operation_details` to inspect supported parameters and request body content types before invoking.
For paged endpoints, use `call_operation_paginated` to aggregate items across pages. The server will follow continuation tokens when available, including body tokens like `nextResult` for query endpoints.

## 6. DDI integration workflow

Use this sequence to integrate with DDI-focused Colectica endpoints:

1. Call convenience wrappers directly: `get_ddi_fragment`, `get_ddi_set_fragment`, `get_item_json`, `get_item_json_set`.
2. Use `get_item_json_set_filtered` for selective graph traversal.
3. For advanced/non-wrapped routes, run `find_ddi_operations` and confirm with `operation_details(operation_id)`.
4. Execute custom integration calls via `call_operation` using typed `arguments` and `arguments.body`.
5. For large result sets, switch to `call_operation_paginated`.

## 7. Container deployment (streamable-http)

The MCP server can run as a standalone HTTP service — useful for cloud
deployments, multi-agent setups, and connecting to Azure AI Foundry.

### Run with Docker

```bash
# Build image
docker build -t colectica-mcp-server:latest .

# Run as HTTP server
docker run -p 8000:8000 \
  -e COLECTICA_BASE_URL=https://your-server.example.com \
  -e COLECTICA_BEARER_TOKEN=your-token \
  colectica-mcp-server:latest
# → MCP endpoint: http://localhost:8000/mcp
```

### Run full stack (Colectica MCP + Purview MCP + AI Agent)

```bash
cp .env.example .env   # fill in your values
docker compose up --build
```

Services started:
- `colectica-mcp` → `http://localhost:8000/mcp`
- `purview-mcp`   → `http://localhost:8001/mcp`
- `foundry-agent` → one-shot AI agent (waits for both MCPs to be healthy)

### Deploy to Azure Container Apps

```bash
az acr build --registry <registry> --image colectica-mcp-server:latest .

az containerapp create \
  --name colectica-mcp \
  --image <registry>.azurecr.io/colectica-mcp-server:latest \
  --env-vars \
    COLECTICA_BASE_URL=https://your-server.example.com \
    COLECTICA_BEARER_TOKEN=secretref:colectica-token \
    COLECTICA_MCP_TRANSPORT=streamable-http \
    COLECTICA_MCP_HOST=0.0.0.0 \
  --ingress external --target-port 8000 \
  --mi-system-assigned
```

---

## 8. AI Agent integrations (Colectica + Purview)

The `integrations/` folder contains agents and code samples that combine
**Colectica MCP** and **Purview MCP** to automate data governance workflows.

### GitHub Copilot Agent (VS Code)

Activate `@ColecticaPurviewAgent` in Copilot Chat for 5 built-in scenarios:

| Skill | What it does |
|---|---|
| `sync-metadata` | Search Colectica → transform → bulk import to Purview |
| `lineage-propagation` | Build Purview lineage from Colectica relationships |
| `drift-detection` | Detect missing / stale / orphaned entities |
| `tag-governance` | Bidirectional tag ↔ classification sync |
| `cross-system-query` | Natural-language Q&A across both systems |

Agent definition: `.github/agents/ColecticaPurviewAgent.md`  
Skills: `.github/skills/*.md`

### Azure AI Foundry Agent SDK

Full Python agent using `azure-ai-projects` with native MCP tool support.
Runs in AI Foundry, Azure Container Apps, or any Docker host.

```bash
cd integrations/examples/foundry_agent
pip install -r requirements.txt

export AZURE_AI_PROJECT_ENDPOINT="https://<hub>.api.azureml.ms"
export COLECTICA_MCP_URL="https://colectica-mcp.<env>.azurecontainerapps.io/mcp"
export PURVIEW_MCP_URL="https://purview-mcp.<env>.azurecontainerapps.io/mcp"

python agent.py sync           # sync QuestionItems → Purview (dry run)
python agent.py drift          # detect metadata drift
python agent.py "your question"
```

### Claude SDK Agent (local / prototyping)

```bash
cd integrations/agents
pip install anthropic python-dotenv
python colectica_purview_agent.py
```

### More frameworks

See [`integrations/docs/`](integrations/docs/README.md) for LangChain,
LlamaIndex, local LLM, and custom agent guides.

---

## 9. Verification commands

Run Colectica server tool unit tests locally:

```powershell
python -m unittest tests/test_server_tools.py tests/test_client_pagination.py -v
```

## License

This project is licensed under the Apache License 2.0.
See the [LICENSE](LICENSE) file for details.

