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

from colectica_mcp.client import ColecticaApiClient, OperationRef
from colectica_mcp.config import ColecticaConfig


def _make_client() -> ColecticaApiClient:
    cfg = ColecticaConfig(
        base_url="https://colectica.example",
        timeout_seconds=30,
        verify_ssl=True,
        username=None,
        password=None,
        bearer_token=None,
        transport="stdio",
        mount_path=None,
    )
    return ColecticaApiClient(cfg)


class PaginationUtilityTests(unittest.TestCase):
    def test_synthesize_operation_id_is_stable_for_method_and_path(self) -> None:
        op_id = ColecticaApiClient.synthesize_operation_id("get", "/api/v1/ddi/{agency}/{identifier}")
        self.assertEqual(op_id, "GET_api_v1_ddi_agency_identifier")

    def test_extract_items_supports_default_and_nested_paths(self) -> None:
        body = {"items": [1, 2]}
        nested = {"data": {"records": ["a", "b"]}}

        self.assertEqual(ColecticaApiClient._extract_items(body), [1, 2])
        self.assertEqual(ColecticaApiClient._extract_items(nested, items_path="data.records"), ["a", "b"])
        self.assertIsNone(ColecticaApiClient._extract_items(nested, items_path="data.missing"))

    def test_extract_next_token_from_header_body_and_next_link(self) -> None:
        self.assertEqual(
            ColecticaApiClient._extract_next_token(body={}, headers={"x-continuation-token": "token-1"}),
            "token-1",
        )
        self.assertEqual(
            ColecticaApiClient._extract_next_token(body={"meta": {"nextToken": "token-2"}}, headers={}),
            "token-2",
        )
        self.assertEqual(
            ColecticaApiClient._extract_next_token(
                body={"@odata.nextLink": "https://api.example/items?$skiptoken=token-3"},
                headers={},
            ),
            "token-3",
        )

    def test_infer_token_parameter_name_prefers_supported_query_names(self) -> None:
        client = _make_client()
        operation_ref = OperationRef(
            operation_id="Search",
            method="GET",
            path="/search",
            path_spec={
                "parameters": [
                    {"name": "continuationToken", "in": "query"},
                    {"name": "q", "in": "query"},
                ]
            },
            operation_spec={},
        )

        token_name = client._infer_token_parameter_name({}, operation_ref, args={"q": "income"})
        self.assertEqual(token_name, "continuationToken")


class CallOperationPaginatedTests(unittest.IsolatedAsyncioTestCase):
    async def test_call_operation_paginated_aggregates_items_and_updates_token(self) -> None:
        client = _make_client()
        operation_ref = OperationRef(
            operation_id="Search",
            method="GET",
            path="/search",
            path_spec={"parameters": [{"name": "continuationToken", "in": "query"}]},
            operation_spec={},
        )

        client.discover_openapi = AsyncMock(return_value=("/openapi.json", {}))
        client._operation_index = AsyncMock(return_value={"Search": operation_ref})
        client.call_operation = AsyncMock(
            side_effect=[
                {
                    "status_code": 200,
                    "headers": {},
                    "body": {"items": [1, 2], "continuationToken": "token-a"},
                },
                {
                    "status_code": 200,
                    "headers": {},
                    "body": {"items": [3]},
                },
            ]
        )

        input_args = {"q": "income"}
        result = await client.call_operation_paginated(
            operation_id="Search",
            arguments=input_args,
            max_pages=5,
        )

        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(result["items_count"], 3)
        self.assertEqual(result["items"], [1, 2, 3])
        self.assertEqual(result["token_parameter"], "continuationToken")

        self.assertEqual(client.call_operation.await_count, 2)
        self.assertEqual(client.call_operation.await_args_list[1].kwargs["arguments"], {"q": "income", "continuationToken": "token-a"})
        self.assertEqual(input_args, {"q": "income"})

    async def test_call_operation_paginated_respects_max_pages_limit(self) -> None:
        client = _make_client()
        operation_ref = OperationRef(
            operation_id="Search",
            method="GET",
            path="/search",
            path_spec={"parameters": [{"name": "continuationToken", "in": "query"}]},
            operation_spec={},
        )

        client.discover_openapi = AsyncMock(return_value=("/openapi.json", {}))
        client._operation_index = AsyncMock(return_value={"Search": operation_ref})
        client.call_operation = AsyncMock(
            side_effect=[
                {
                    "status_code": 200,
                    "headers": {},
                    "body": {"items": [1], "continuationToken": "token-a"},
                },
                {
                    "status_code": 200,
                    "headers": {},
                    "body": {"items": [2], "continuationToken": "token-b"},
                },
            ]
        )

        result = await client.call_operation_paginated(
            operation_id="Search",
            arguments={"q": "income"},
            max_pages=2,
        )

        self.assertEqual(result["pages_fetched"], 2)
        self.assertTrue(result["stopped_with_next_token"])
        self.assertEqual(result["items"], [1, 2])

    async def test_call_operation_paginated_updates_body_next_result_when_no_query_token(self) -> None:
        client = _make_client()
        operation_ref = OperationRef(
            operation_id="POST_api_v1__query",
            method="POST",
            path="/api/v1/_query",
            path_spec={"parameters": []},
            operation_spec={},
        )

        client.discover_openapi = AsyncMock(return_value=("/openapi.json", {}))
        client._operation_index = AsyncMock(return_value={"POST_api_v1__query": operation_ref})
        client.call_operation = AsyncMock(
            side_effect=[
                {
                    "status_code": 200,
                    "headers": {},
                    "body": {"results": ["a"], "nextResult": "25"},
                },
                {
                    "status_code": 200,
                    "headers": {},
                    "body": {"results": ["b"]},
                },
            ]
        )

        input_args = {"body": {"searchTerms": ["income"], "nextResult": 0}}
        result = await client.call_operation_paginated(
            operation_id="POST_api_v1__query",
            arguments=input_args,
            max_pages=5,
        )

        self.assertEqual(result["pages_fetched"], 2)
        self.assertEqual(result["items"], ["a", "b"])
        self.assertIsNone(result["token_parameter"])
        self.assertEqual(result["body_token_field"], "nextResult")
        self.assertEqual(client.call_operation.await_args_list[1].kwargs["arguments"]["body"]["nextResult"], "25")
        self.assertEqual(input_args, {"body": {"searchTerms": ["income"], "nextResult": 0}})
