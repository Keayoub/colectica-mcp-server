# Local LLM Agent Integration

**Framework:** Ollama / GGML / llama.cpp  
**Best for:** Privacy-first, offline, no API costs, on-device execution

## Setup

### 1. Install Ollama

```bash
# Download from https://ollama.ai
ollama pull llama2:7b-chat
# Or larger model
ollama pull mistral:7b
```

### 2. Define Tool Schema

```python
import json
import subprocess

tools_schema = """
You have access to these tools:

1. colectica_search
   - Searches Colectica Repository
   - Arguments: query (string), limit (int, default 50)
   - Returns: JSON with items list

2. purview_bulk_import
   - Imports entities to Purview
   - Arguments: entities (JSON array), dry_run (bool, default true)
   - Returns: JSON with counts

To use a tool, format your response as:
<tool_call>
{
  "tool": "tool_name",
  "args": {"arg1": "value1"}
}
</tool_call>
"""
```

### 3. Run Agent Loop

```python
import re

def run_local_agent():
    """Run sync agent with local LLM."""
    system_prompt = "You are a data orchestrator for Colectica and Purview..."
    messages = [
        {"role": "system", "content": system_prompt + tools_schema},
        {"role": "user", "content": "Sync survey questions from Colectica to Purview"},
    ]
    
    while True:
        # Call local LLM
        response = subprocess.run(
            ["ollama", "run", "mistral:7b"],
            input=json.dumps(messages),
            capture_output=True,
            text=True
        )
        
        output = response.stdout
        messages.append({"role": "assistant", "content": output})
        
        # Parse tool calls
        tool_calls = re.findall(r"<tool_call>(.*?)</tool_call>", output, re.DOTALL)
        
        if not tool_calls:
            # No more tool calls, agent done
            print(output)
            break
        
        # Execute tools
        for call_str in tool_calls:
            call = json.loads(call_str)
            tool_name = call["tool"]
            args = call["args"]
            
            if tool_name == "colectica_search":
                result = call_mcp_colectica("search", args)
            elif tool_name == "purview_bulk_import":
                result = call_mcp_purview("bulk_import", args)
            
            messages.append({
                "role": "user",
                "content": f"Tool {tool_name} returned: {json.dumps(result)}"
            })
```

## Advantages

- ✅ No API costs
- ✅ Full privacy (runs locally)
- ✅ Works offline
- ✅ Open source models
- ✅ Fast for small models on consumer hardware

## Disadvantages

- ⚠️ Smaller models less capable
- ⚠️ Slower inference (5-30s vs <1s)
- ⚠️ Requires GPU for acceptable speed
- ⚠️ Complex reasoning harder for 7B models

## Recommended Models

- **Mistral 7B:** Good balance of speed/capability
- **Llama 2 13B:** Better reasoning, needs 8GB+ RAM
- **ORCA Mini:** Smaller, faster, less capable
- **Dolphin 2.6:** Fine-tuned for instructions

## See Also

- [FRAMEWORK_AGNOSTIC.md](./FRAMEWORK_AGNOSTIC.md) - All frameworks comparison
- [Ollama](https://ollama.ai)
- [llama.cpp](https://github.com/ggerganov/llama.cpp)
