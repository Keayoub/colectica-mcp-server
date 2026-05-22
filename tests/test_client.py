from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

# Ensure imports work even when the package is not installed in editable mode.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from colectica_mcp.client import ColecticaApiClient
from colectica_mcp.client import ColecticaApiError
from colectica_mcp.client import OPENAPI_CANDIDATE_PATHS
from colectica_mcp.config import ColecticaConfig


class DiscoverOpenApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_discover_openapi_reports_cloudflare_challenge(self) -> None:
        config = ColecticaConfig(
            base_url="https://discovery.closer.ac.uk",
            timeout_seconds=30,
            verify_ssl=True,
            username=None,
            password=None,
            bearer_token=None,
            transport="stdio",
            mount_path=None,
        )
        client = ColecticaApiClient(config)
        challenge_error = ColecticaApiError(
            '403 Forbidden: <html><head><title>Just a moment...</title></head><body>Cloudflare</body></html>'
        )
        client._request = AsyncMock(side_effect=[challenge_error] * len(OPENAPI_CANDIDATE_PATHS))

        with self.assertRaises(ColecticaApiError) as captured:
            await client.discover_openapi(auth_mode="none")

        message = str(captured.exception)
        self.assertIn("Cloudflare challenge page", message)
        self.assertIn("direct API/OpenAPI endpoint", message)
        self.assertIn("/swagger/v1/swagger.json", message)
