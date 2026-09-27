"""Baidu Maps provider for Life Hub — 使用百度 Agent Plan API (baidu-ai-map).

配置方式：
1. 前往 https://lbs.baidu.com/apiconsole/agentplan 申请 BAIDU_MAP_AUTH_TOKEN
2. 在添加子条目时填入 token（sk-ap- 开头）
"""
from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..base import ProviderSpec
from ...models import ProviderRuntime

_LOGGER = logging.getLogger(__name__)

PROVIDER_KEY = "baidu_map"
PROVIDER_NAME = "百度地图"

BAIDU_MAP_API_BASE = "https://api.map.baidu.com"
AGENT_PLAN_BASE = f"{BAIDU_MAP_API_BASE}/agent_plan/v1"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def build_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required("auth_token", default=current.get("auth_token", "")): str,
        vol.Optional("refresh_interval", default=current.get("refresh_interval", 30)): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=1440)
        ),
    })


async def validate_config(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """验证 token — 调 Agent Plan place 接口测试连通性。"""
    token = data.get("auth_token", "")
    if not token:
        raise ValueError("auth_token is required (BAIDU_MAP_AUTH_TOKEN)")
    if not token.startswith("sk-ap-"):
        raise ValueError("Token 格式错误，应以 sk-ap- 开头")
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            f"{AGENT_PLAN_BASE}/place",
            headers=_headers(token),
            params={"user_raw_request": "测试", "region": "北京"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status == 401:
                raise ValueError("Token 无效 (401 Unauthorized)")
            if resp.status == 403:
                raise ValueError("Token 无权限 (403 Forbidden)")
            resp.raise_for_status()
            body = await resp.json()
            # 正常响应含 answer_type / results 等字段，无 status 字段
            if not isinstance(body, dict):
                raise ValueError(f"API 返回格式异常: {body}")
    except ValueError:
        raise
    except Exception as err:
        raise ValueError(f"连接失败: {err}") from err


async def setup_provider(
    hass: HomeAssistant,
    config: dict[str, Any],
    subentry_id: str,
) -> ProviderRuntime:
    token = config["auth_token"]
    session = async_get_clientsession(hass)
    status = "connected"

    client = BaiduMapClient(session, token)

    async def stop() -> None:
        pass

    def get_status() -> str:
        return status

    async def _health_check() -> bool:
        try:
            await client.search_poi("天安门", "北京")
            return True
        except Exception as err:
            _LOGGER.warning("Baidu Map health check failed: %s", err)
            return False

    return ProviderRuntime(
        key=PROVIDER_KEY, title=PROVIDER_NAME, subentry_id=subentry_id,
        client=client, stop=stop, status=get_status, status_check=_health_check,
    )


class BaiduMapClient:
    """百度地图 Agent Plan API 客户端。"""

    def __init__(self, session: aiohttp.ClientSession, token: str) -> None:
        self._session = session
        self._token = token
        self._headers = _headers(token)

    async def _get(self, path: str, params: dict) -> dict:
        async with self._session.get(
            f"{AGENT_PLAN_BASE}/{path}",
            headers=self._headers,
            params=params,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            text = await resp.text()
            return json.loads(text)

    async def search_poi(self, query: str, region: str = "全国") -> dict:
        """AI 语义搜地点。返回 answer_type + results。"""
        return await self._get("place", {
            "user_raw_request": query,
            "region": region,
        })

    async def geocode(self, address: str, region: str = "") -> dict | None:
        """地理编码: 地址 → 坐标。"""
        params: dict[str, str] = {"address": address}
        if region:
            params["region"] = region
        return await self._get("geocoding", params)

    async def reverse_geocode(self, lat: float, lng: float) -> dict | None:
        """逆地理编码: 坐标 → 地址。"""
        return await self._get("reverse_geocoding", {
            "location": f"{lat},{lng}",
        })

    async def direction(self, user_raw_request: str, location: str = "") -> dict:
        """路线规划。"""
        params: dict[str, str] = {"user_raw_request": user_raw_request}
        if location:
            params["location"] = location
        return await self._get("direction", params)

    async def weather(self, region: str = "", location: str = "") -> dict:
        """天气查询。"""
        params: dict[str, str] = {}
        if region:
            params["region"] = region
        if location:
            params["location"] = location
        return await self._get("weather", params)


PROVIDER_SPEC = ProviderSpec(
    key=PROVIDER_KEY,
    name=PROVIDER_NAME,
    schema_builder=build_schema,
    validate_config=validate_config,
    setup_provider=setup_provider,
    allow_multiple=True,
)
