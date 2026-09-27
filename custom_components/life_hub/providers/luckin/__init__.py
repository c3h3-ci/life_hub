"""Luckin Coffee MCP provider for Life Hub.

瑞幸咖啡 AI 开放平台 MCP Server.
MCP 端点: https://gwmcp.lkcoffee.com/order/user/mcp
认证: Bearer token（从 https://open.lkcoffee.com/mcp 获取）
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..base import ProviderSpec
from ..base_client import McpClientBase
from ...models import ProviderRuntime

_LOGGER = logging.getLogger(__name__)

PROVIDER_KEY = "luckin"
PROVIDER_NAME = "瑞幸咖啡"

LUCKIN_MCP_ENDPOINT = "https://gwmcp.lkcoffee.com/order/user/mcp"


def build_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required("api_token", default=current.get("api_token", "")): str,
        vol.Optional("refresh_interval", default=current.get("refresh_interval", 30)): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=1440)
        ),
    })


async def validate_config(hass: HomeAssistant, data: dict[str, Any]) -> None:
    token = data.get("api_token", "")
    if not token:
        raise ValueError("api_token is required（从 https://open.lkcoffee.com/mcp 获取）")
    session = async_get_clientsession(hass)
    try:
        async with session.post(
            LUCKIN_MCP_ENDPOINT,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 401:
                raise ValueError("Invalid API token")
            resp.raise_for_status()
            body = await resp.json()
            if body.get("error"):
                raise ValueError(f"MCP API error: {body['error'].get('message', 'unknown')}")
    except ValueError:
        raise
    except Exception as err:
        raise ValueError(f"Connection failed: {err}") from err


async def setup_provider(
    hass: HomeAssistant,
    config: dict[str, Any],
    subentry_id: str,
) -> ProviderRuntime:
    token = config["api_token"]
    session = async_get_clientsession(hass)
    _status = "connected"

    client = LuckinClient(session, token)

    async def stop() -> None:
        pass

    def get_status() -> str:
        return _status

    async def _health_check() -> bool:
        nonlocal _status
        try:
            ok = await client.health_check()
            _status = "connected" if ok else "disconnected"
            return ok
        except Exception:
            _status = "disconnected"
            return False

    return ProviderRuntime(
        key=PROVIDER_KEY, title=PROVIDER_NAME, subentry_id=subentry_id,
        client=client, stop=stop, status=get_status, status_check=_health_check,
    )


class LuckinClient(McpClientBase):
    def __init__(self, session: aiohttp.ClientSession, token: str) -> None:
        super().__init__(session, LUCKIN_MCP_ENDPOINT)
        self._token = token

    def _build_headers(self, body: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }


PROVIDER_SPEC = ProviderSpec(
    key=PROVIDER_KEY,
    name=PROVIDER_NAME,
    schema_builder=build_schema,
    validate_config=validate_config,
    setup_provider=setup_provider,
    allow_multiple=True,
)
