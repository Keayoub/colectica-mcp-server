# Azure Functions App - Colectica MCP Server

## Project Structure

```
apps/
└── colectica_functions/          # Azure Functions application
    ├── function_app.py           # Main Functions app entry point
    ├── host.json                 # Functions runtime configuration
    ├── local.settings.json       # Local development settings
    ├── requirements.txt          # Python dependencies
    └── mcp_trigger/              # MCP HTTP trigger functions
        └── __init__.py           # MCP request handlers (health, mcp, tools)
```

## Setup & Local Development

### Prerequisites
- Python 3.11+
- [Azure Functions Core Tools](https://learn.microsoft.com/azure/azure-functions/functions-run-local)
- [Azurite](https://learn.microsoft.com/azure/storage/common/storage-install-azurite) (local storage emulator)

### Install Dependencies

```bash
cd apps/colectica_functions
pip install -r requirements.txt
```

### Run Locally

1. Start Azurite (local storage emulator):
```bash
azurite
```

2. Start the Functions app:
```bash
func start
```

3. Test endpoints:
```bash
# Health check
curl http://localhost:7071/api/health

# List tools
curl http://localhost:7071/api/tools

# MCP endpoint
curl http://localhost:7071/api/mcp
```

## Environment Variables

Configure in `local.settings.json` for local development:

| Variable | Description | Example |
|----------|-------------|---------|
| `COLECTICA_BASE_URL` | Colectica API base URL | `https://midus.colectica.org/` |
| `COLECTICA_BEARER_TOKEN` | API bearer token | `your_token_here` |
| `COLECTICA_USERNAME` | (Optional) Basic auth username | `user@example.com` |
| `COLECTICA_PASSWORD` | (Optional) Basic auth password | `password` |
| `COLECTICA_VERIFY_SSL` | Verify SSL certificates | `true` |
| `COLECTICA_TIMEOUT` | Request timeout (seconds) | `30` |

## Deployment to Azure

Deploy using `azd` from the workspace root:

```bash
cd ../..
azd up
```

This will:
1. Build and push the Functions app to Azure
2. Create/update Function App resources
3. Configure Key Vault secrets
4. Deploy and start the service

## API Endpoints

Once deployed, your MCP server is available at:
- **MCP Endpoint**: `https://<function-app-name>.azurewebsites.net/api/mcp`
- **Health Check**: `https://<function-app-name>.azurewebsites.net/api/health`
- **List Tools**: `https://<function-app-name>.azurewebsites.net/api/tools`

## VS Code Integration

After deployment, connect in VS Code via `.vscode/mcp.json`:

```json
{
  "servers": {
    "colectica-mcp-azure": {
      "type": "http",
      "url": "https://<function-app-name>.azurewebsites.net/runtime/webhooks/mcp",
      "headers": {
        "x-functions-key": "${input:functions-key}"
      }
    }
  }
}
```

## Troubleshooting

### Functions won't start locally
- Ensure Azurite is running on port 10000
- Check `local.settings.json` is properly formatted
- Verify Python 3.11 is installed

### 401 Unauthorized errors
- Verify Colectica API credentials in environment variables
- Check Key Vault contains required secrets (when deployed)

### MCP endpoint returns 503
- Check health endpoint: `/api/health`
- View logs: `func logs stream` (local) or Azure Portal (cloud)

## Further Reading

- [Azure Functions Documentation](https://learn.microsoft.com/azure/azure-functions/)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [Colectica API Documentation](https://docs.colectica.com/)
