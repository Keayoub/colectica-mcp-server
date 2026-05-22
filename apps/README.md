# Azure Applications

This directory contains deployable Azure applications for the Colectica MCP server.

## Directory Structure

```
apps/
├── colectica_functions/    # Azure Functions app (recommended)
│   ├── function_app.py
│   ├── host.json
│   ├── requirements.txt
│   ├── local.settings.json
│   ├── mcp_trigger/
│   │   └── __init__.py
│   └── README.md
├── .gitignore
└── README.md (this file)
```

## Applications

### 1. Colectica Functions (`colectica_functions/`)

**Azure Functions with native MCP support**

- **Type**: Azure Functions (Flex Consumption)
- **Language**: Python 3.11
- **Use Case**: Event-driven, serverless MCP server
- **Benefits**:
  - Native MCP protocol support
  - Built-in authentication (Entra ID + access keys)
  - Auto-scales to zero when idle
  - Lower cost than always-running services
  - Easy VS Code integration

**Quick Start**:
```bash
cd colectica_functions
func start
```

See [colectica_functions/README.md](colectica_functions/README.md) for detailed documentation.

## Deployment

All applications are deployed together using Azure Developer CLI from the workspace root:

```bash
cd ../..
azd up
```

This will:
- Create all necessary Azure infrastructure
- Build and deploy each application
- Configure secrets and authentication
- Provide deployment endpoints

## Local Development

Each application has its own local development setup. Refer to the individual application README for:
- Local setup instructions
- Environment variable configuration
- Testing endpoints
- Debugging

## Project Layout

```
Colectica_mcp/
├── src/                    # Colectica SDK code
├── apps/                   # Azure deployable applications (THIS DIRECTORY)
├── .azure/                 # Azure infrastructure (Bicep, deployment plan)
├── tests/                  # Tests
├── pyproject.toml          # Main project configuration
└── README.md               # Main project README
```

## Adding New Applications

To add a new Azure application:

1. Create a new folder in `apps/`: `mkdir apps/<app-name>`
2. Add application code and configuration
3. Create `README.md` with setup instructions
4. Update `.azure/deployment-plan.md` if infrastructure changes
5. Optionally update `.azure/infra/main.bicep` for additional resources

## Environment Configuration

### Local Development
Each app has `local.settings.json` for local environment variables.

### Azure Deployment
Secrets are stored in Azure Key Vault and retrieved at runtime.
Update Key Vault secrets before deployment:
```bash
az keyvault secret set --vault-name <kv-name> --name <secret-name> --value <value>
```

## Support

- **Azure Functions**: [Official docs](https://learn.microsoft.com/azure/azure-functions/)
- **MCP Protocol**: [modelcontextprotocol.io](https://modelcontextprotocol.io/)
- **Project README**: [../README.md](../README.md)
