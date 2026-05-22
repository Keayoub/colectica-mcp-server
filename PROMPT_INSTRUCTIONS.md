# Colectica MCP Server — LLM Prompt Instructions

## Overview

The Colectica MCP server exposes the full **Colectica Repository REST API** as MCP tools via OpenAPI discovery. Operations are discovered dynamically from the live API, so the available tool set reflects exactly what the connected repository supports.

The two primary tools are:

| Tool | Purpose |
|------|---------|
| `list_operations` | Discover available API operations (filterable by category or keyword) |
| `call_operation` | Execute a specific operation by `operationId` with typed parameters |

---

## Quick Rules

1. **Discover before executing.** Always call `list_operations` (or `find_operations` / `list_operations_by_category`) first to confirm the correct `operationId` and required parameters before calling `call_operation`.

2. **Use `operationId` exactly.** Operation IDs are case-sensitive strings such as `GET_api_v1_item_agency_id`. Copy them verbatim from `list_operations` output.

3. **Pass `auth_mode` explicitly when non-default.** The default auth mode is `auto` (inferred from environment variables). Override with `auth_mode="bearer"`, `auth_mode="basic"`, or `auth_mode="none"` when the operation requires a specific scheme.

4. **Narrow large lists with `filter_keywords`.** When `list_operations` returns many results, supply a `filter_keywords` argument (e.g., `"item"`, `"search"`, `"transaction"`) to reduce noise before chaining to `call_operation`.

5. **Chain calls for multi-step workflows.** Use the output of one `call_operation` (e.g., an item's `AgencyId` + `Identifier`) as the input to the next.

6. **Pagination.** For endpoints that return large result sets, use `call_operation_paginated` instead of `call_operation`.

---

## Prompt Templates

### Template 1 — Discover Available Operations

Use this when you want to explore what the server can do or find the right endpoint.

```
List all operations available in the Colectica MCP server.
Filter by the keyword "<keyword>" and show operationId, HTTP method, path, and summary.
```

**Examples:**
- `List all GET operations related to /api/v1/item`
- `Show all operations in the "search" category`
- `Find operations that contain the word "transaction"`

---

### Template 2 — Execute a Specific Operation with Parameters

Use this when you know the endpoint and want to retrieve or write data.

```
Call the operation "<operationId>" with the following parameters:
- AgencyId: "<agency>"
- Identifier: "<guid>"
- Version: <int>
Return the full response.
```

**Examples:**
- `Call the operation that retrieves an item by AgencyId and Identifier`
- `Execute GET_api_v1_item_agency_id_version with AgencyId="int.example", Identifier="abc-123", Version=1`
- `Call GET_api_v1_repository_statistics and summarise the result`

---

### Template 3 — Search by Keyword and Chain Calls

Use this for multi-step discovery + execution workflows.

```
1. Find operations matching the keyword "<keyword>".
2. Select the most relevant operationId for <goal>.
3. Call it with parameters: <params>.
4. Use the result to call <next operation> with the retrieved identifiers.
```

**Examples:**
- `Find and run the search endpoint with keyword filter "variable", then retrieve the full item for the first result`
- `Search for all items of type "QuestionItem" in agency "int.example" and list their names and identifiers`
- `Find the operation that lists repository statistics and call it; then find the operation that retrieves a specific item and call it with the first identifier from the statistics response`

---

## Short Example Prompts

```
List all GET operations for /api/v1/item
```

```
Call the operation that retrieves an item by AgencyId and Identifier.
Use AgencyId="int.example" and Identifier="00000000-0000-0000-0000-000000000001"
```

```
Find and run the search endpoint with keyword filter "variable"
```

```
Show available operations in the "transaction" category and start a new transaction
```

```
Get repository statistics and show total item count by type
```

```
Search for QuestionItems in agency "int.example" and return the first 5 results with their labels
```

---

## Parameter Reference

| Parameter | Type | Notes |
|-----------|------|-------|
| `operationId` | string | From `list_operations` output — exact match required |
| `auth_mode` | `"auto"` \| `"bearer"` \| `"basic"` \| `"none"` | Default: `"auto"` |
| `filter_keywords` | string | Comma-separated keywords to narrow `list_operations` results |
| `page` / `page_size` | int | For `call_operation_paginated` |

---

## Common Workflows

### Find an item by identifier
1. `list_operations` → filter `"item"` → note `GET_api_v1_item_agency_id_version`
2. `call_operation("GET_api_v1_item_agency_id_version", AgencyId=..., Identifier=..., Version=1)`

### Full-text search
1. `list_operations` → filter `"search"` → note `POST_api_v1_query`
2. `call_operation("POST_api_v1_query", SearchTerms="education", MaxResults=20)`

### Browse item set (graph of related items)
1. Retrieve item with `GET_api_v1_item_agency_id`
2. Follow relationships with `POST_api_v1_query_relationship_bysubject`
