import azure.functions as func
import json
import logging
from function_app import client

logger = logging.getLogger("colectica-mcp-functions")

# Health check endpoint
@func.route(route="health", methods=["GET"])
async def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint for monitoring."""
    try:
        if client is None:
            return func.HttpResponse(
                json.dumps({"status": "unhealthy", "error": "Client not initialized"}),
                status_code=503,
                headers={"Content-Type": "application/json"}
            )
        
        # Verify Colectica connectivity
        openapi = await client.discover_openapi()
        if openapi:
            logger.info("Health check passed")
            return func.HttpResponse(
                json.dumps({"status": "healthy", "service": "colectica-mcp"}),
                status_code=200,
                headers={"Content-Type": "application/json"}
            )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return func.HttpResponse(
            json.dumps({"status": "unhealthy", "error": str(e)}),
            status_code=503,
            headers={"Content-Type": "application/json"}
        )

# MCP endpoint
@func.route(route="mcp", methods=["GET", "POST", "OPTIONS"])
async def mcp_handler(req: func.HttpRequest) -> func.HttpResponse:
    """Handle MCP HTTP requests."""
    try:
        logger.info(f"MCP request: {req.method} {req.path}")
        
        if req.method == "OPTIONS":
            return func.HttpResponse(
                body=b"",
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type"
                }
            )
        
        return func.HttpResponse(
            json.dumps({"message": "Colectica MCP Server is running. Use /api/mcp for MCP protocol."}),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        logger.error(f"Error in MCP handler: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )

# List tools endpoint
@func.route(route="tools", methods=["GET"])
async def list_tools(req: func.HttpRequest) -> func.HttpResponse:
    """List available Colectica tools."""
    try:
        if client is None:
            return func.HttpResponse(
                json.dumps({"error": "Client not initialized"}),
                status_code=503,
                headers={"Content-Type": "application/json"}
            )
        
        operations = await client.list_operations()
        logger.info(f"Listed {len(operations)} operations")
        
        return func.HttpResponse(
            json.dumps(operations, default=str),
            status_code=200,
            headers={"Content-Type": "application/json"}
        )
    except Exception as e:
        logger.error(f"Error listing tools: {str(e)}")
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            headers={"Content-Type": "application/json"}
        )
