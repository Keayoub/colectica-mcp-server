from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Ensure imports work even when the package is not installed in editable mode.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from colectica_mcp import server


class ResolveAuthModeTests(unittest.TestCase):
    def test_resolve_auth_mode_accepts_supported_values(self) -> None:
        self.assertEqual(server._resolve_auth_mode(" auto "), "auto")
        self.assertEqual(server._resolve_auth_mode("BASIC"), "basic")
        self.assertEqual(server._resolve_auth_mode("Bearer"), "bearer")
        self.assertEqual(server._resolve_auth_mode("none"), "none")

    def test_resolve_auth_mode_rejects_invalid_value(self) -> None:
        with self.assertRaises(ValueError):
            server._resolve_auth_mode("oauth")


class CategoryDerivationTests(unittest.TestCase):
    def test_derive_operation_category_handles_query_and_standard_groups(self) -> None:
        self.assertEqual(server._derive_operation_category("/api/v1/_query"), "Query")
        self.assertEqual(server._derive_operation_category("/api/v1/transaction/commit"), "Transaction")
        self.assertEqual(server._derive_operation_category("/api/v1/versionNumber"), "VersionNumber")


class ServerToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.cfg = SimpleNamespace(base_url="https://colectica.example")

        self.resolve_config_patcher = patch("colectica_mcp.server._resolve_config", return_value=self.cfg)
        self.mock_resolve_config = self.resolve_config_patcher.start()

        self.client_cls_patcher = patch("colectica_mcp.server.ColecticaApiClient")
        self.mock_client_cls = self.client_cls_patcher.start()
        self.mock_client = self.mock_client_cls.return_value

        self.addCleanup(self.resolve_config_patcher.stop)
        self.addCleanup(self.client_cls_patcher.stop)

    async def test_health_check_uses_discovered_openapi(self) -> None:
        self.mock_client.discover_openapi = AsyncMock(return_value=("/openapi.json", {}))

        result = await server.health_check(auth_mode="basic")

        self.mock_client.discover_openapi.assert_awaited_once_with(auth_mode="basic")
        self.assertEqual(result["base_url"], "https://colectica.example")
        self.assertEqual(result["openapi_document"], "/openapi.json")
        self.assertEqual(result["auth_mode_used"], "basic")

    async def test_list_operations_delegates_to_client(self) -> None:
        expected = [{"operation_id": "GetItem", "method": "post", "path": "/api/GetItem"}]
        self.mock_client.list_operations = AsyncMock(return_value=expected)

        result = await server.list_operations(auth_mode="auto")

        self.mock_client.list_operations.assert_awaited_once_with(auth_mode="auto")
        self.assertEqual(result, expected)

    async def test_call_operation_passes_arguments(self) -> None:
        response = {"status_code": 200, "body": {"ok": True}}
        self.mock_client.call_operation = AsyncMock(return_value=response)

        result = await server.call_operation("GetItem", arguments={"urn": "urn:test"}, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            operation_id="GetItem",
            arguments={"urn": "urn:test"},
            auth_mode="bearer",
        )
        self.assertEqual(result, response)

    async def test_call_endpoint_maps_method_and_path_to_synthesized_operation_id(self) -> None:
        response = {"status_code": 200, "body": {"ok": True}}
        self.mock_client.call_operation = AsyncMock(return_value=response)

        result = await server.call_endpoint(
            method="post",
            path="api/v1/transaction/commit",
            arguments={"body": {"id": "tx-1"}},
            auth_mode="bearer",
        )

        self.mock_client.call_operation.assert_awaited_once_with(
            operation_id="POST_api_v1_transaction_commit",
            arguments={"body": {"id": "tx-1"}},
            auth_mode="bearer",
        )
        self.assertEqual(result, response)

    async def test_call_endpoint_rejects_invalid_method(self) -> None:
        with self.assertRaises(ValueError):
            await server.call_endpoint(method="TRACE", path="/api/v1/item", auth_mode="auto")

    async def test_operation_details_delegates_to_client(self) -> None:
        expected = {"operation_id": "Search", "parameters": []}
        self.mock_client.operation_details = AsyncMock(return_value=expected)

        result = await server.operation_details("Search", auth_mode="none")

        self.mock_client.operation_details.assert_awaited_once_with(operation_id="Search", auth_mode="none")
        self.assertEqual(result, expected)

    async def test_call_operation_paginated_passes_paging_arguments(self) -> None:
        expected = {"items": [1, 2, 3], "pages": 2}
        self.mock_client.call_operation_paginated = AsyncMock(return_value=expected)

        result = await server.call_operation_paginated(
            operation_id="Search",
            arguments={"q": "income"},
            auth_mode="auto",
            max_pages=5,
            items_path="data.items",
        )

        self.mock_client.call_operation_paginated.assert_awaited_once_with(
            operation_id="Search",
            arguments={"q": "income"},
            auth_mode="auto",
            max_pages=5,
            items_path="data.items",
        )
        self.assertEqual(result, expected)

    async def test_get_repository_info_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_repository_info(auth_mode="basic")

        self.mock_client.call_operation.assert_awaited_once_with("GetRepositoryInfo", auth_mode="basic")
        self.assertEqual(result, expected)

    async def test_get_item_by_urn_maps_argument(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_by_urn("urn:colectica:item:123", auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GetItem",
            arguments={"urn": "urn:colectica:item:123"},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_register_item_body_wraps_body_argument(self) -> None:
        expected = {"status_code": 201}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        payload = {"name": "Example"}
        result = await server.register_item_body(payload, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "RegisterItem",
            arguments={"body": payload},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_find_operations_filters_by_query_terms(self) -> None:
        self.mock_client.list_operations = AsyncMock(
            return_value=[
                {"operation_id": "GetItem", "method": "GET", "path": "/items/{id}"},
                {"operation_id": "ExportDDI", "method": "POST", "path": "/ddi/export"},
                {"operation_id": "Search", "method": "POST", "path": "/search"},
            ]
        )

        result = await server.find_operations(query="ddi", auth_mode="auto", limit=10)

        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["matches"][0]["operation_id"], "ExportDDI")

    async def test_find_ddi_operations_uses_ddi_keyword_set(self) -> None:
        self.mock_client.list_operations = AsyncMock(
            return_value=[
                {"operation_id": "GetItem", "method": "GET", "path": "/items/{id}"},
                {"operation_id": "ImportQuestionnaire", "method": "POST", "path": "/ddi/import"},
                {"operation_id": "Search", "method": "POST", "path": "/search"},
            ]
        )

        result = await server.find_ddi_operations(auth_mode="auto", limit=10)

        self.assertEqual(result["total_matches"], 1)
        self.assertEqual(result["matches"][0]["operation_id"], "ImportQuestionnaire")

    async def test_list_operation_categories_groups_and_counts_operations(self) -> None:
        self.mock_client.list_operations = AsyncMock(
            return_value=[
                {"operation_id": "GetAgency", "method": "GET", "path": "/api/v1/agency"},
                {"operation_id": "Search", "method": "POST", "path": "/api/v1/_query"},
                {"operation_id": "Commit", "method": "POST", "path": "/api/v1/transaction/commit"},
                {"operation_id": "ListAgency", "method": "GET", "path": "/api/v1/agency/all"},
            ]
        )

        result = await server.list_operation_categories(auth_mode="auto")

        self.assertEqual(result["total_operations"], 4)
        categories = {item["category"]: item["operation_count"] for item in result["categories"]}
        self.assertEqual(categories["Agency"], 2)
        self.assertEqual(categories["Query"], 1)
        self.assertEqual(categories["Transaction"], 1)

    async def test_list_operations_by_category_filters_results(self) -> None:
        self.mock_client.list_operations = AsyncMock(
            return_value=[
                {"operation_id": "GetAgency", "method": "GET", "path": "/api/v1/agency"},
                {"operation_id": "SetRating", "method": "POST", "path": "/api/v1/rating"},
                {"operation_id": "DeleteAgency", "method": "DELETE", "path": "/api/v1/agency/{agency}"},
            ]
        )

        result = await server.list_operations_by_category(category="agency", auth_mode="auto", limit=10)

        self.assertEqual(result["total_matches"], 2)
        self.assertEqual(len(result["matches"]), 2)
        self.assertTrue(all(match["path"].startswith("/api/v1/agency") for match in result["matches"]))

    async def test_get_ddi_fragment_without_version_uses_expected_path_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_ddi_fragment("ABC", "item-1", auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_ddi_agency_identifier",
            arguments={"agency": "ABC", "identifier": "item-1"},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_ddi_fragment_with_version_uses_expected_path_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_ddi_fragment("ABC", "item-1", version=2, auth_mode="basic")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_ddi_agency_identifier_version",
            arguments={"agency": "ABC", "identifier": "item-1", "version": 2},
            auth_mode="basic",
        )
        self.assertEqual(result, expected)

    async def test_get_item_json_set_filtered_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        payload = {"agencyId": "ABC", "identifier": "00000000-0000-0000-0000-000000000001"}
        result = await server.get_item_json_set_filtered(body=payload, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_jsonset_filtered",
            arguments={"body": payload},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)
