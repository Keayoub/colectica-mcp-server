# Custom Orchestration Implementation

**Framework:** DIY / No Framework  
**Best for:** Full control, minimal dependencies, edge cases, custom workflows

## When to Use Custom

- You need 100% control over orchestration logic
- Framework overhead is unacceptable
- You have very specific workflow requirements
- You want to understand every step

## Architecture

```
Your Code (Custom)
    ↓
MCP Client Library
    ↓
Colectica MCP  ←→  Purview MCP (stdio)
    ↓
REST APIs
```

## Implementation

### 1. Create MCP Client Wrapper

```python
import asyncio
import json
import subprocess
from typing import Any

class MCPClient:
    """Wraps MCP stdio transport."""
    
    def __init__(self, mcp_server_path: str):
        self.process = subprocess.Popen(
            [mcp_server_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    
    def call_tool(self, tool_name: str, **kwargs) -> dict:
        """Call a tool on the MCP server."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": kwargs,
            }
        }
        
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        
        response = json.loads(self.process.stdout.readline())
        return response.get("result", {})
    
    def close(self):
        self.process.terminate()
```

### 2. Implement Orchestration

```python
from datetime import datetime
import json

class SyncOrchestrator:
    """Custom orchestration logic."""
    
    def __init__(self, colectica_mcp_path: str, purview_mcp_path: str):
        self.colectica = MCPClient(colectica_mcp_path)
        self.purview = MCPClient(purview_mcp_path)
        self.checkpoint = {}
    
    def sync_survey_items(self, query: str, dry_run: bool = True):
        """Main sync workflow."""
        print(f"Starting sync: {query}")
        
        # Step 1: Query Colectica
        print("  → Searching Colectica...")
        search_result = self.colectica.call_tool(
            "search",
            query=query,
            limit=50,
        )
        items = search_result.get("items", [])
        print(f"  ✓ Found {len(items)} items")
        
        # Step 2: Fetch full items
        print("  → Fetching item details...")
        full_items = []
        for item in items:
            detail = self.colectica.call_tool(
                "get_item_json_set",
                agency=item.get("agency"),
                identifier=item.get("id"),
            )
            full_items.append(detail)
        print(f"  ✓ Fetched {len(full_items)} items")
        
        # Step 3: Transform
        print("  → Transforming to Purview format...")
        entities = self._transform_items(full_items)
        print(f"  ✓ Transformed to {len(entities)} entities")
        
        # Step 4: Validate
        print("  → Validating entities...")
        valid_entities = []
        for entity in entities:
            if self._validate_entity(entity):
                valid_entities.append(entity)
            else:
                print(f"    ⚠️  Invalid entity: {entity.get('id')}")
        print(f"  ✓ Validated {len(valid_entities)} entities")
        
        # Step 5: Preview or Import
        if dry_run:
            print("  → Dry run: showing preview")
            self._show_preview(valid_entities)
        else:
            print("  → Importing to Purview...")
            import_result = self.purview.call_tool(
                "bulk_import",
                entities=valid_entities,
                dry_run=False,
            )
            print(f"  ✓ Created: {import_result.get('created')}")
            print(f"  ✓ Updated: {import_result.get('updated')}")
            print(f"  ✓ Failed: {import_result.get('failed')}")
        
        # Step 6: Update checkpoint
        self.checkpoint = {
            "last_synced": datetime.utcnow().isoformat(),
            "total_items": len(valid_entities),
            "failed_items": [],
        }
        self._save_checkpoint()
        
        print("  ✓ Sync complete")
    
    def _transform_items(self, items: list) -> list:
        """Transform Colectica items to Purview entities."""
        entities = []
        for item in items:
            entity = {
                "id": item.get("id"),
                "name": item.get("name"),
                "description": item.get("description", ""),
                "typeName": self._map_type(item.get("type")),
                "attributes": {
                    "sourceSystemId": "colectica",
                    "sourceSystemName": item.get("name"),
                },
            }
            entities.append(entity)
        return entities
    
    def _map_type(self, colectica_type: str) -> str:
        """Map Colectica type to Purview type."""
        mapping = {
            "QuestionItem": "DataSet",
            "Variable": "Column",
            "Instrument": "Process",
            "ResourcePackage": "DataSet",
        }
        return mapping.get(colectica_type, "Asset")
    
    def _validate_entity(self, entity: dict) -> bool:
        """Validate entity before import."""
        return (
            entity.get("id") is not None
            and entity.get("name") is not None
            and entity.get("typeName") is not None
        )
    
    def _show_preview(self, entities: list):
        """Show preview of what would be imported."""
        for entity in entities[:5]:  # Show first 5
            print(f"    - {entity.get('name')} ({entity.get('typeName')})")
        if len(entities) > 5:
            print(f"    ... and {len(entities) - 5} more")
    
    def _save_checkpoint(self):
        """Save checkpoint for resumable syncs."""
        with open(".sync_checkpoint.json", "w") as f:
            json.dump(self.checkpoint, f, indent=2)
    
    def close(self):
        """Clean up MCP connections."""
        self.colectica.close()
        self.purview.close()
```

### 3. Execute

```python
if __name__ == "__main__":
    orchestrator = SyncOrchestrator(
        colectica_mcp_path="python -m colectica_mcp.server",
        purview_mcp_path="python -m purview_mcp.server",
    )
    
    try:
        # Dry run first
        orchestrator.sync_survey_items(
            query="type:QuestionItem",
            dry_run=True,
        )
        
        # Then actual sync
        # orchestrator.sync_survey_items(
        #     query="type:QuestionItem",
        #     dry_run=False,
        # )
    finally:
        orchestrator.close()
```

## Advantages

- ✅ Maximum control & visibility
- ✅ Minimal dependencies
- ✅ Easy to debug step-by-step
- ✅ Customizable error handling
- ✅ No framework limitations

## Disadvantages

- ⚠️ More code to write
- ⚠️ No intelligent tool selection
- ⚠️ More error handling needed
- ⚠️ Harder to extend with new models

## See Also

- [USE_CASES.md](./USE_CASES.md) — 5 concrete integration scenarios with code
- [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) — All frameworks comparison
- [MCP Spec](https://modelcontextprotocol.io)
