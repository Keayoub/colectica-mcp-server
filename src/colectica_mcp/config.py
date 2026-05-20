# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Transport = Literal["stdio", "streamable-http"]
AuthMode = Literal["auto", "basic", "bearer", "none"]


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ColecticaConfig:
    base_url: str
    timeout_seconds: float
    verify_ssl: bool
    username: str | None
    password: str | None
    bearer_token: str | None
    transport: Transport
    mount_path: str | None

    @classmethod
    def from_env(cls) -> "ColecticaConfig":
        base_url = os.getenv("COLECTICA_BASE_URL", "").strip()
        if not base_url:
            raise ValueError("COLECTICA_BASE_URL is required.")

        transport = os.getenv("COLECTICA_MCP_TRANSPORT", "stdio").strip().lower()
        if transport not in {"stdio", "streamable-http"}:
            raise ValueError("COLECTICA_MCP_TRANSPORT must be 'stdio' or 'streamable-http'.")

        timeout_raw = os.getenv("COLECTICA_TIMEOUT_SECONDS", "30").strip()
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise ValueError("COLECTICA_TIMEOUT_SECONDS must be numeric.") from exc

        typed_transport: Transport = "streamable-http" if transport == "streamable-http" else "stdio"

        return cls(
            base_url=base_url.rstrip("/"),
            timeout_seconds=timeout_seconds,
            verify_ssl=_as_bool(os.getenv("COLECTICA_VERIFY_SSL"), True),
            username=os.getenv("COLECTICA_USERNAME"),
            password=os.getenv("COLECTICA_PASSWORD"),
            bearer_token=os.getenv("COLECTICA_BEARER_TOKEN"),
            transport=typed_transport,
            mount_path=os.getenv("COLECTICA_MCP_MOUNT_PATH"),
        )

