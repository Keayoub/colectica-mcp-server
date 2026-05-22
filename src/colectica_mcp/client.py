# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import base64
import copy
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import quote
from urllib.parse import urlparse

import httpx

from .config import AuthMode, ColecticaConfig

OPENAPI_CANDIDATE_PATHS = (
    "/swagger/v1/swagger.json",
    "/swagger.json",
    "/openapi/v1.json",
    "/openapi.json",
)


class ColecticaApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class OperationRef:
    operation_id: str
    method: str
    path: str
    path_spec: dict[str, Any]
    operation_spec: dict[str, Any]


class ColecticaApiClient:
    def __init__(self, config: ColecticaConfig) -> None:
        self._config = config
        self._openapi_cache_ttl_seconds = self._resolve_openapi_cache_ttl_seconds()
        self._retry_max_retries = self._resolve_non_negative_int("COLECTICA_RETRY_MAX_RETRIES", 2)
        self._retry_base_seconds = self._resolve_non_negative_float("COLECTICA_RETRY_BASE_SECONDS", 0.5)
        self._retry_max_seconds = self._resolve_non_negative_float("COLECTICA_RETRY_MAX_SECONDS", 8.0)
        self._retry_status_codes = {429, 500, 502, 503, 504}
        self._openapi_cache: dict[AuthMode, tuple[float, str, dict[str, Any]]] = {}
        self._operation_index_cache: dict[AuthMode, tuple[float, dict[str, OperationRef]]] = {}

    @staticmethod
    def _resolve_non_negative_int(env_name: str, default: int) -> int:
        raw = os.getenv(env_name, str(default)).strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ColecticaApiError(f"{env_name} must be an integer.") from exc
        if value < 0:
            raise ColecticaApiError(f"{env_name} must be >= 0.")
        return value

    @staticmethod
    def _resolve_non_negative_float(env_name: str, default: float) -> float:
        raw = os.getenv(env_name, str(default)).strip()
        try:
            value = float(raw)
        except ValueError as exc:
            raise ColecticaApiError(f"{env_name} must be numeric.") from exc
        if value < 0:
            raise ColecticaApiError(f"{env_name} must be >= 0.")
        return value

    def _retry_sleep_seconds(self, retry_index: int) -> float:
        exp = self._retry_base_seconds * (2 ** retry_index)
        jitter = random.uniform(0.0, 0.25 * max(exp, 0.001))
        return min(self._retry_max_seconds, exp + jitter)

    @staticmethod
    def _resolve_openapi_cache_ttl_seconds() -> float:
        raw = os.getenv("COLECTICA_OPENAPI_CACHE_TTL_SECONDS", "300").strip()
        try:
            ttl = float(raw)
        except ValueError as exc:
            raise ColecticaApiError("COLECTICA_OPENAPI_CACHE_TTL_SECONDS must be numeric.") from exc
        if ttl < 0:
            raise ColecticaApiError("COLECTICA_OPENAPI_CACHE_TTL_SECONDS must be >= 0.")
        return ttl

    @staticmethod
    def _is_cloudflare_challenge_error(message: str) -> bool:
        lowered = message.lower()
        return (
            "just a moment" in lowered
            or "cloudflare" in lowered
            or "challenges.cloudflare.com" in lowered
        )

    def _auth_headers(self, auth_mode: AuthMode) -> dict[str, str]:
        if auth_mode == "none":
            return {}

        if auth_mode == "bearer" or (auth_mode == "auto" and self._config.bearer_token):
            if not self._config.bearer_token:
                raise ColecticaApiError("Bearer auth requested but COLECTICA_BEARER_TOKEN is not set.")
            return {"Authorization": f"Bearer {self._config.bearer_token}"}

        if auth_mode == "basic" or auth_mode == "auto":
            if not self._config.username or not self._config.password:
                if auth_mode == "basic":
                    raise ColecticaApiError(
                        "Basic auth requested but COLECTICA_USERNAME/COLECTICA_PASSWORD are not set."
                    )
                return {}
            token = base64.b64encode(f"{self._config.username}:{self._config.password}".encode("utf-8")).decode(
                "ascii"
            )
            return {"Authorization": f"Basic {token}"}

        return {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        auth_mode: AuthMode = "auto",
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        form_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url_path = path if path.startswith("/") else f"/{path}"
        req_headers = {"Accept": "application/json"}
        req_headers.update(self._auth_headers(auth_mode))
        if headers:
            req_headers.update(headers)

        async with httpx.AsyncClient(
            base_url=self._config.base_url,
            timeout=self._config.timeout_seconds,
            verify=self._config.verify_ssl,
        ) as client:
            for retry_index in range(self._retry_max_retries + 1):
                try:
                    response = await client.request(
                        method=method.upper(),
                        url=url_path,
                        params=params,
                        json=json_body,
                        data=form_body,
                        headers=req_headers,
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if retry_index >= self._retry_max_retries:
                        raise ColecticaApiError(
                            f"Request failed after retries: {type(exc).__name__}: {exc}"
                        ) from exc
                    await asyncio.sleep(self._retry_sleep_seconds(retry_index))
                    continue

                content_type = response.headers.get("content-type", "").lower()
                body: Any
                if "application/json" in content_type:
                    body = response.json()
                else:
                    body = response.text

                if response.status_code in self._retry_status_codes and retry_index < self._retry_max_retries:
                    await asyncio.sleep(self._retry_sleep_seconds(retry_index))
                    continue

                if response.is_error:
                    raise ColecticaApiError(f"{response.status_code} {response.reason_phrase}: {body}")

                return {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "body": body,
                }

        raise ColecticaApiError("Unexpected retry flow termination.")

    async def discover_openapi(self, auth_mode: AuthMode = "auto") -> tuple[str, dict[str, Any]]:
        cache_entry = self._openapi_cache.get(auth_mode)
        now = time.monotonic()
        if cache_entry and cache_entry[0] > now:
            _, discovered_path, spec = cache_entry
            return discovered_path, spec

        last_error = "No OpenAPI document found."
        for candidate_path in OPENAPI_CANDIDATE_PATHS:
            try:
                result = await self._request("GET", candidate_path, auth_mode=auth_mode)
            except ColecticaApiError as err:
                last_error = str(err)
                continue
            body = result["body"]
            if isinstance(body, dict) and "paths" in body:
                if self._openapi_cache_ttl_seconds > 0:
                    self._openapi_cache[auth_mode] = (
                        now + self._openapi_cache_ttl_seconds,
                        candidate_path,
                        body,
                    )
                return candidate_path, body

        if self._is_cloudflare_challenge_error(last_error):
            raise ColecticaApiError(
                "Unable to discover OpenAPI document because the site returned a Cloudflare challenge page. "
                "Point COLECTICA_BASE_URL at a direct API/OpenAPI endpoint, or ask the site owner to allow "
                "server-side requests. Tried {paths}. Last error: {error}".format(
                    paths=OPENAPI_CANDIDATE_PATHS,
                    error=last_error,
                )
            )

        raise ColecticaApiError(
            f"Unable to discover OpenAPI document. Tried {OPENAPI_CANDIDATE_PATHS}. Last error: {last_error}"
        )

    @staticmethod
    def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
        if not ref.startswith("#/"):
            raise ColecticaApiError(f"Unsupported $ref format: {ref}")
        node: Any = spec
        for part in ref[2:].split("/"):
            if not isinstance(node, dict) or part not in node:
                raise ColecticaApiError(f"Unable to resolve $ref: {ref}")
            node = node[part]
        if not isinstance(node, dict):
            raise ColecticaApiError(f"Resolved $ref is not an object: {ref}")
        return node

    def _resolve_parameter_spec(self, spec: dict[str, Any], parameter: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in parameter and isinstance(parameter["$ref"], str):
            return self._resolve_ref(spec, parameter["$ref"])
        return parameter

    def _collect_parameters(self, spec: dict[str, Any], operation: OperationRef) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        path_parameters = operation.path_spec.get("parameters", [])
        operation_parameters = operation.operation_spec.get("parameters", [])
        for raw_param in [*path_parameters, *operation_parameters]:
            if not isinstance(raw_param, dict):
                continue
            collected.append(self._resolve_parameter_spec(spec, raw_param))
        return collected

    def _resolve_request_body_spec(
        self,
        spec: dict[str, Any],
        operation_spec: dict[str, Any],
    ) -> dict[str, Any] | None:
        request_body = operation_spec.get("requestBody")
        if not isinstance(request_body, dict):
            return None
        if "$ref" in request_body and isinstance(request_body["$ref"], str):
            return self._resolve_ref(spec, request_body["$ref"])
        return request_body

    @staticmethod
    def synthesize_operation_id(method: str, path: str) -> str:
        normalized_method = re.sub(r"[^A-Za-z0-9]", "_", method.upper())
        normalized_path = re.sub(r"[^A-Za-z0-9]", "_", path)
        normalized_path = re.sub(r"_+", "_", normalized_path).strip("_")
        return f"{normalized_method}_{normalized_path}"

    async def _operation_index(self, auth_mode: AuthMode) -> dict[str, OperationRef]:
        cache_entry = self._operation_index_cache.get(auth_mode)
        now = time.monotonic()
        if cache_entry and cache_entry[0] > now:
            return cache_entry[1]

        _, spec = await self.discover_openapi(auth_mode=auth_mode)
        index: dict[str, OperationRef] = {}
        for path, path_item in spec.get("paths", {}).items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if not isinstance(operation, dict):
                    continue
                operation_id = operation.get("operationId") or self.synthesize_operation_id(str(method), str(path))
                index[str(operation_id)] = OperationRef(
                    operation_id=str(operation_id),
                    method=str(method).upper(),
                    path=str(path),
                    path_spec=path_item,
                    operation_spec=operation,
                )

        if self._openapi_cache_ttl_seconds > 0:
            self._operation_index_cache[auth_mode] = (now + self._openapi_cache_ttl_seconds, index)

        return index

    async def list_operations(self, auth_mode: AuthMode = "auto") -> list[dict[str, str]]:
        index = await self._operation_index(auth_mode=auth_mode)
        operations: list[dict[str, str]] = []
        for operation_id, operation in index.items():
            operations.append(
                {
                    "operation_id": operation_id,
                    "method": operation.method,
                    "path": operation.path,
                }
            )
        operations.sort(key=lambda item: item["operation_id"])
        return operations

    async def call_operation(
        self,
        operation_id: str,
        arguments: dict[str, Any] | None = None,
        *,
        auth_mode: AuthMode = "auto",
    ) -> dict[str, Any]:
        args = arguments or {}
        _, spec = await self.discover_openapi(auth_mode=auth_mode)
        operation_index = await self._operation_index(auth_mode=auth_mode)
        operation_ref = operation_index.get(operation_id)
        if not operation_ref:
            raise ColecticaApiError(f"operationId '{operation_id}' was not found in the OpenAPI document.")
        operation_spec = operation_ref.operation_spec

        path = operation_ref.path
        query_params: dict[str, Any] = {}
        headers: dict[str, str] = {}

        for parameter in self._collect_parameters(spec, operation_ref):
            name = parameter.get("name")
            location = parameter.get("in")
            if not name or name not in args:
                continue
            value = args[name]
            if location == "path":
                path = path.replace(f"{{{name}}}", quote(str(value), safe=""))
            elif location == "query":
                query_params[name] = value
            elif location == "header":
                headers[name] = str(value)

        body = args.get("body")
        request_body_spec = self._resolve_request_body_spec(spec, operation_spec)

        content_type = args.get("content_type")
        if content_type is not None:
            content_type = str(content_type)

        if request_body_spec and body is None and request_body_spec.get("required"):
            raise ColecticaApiError(f"operationId '{operation_id}' requires request body arguments.body")

        if request_body_spec and body is not None:
            content = request_body_spec.get("content")
            if isinstance(content, dict) and content:
                if content_type is None:
                    content_type = "application/json" if "application/json" in content else str(next(iter(content)))
                if content_type not in content:
                    raise ColecticaApiError(
                        f"operationId '{operation_id}' does not accept content_type '{content_type}'. "
                        f"Allowed: {list(content.keys())}"
                    )
            elif content_type is None:
                content_type = "application/json"

        json_body: Any = None
        form_body: dict[str, Any] | None = None
        if body is not None:
            if content_type in {"application/x-www-form-urlencoded", "multipart/form-data"}:
                if not isinstance(body, dict):
                    raise ColecticaApiError(
                        f"operationId '{operation_id}' with content_type '{content_type}' requires arguments.body as object"
                    )
                form_body = body
            else:
                json_body = body

        if content_type:
            headers.setdefault("Content-Type", content_type)

        return await self._request(
            operation_ref.method,
            path,
            auth_mode=auth_mode,
            params=query_params or None,
            json_body=json_body,
            form_body=form_body,
            headers=headers or None,
        )

    async def operation_details(self, operation_id: str, auth_mode: AuthMode = "auto") -> dict[str, Any]:
        _, spec = await self.discover_openapi(auth_mode=auth_mode)
        operation_index = await self._operation_index(auth_mode=auth_mode)
        operation_ref = operation_index.get(operation_id)
        if not operation_ref:
            raise ColecticaApiError(f"operationId '{operation_id}' was not found in the OpenAPI document.")

        operation_spec = operation_ref.operation_spec
        request_body_spec = self._resolve_request_body_spec(spec, operation_spec)

        parameters: list[dict[str, Any]] = []
        for param in self._collect_parameters(spec, operation_ref):
            parameters.append(
                {
                    "name": param.get("name"),
                    "in": param.get("in"),
                    "required": bool(param.get("required", False)),
                    "schema": param.get("schema"),
                    "description": param.get("description"),
                }
            )

        request_body: dict[str, Any] | None = None
        if request_body_spec:
            content_types = []
            content = request_body_spec.get("content")
            if isinstance(content, dict):
                content_types = list(content.keys())
            request_body = {
                "required": bool(request_body_spec.get("required", False)),
                "content_types": content_types,
                "description": request_body_spec.get("description"),
            }

        return {
            "operation_id": operation_id,
            "method": operation_ref.method,
            "path": operation_ref.path,
            "summary": operation_spec.get("summary"),
            "description": operation_spec.get("description"),
            "tags": operation_spec.get("tags", []),
            "parameters": parameters,
            "request_body": request_body,
            "responses": operation_spec.get("responses", {}),
        }

    @staticmethod
    def _extract_items(body: Any, items_path: str | None = None) -> list[Any] | None:
        if isinstance(body, list):
            return body
        if not isinstance(body, dict):
            return None

        if items_path:
            node: Any = body
            for part in items_path.split("."):
                if not isinstance(node, dict) or part not in node:
                    return None
                node = node[part]
            if isinstance(node, list):
                return node
            return None

        for key in ("items", "results", "value", "data"):
            value = body.get(key)
            if isinstance(value, list):
                return value

        return None

    @staticmethod
    def _extract_next_token(body: Any, headers: dict[str, Any]) -> str | None:
        header_candidates = (
            "x-continuation-token",
            "continuation-token",
            "x-next-token",
            "x-next-cursor",
        )
        lowered_headers = {str(k).lower(): v for k, v in headers.items()}
        for key in header_candidates:
            value = lowered_headers.get(key)
            if value:
                return str(value)

        if not isinstance(body, dict):
            return None

        key_candidates = (
            "nextResult",
            "nextToken",
            "continuationToken",
            "continuation",
            "next",
            "cursor",
        )
        for key in key_candidates:
            value = body.get(key)
            if value:
                return str(value)

        for nested_key in ("paging", "meta"):
            nested = body.get(nested_key)
            if isinstance(nested, dict):
                for key in key_candidates:
                    value = nested.get(key)
                    if value:
                        return str(value)

        next_link = body.get("@odata.nextLink") or body.get("nextLink")
        if isinstance(next_link, str) and next_link:
            parsed = urlparse(next_link)
            query = parse_qs(parsed.query)
            for query_key in ("$skiptoken", "skiptoken", "continuationToken", "nextToken", "cursor"):
                values = query.get(query_key)
                if values and values[0]:
                    return str(values[0])
            return next_link

        return None

    def _infer_token_parameter_name(
        self,
        spec: dict[str, Any],
        operation_ref: OperationRef,
        args: dict[str, Any],
    ) -> str | None:
        query_param_names: list[str] = []
        for parameter in self._collect_parameters(spec, operation_ref):
            if parameter.get("in") == "query" and isinstance(parameter.get("name"), str):
                query_param_names.append(str(parameter["name"]))

        for arg_name in args:
            if arg_name in query_param_names and "token" in arg_name.lower():
                return arg_name

        preferred = (
            "continuationToken",
            "nextToken",
            "cursor",
            "skiptoken",
            "$skiptoken",
            "pageToken",
            "offset",
            "skip",
            "page",
        )
        lowered = {name.lower(): name for name in query_param_names}
        for candidate in preferred:
            match = lowered.get(candidate.lower())
            if match:
                return match

        return None

    @staticmethod
    def _infer_body_token_field(args: dict[str, Any]) -> str | None:
        body = args.get("body")
        if not isinstance(body, dict):
            return None

        preferred = (
            "nextResult",
            "continuationToken",
            "nextToken",
            "cursor",
            "offset",
            "skip",
            "page",
        )
        for candidate in preferred:
            if candidate in body:
                return candidate

        # Colectica Search/AdvancedSearch commonly use nextResult in body.
        return "nextResult"

    async def call_operation_paginated(
        self,
        operation_id: str,
        arguments: dict[str, Any] | None = None,
        *,
        auth_mode: AuthMode = "auto",
        max_pages: int = 20,
        items_path: str | None = None,
    ) -> dict[str, Any]:
        if max_pages < 1:
            raise ColecticaApiError("max_pages must be >= 1")

        args = copy.deepcopy(arguments or {})
        _, spec = await self.discover_openapi(auth_mode=auth_mode)
        operation_index = await self._operation_index(auth_mode=auth_mode)
        operation_ref = operation_index.get(operation_id)
        if not operation_ref:
            raise ColecticaApiError(f"operationId '{operation_id}' was not found in the OpenAPI document.")

        token_arg_name = self._infer_token_parameter_name(spec, operation_ref, args)
        body_token_field = self._infer_body_token_field(args)
        items: list[Any] = []
        pages: list[dict[str, Any]] = []
        next_token: str | None = None

        for page_index in range(max_pages):
            page_result = await self.call_operation(operation_id, arguments=args, auth_mode=auth_mode)
            page_body = page_result.get("body")
            page_headers = page_result.get("headers", {})
            page_items = self._extract_items(page_body, items_path=items_path)
            if page_items is not None:
                items.extend(page_items)

            next_token = self._extract_next_token(page_body, page_headers if isinstance(page_headers, dict) else {})

            pages.append(
                {
                    "page": page_index + 1,
                    "status_code": page_result.get("status_code"),
                    "item_count": len(page_items) if page_items is not None else None,
                    "has_next_token": bool(next_token),
                }
            )

            if not next_token:
                break

            if token_arg_name:
                args[token_arg_name] = next_token
                continue

            if body_token_field and isinstance(args.get("body"), dict):
                args["body"][body_token_field] = next_token
                continue

            if not token_arg_name and not body_token_field:
                break

        return {
            "operation_id": operation_id,
            "pages_fetched": len(pages),
            "max_pages": max_pages,
            "token_parameter": token_arg_name,
            "body_token_field": body_token_field,
            "stopped_with_next_token": bool(next_token and len(pages) >= max_pages),
            "items_count": len(items),
            "items": items,
            "pages": pages,
        }
