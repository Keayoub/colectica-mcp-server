import azure.functions as func
import logging
from colectica_mcp.client import ColecticaApiClient
from colectica_mcp.config import ColecticaConfig

# Initialize logger
logger = logging.getLogger("colectica-mcp-functions")
logger.setLevel(logging.INFO)

# Initialize Colectica client
try:
    config = ColecticaConfig.from_env()
    client = ColecticaApiClient(config)
    logger.info("Colectica client initialized")
except Exception as e:
    logger.error(f"Failed to initialize Colectica client: {str(e)}")
    client = None

# Create Azure Functions app
app = func.FunctionApp(http_type='asgi')
