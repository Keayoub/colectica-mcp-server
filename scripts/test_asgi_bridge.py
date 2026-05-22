"""Test the ASGI bridge directly to capture the real exception."""
import asyncio
import sys
sys.path.insert(0, r"C:\Dvlp\Projects\Purview\Colectica_mcp\hosting\app")

import azure.functions as func
from colectica_mcp.server import mcp
from function_app import _FastMCPBridge

_fastmcp_base = mcp.streamable_http_app()
bridge = _FastMCPBridge(_fastmcp_base)
asgi = func.AsgiMiddleware(bridge)

INIT_BODY = (
    b'{"jsonrpc":"2.0","id":1,"method":"initialize",'
    b'"params":{"protocolVersion":"2024-11-05","capabilities":{},'
    b'"clientInfo":{"name":"test","version":"0"}}}'
)


async def test():
    req = func.HttpRequest(
        method="POST",
        url="http://localhost:7071/api/mcp",
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        body=INIT_BODY,
    )
    try:
        resp = await asgi.handle_async(req)
        print("Status:", resp.status_code)
        body = resp.get_body()
        print("Body:", body[:800].decode("utf-8", errors="replace"))
    except Exception:
        import traceback
        traceback.print_exc()


asyncio.run(test())
