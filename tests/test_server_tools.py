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
from colectica_mcp.client import ColecticaApiError


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
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["base_url"], "https://colectica.example")
        self.assertEqual(result["openapi_document"], "/openapi.json")
        self.assertEqual(result["auth_mode_used"], "basic")

    async def test_health_check_returns_warning_for_cloudflare_block(self) -> None:
        self.mock_client.discover_openapi = AsyncMock(
            side_effect=ColecticaApiError(
                "Unable to discover OpenAPI document because the site returned a Cloudflare challenge page."
            )
        )

        result = await server.health_check(auth_mode="none")

        self.mock_client.discover_openapi.assert_awaited_once_with(auth_mode="none")
        self.assertEqual(result["status"], "warning")
        self.assertIsNone(result["openapi_document"])
        self.assertIn("Cloudflare challenge page", result["warning"])
        self.assertEqual(result["auth_mode_used"], "none")

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

    async def test_create_transaction_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.create_transaction(auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with("CreateTransaction", auth_mode="auto")
        self.assertEqual(result, expected)

    async def test_get_transactions_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"transactionIds": [1, 2]}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_transactions(body=body, auth_mode="basic")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GetTransactions",
            arguments={"body": body},
            auth_mode="basic",
        )
        self.assertEqual(result, expected)

    async def test_list_transactions_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"skip": 0, "take": 10}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.list_transactions(body=body, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "ListTransactions",
            arguments={"body": body},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_commit_transaction_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"transactionId": 1}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.commit_transaction(body=body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "CommitTransaction",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_cancel_transaction_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"transactionId": 1}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.cancel_transaction(body=body, auth_mode="none")

        self.mock_client.call_operation.assert_awaited_once_with(
            "CancelTransaction",
            arguments={"body": body},
            auth_mode="none",
        )
        self.assertEqual(result, expected)

    async def test_add_items_to_transaction_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"transactionId": 1, "items": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.add_items_to_transaction(body=body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "AddItemsToTransaction",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_items_in_transaction_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_items_in_transaction(transaction_id="1", auth_mode="basic")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GetItemsInTransaction",
            arguments={"transactionId": "1"},
            auth_mode="basic",
        )
        self.assertEqual(result, expected)

    async def test_get_tags_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_tags("AG", "item-1", 1, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GetTags",
            arguments={"agency": "AG", "id": "item-1", "version": 1},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_add_tag_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.add_tag("AG", "item-1", 1, "gold", auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "AddTag",
            arguments={"agency": "AG", "id": "item-1", "version": 1, "tag": "gold"},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_remove_tag_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.remove_tag("AG", "item-1", 1, "gold", auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "RemoveTag",
            arguments={"agency": "AG", "id": "item-1", "version": 1, "tag": "gold"},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_ratings_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_ratings("AG", "item-1", 1, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GetRatings",
            arguments={"agency": "AG", "id": "item-1", "version": 1},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_add_rating_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.add_rating("AG", "item-1", 1, rating=5, auth_mode="basic")

        self.mock_client.call_operation.assert_awaited_once_with(
            "AddRating",
            arguments={"agency": "AG", "id": "item-1", "version": 1, "body": 5},
            auth_mode="basic",
        )
        self.assertEqual(result, expected)

    async def test_search_advanced_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"searchText": "income"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.search_advanced(body=body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "SearchAdvanced",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_search_set_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"items": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.search_set(body=body, auth_mode="none")

        self.mock_client.call_operation.assert_awaited_once_with(
            "SearchSet",
            arguments={"body": body},
            auth_mode="none",
        )
        self.assertEqual(result, expected)

    async def test_get_repository_statistics_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_repository_statistics(auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with("GetRepositoryStatistics", auth_mode="auto")
        self.assertEqual(result, expected)

    # ------------------------------------------------------------------
    # Batch 1 — Item lifecycle, versions, history, comments
    # ------------------------------------------------------------------

    async def test_get_item_versions_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_versions("AG", "item-1", auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_item_agency_id_versions",
            arguments={"agency": "AG", "id": "item-1"},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_item_latest_version_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_latest_version("AG", "item-1", auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_item_agency_id_versions_latest",
            arguments={"agency": "AG", "id": "item-1"},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_item_latest_version_by_tag_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_latest_version_by_tag("AG", "item-1", "gold", auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_item_agency_id_tag_versions_latest",
            arguments={"agency": "AG", "id": "item-1", "tag": "gold"},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_item_description_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_description("AG", "item-1", 3, auth_mode="basic")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_item_agency_id_version_description",
            arguments={"agency": "AG", "id": "item-1", "version": 3},
            auth_mode="basic",
        )
        self.assertEqual(result, expected)

    async def test_get_item_history_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_history("AG", "item-1", auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_item_agency_id_history",
            arguments={"agency": "AG", "id": "item-1"},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_item_comments_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_comments("AG", "item-1", auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_item_agency_id_comment",
            arguments={"agency": "AG", "id": "item-1"},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_add_item_comment_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"text": "Nice item"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.add_item_comment("AG", "item-1", 2, body, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_item_agency_id_version_comment",
            arguments={"agency": "AG", "id": "item-1", "version": 2, "body": body},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_delete_items_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"items": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.delete_items(body, auth_mode="basic")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_item_delete",
            arguments={"body": body},
            auth_mode="basic",
        )
        self.assertEqual(result, expected)

    async def test_get_item_descriptions_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"repositoryItems": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_descriptions(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_item_getDescriptions",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_latest_version_numbers_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"repositoryItems": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_latest_version_numbers(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_item_getLatestVersionNumbers",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_items_list_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"repositoryItems": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_items_list(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_item_getList",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_items_list_latest_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"repositoryItems": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_items_list_latest(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_item_getListLatest",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_update_item_state_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"items": [], "deprecated": True}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.update_item_state(body, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_item_updateState",
            arguments={"body": body},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_get_comment_list_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"items": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_comment_list(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_item_getCommentList",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    # ------------------------------------------------------------------
    # Batch 2 — Relationship queries
    # ------------------------------------------------------------------

    async def test_search_relationships_by_subject_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"subject": "urn:x"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.search_relationships_by_subject(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_query_relationship_bysubject",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_search_relationships_by_subject_descriptions_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"subject": "urn:x"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.search_relationships_by_subject_descriptions(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_query_relationship_bysubject_descriptions",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_search_relationships_by_object_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"object": "urn:y"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.search_relationships_by_object(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_query_relationship_byobject",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_search_relationships_by_object_descriptions_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"object": "urn:y"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.search_relationships_by_object_descriptions(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_query_relationship_byobject_descriptions",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_relationship_matrix_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"items": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_relationship_matrix(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_query_relationship_matrix",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_relationship_matrix_typed_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"items": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_relationship_matrix_typed(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_query_relationship_matrix_typed",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    # ------------------------------------------------------------------
    # Batch 3 — Settings, agency, events, permissions, sets, tokens
    # ------------------------------------------------------------------

    async def test_get_settings_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_settings(auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_setting",
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_setting_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_setting("MaxResults", auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_setting_setting",
            arguments={"setting": "MaxResults"},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_set_setting_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"name": "MaxResults", "value": "100"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.set_setting(body, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_setting",
            arguments={"body": body},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_delete_setting_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.delete_setting("MaxResults", auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "DELETE_api_v1_setting_setting",
            arguments={"setting": "MaxResults"},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_create_agency_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"agency": "int.example"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.create_agency(body, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_agency",
            arguments={"body": body},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_delete_agency_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.delete_agency("int.example", auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "DELETE_api_v1_agency_agency",
            arguments={"agency": "int.example"},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_publish_event_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"eventType": "ItemCreated"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.publish_event(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_event",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_add_permissions_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"permissions": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.add_permissions(body, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_permission",
            arguments={"body": body},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_delete_permissions_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"permissions": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.delete_permissions(body, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_permission_delete",
            arguments={"body": body},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_get_permissions_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"items": []}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_permissions(body, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_permission_get",
            arguments={"body": body},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_get_item_set_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_set("AG", "root-1", auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_set_agency_id",
            arguments={"agency": "AG", "id": "root-1"},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_item_set_with_version_passes_version_argument(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_set("AG", "root-1", version=2, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_set_agency_id",
            arguments={"agency": "AG", "id": "root-1", "version": 2},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_item_set_versioned_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_set_versioned("AG", "root-1", 4, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_set_agency_id_version",
            arguments={"agency": "AG", "id": "root-1", "version": 4},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_item_set_typed_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_item_set_typed("AG", "root-1", 4, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_set_agency_id_version_typed",
            arguments={"agency": "AG", "id": "root-1", "version": 4},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_create_token_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"username": "user", "password": "pass"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.create_token(body, auth_mode="none")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_token_CreateToken",
            arguments={"body": body},
            auth_mode="none",
        )
        self.assertEqual(result, expected)

    async def test_create_windows_token_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.create_windows_token(auth_mode="none")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_token_CreateWindowsToken",
            auth_mode="none",
        )
        self.assertEqual(result, expected)

    # ------------------------------------------------------------------
    # Batch 4 — Replication
    # ------------------------------------------------------------------

    async def test_get_replication_targets_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_replication_targets(auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "GET_api_v1_replication_targets",
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_create_replication_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"target": "remote-1"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.create_replication(body, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_replication",
            arguments={"body": body},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)

    async def test_get_replication_allowed_initial_states_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"target": "remote-1"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_replication_allowed_initial_states(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_replication_allowed_initial_states",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_get_replication_allowed_transitions_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"target": "remote-1"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.get_replication_allowed_transitions(body, auth_mode="auto")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_replication_allowed_state_transitions",
            arguments={"body": body},
            auth_mode="auto",
        )
        self.assertEqual(result, expected)

    async def test_request_replication_state_change_uses_expected_operation(self) -> None:
        expected = {"status_code": 200}
        body = {"target": "remote-1", "state": "Active"}
        self.mock_client.call_operation = AsyncMock(return_value=expected)

        result = await server.request_replication_state_change(body, auth_mode="bearer")

        self.mock_client.call_operation.assert_awaited_once_with(
            "POST_api_v1_replication_request_state_change",
            arguments={"body": body},
            auth_mode="bearer",
        )
        self.assertEqual(result, expected)
