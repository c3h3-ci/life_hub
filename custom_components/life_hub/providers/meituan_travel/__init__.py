"""美团旅行 provider for Life Hub（基于美团旅行官方 API）。"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..base import ProviderSpec
from ...models import ProviderRuntime

_LOGGER = logging.getLogger(__name__)

PROVIDER_KEY = "meituan_travel"
PROVIDER_NAME = "美团旅行"

MEITUAN_TRAVEL_API = "https://mcp-open-cater.meituan.com/v1/api/voyage/openapi/query"


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
        raise ValueError("api_token is required（请前往 developer.meituan.com 创建 Token）")
    session = async_get_clientsession(hass)
    try:
        async with session.post(
            MEITUAN_TRAVEL_API,
            headers={"Authorization": token, "Content-Type": "application/json"},
            json={"city": "北京", "query": "ping"},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            body = await resp.json()
            if body.get("code") != 0:
                raise ValueError(f"API 验证失败: {body.get('msg', '未知错误')}")
    except ValueError:
        raise
    except Exception as err:
        raise ValueError(f"连接失败: {err}") from err


async def setup_provider(
    hass: HomeAssistant,
    config: dict[str, Any],
    subentry_id: str,
) -> ProviderRuntime:
    token = config["api_token"]
    session = async_get_clientsession(hass)
    status = "connected"

    client = MeituanTravelClient(session, token)

    async def stop() -> None:
        pass

    def get_status() -> str:
        return status

    async def _health_check() -> bool:
        try:
            await client.ping()
            return True
        except Exception:
            return False

    return ProviderRuntime(
        key=PROVIDER_KEY, title=PROVIDER_NAME, subentry_id=subentry_id,
        client=client, stop=stop, status=get_status, status_check=_health_check,
    )


class MeituanTravelClient:
    """美团旅行客户端——对接美团官方旅行 API。"""

    def __init__(self, session: aiohttp.ClientSession, token: str) -> None:
        self._session = session
        self._token = token
        self._headers = {"Authorization": token, "Content-Type": "application/json"}

    async def _query(self, city: str, query: str) -> dict:
        async with self._session.post(
            MEITUAN_TRAVEL_API,
            headers=self._headers,
            json={"city": city, "query": query},
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            body = await resp.json()
            return body

    async def ping(self) -> bool:
        resp = await self._query("北京", "ping")
        return resp.get("code") == 0

    async def query(self, query: str, city: str = "北京") -> dict:
        """通用查询——支持预订、比价、查攻略等任意自然语言请求"""
        return await self._query(city, query)

    async def search_hotel(self, query: str, city: str = "北京") -> dict:
        return await self._query(city, f"搜索酒店：{query}")

    async def search_flight(self, origin: str, destination: str, dep_date: str = "") -> dict:
        q = f"搜索机票：从{origin}到{destination}"
        if dep_date:
            q += f"，出发日期{dep_date}"
        return await self._query("北京", q)

    async def search_train(self, origin: str, destination: str, dep_date: str = "") -> dict:
        q = f"搜索火车票：从{origin}到{destination}"
        if dep_date:
            q += f"，出发日期{dep_date}"
        return await self._query("北京", q)

    async def search_poi(self, city: str, keyword: str) -> dict:
        return await self._query(city, f"搜索景点：{keyword}")

    async def plan_itinerary(self, city: str, days: int = 3, budget: int = 0) -> dict:
        q = f"规划行程：{city}，{days}天"
        if budget:
            q += f"，预算{budget}元"
        return await self._query(city, q)

    async def get_travel_orders(self) -> dict:
        return await self._query("北京", "查询旅行订单")


PROVIDER_SPEC = ProviderSpec(
    key=PROVIDER_KEY,
    name=PROVIDER_NAME,
    schema_builder=build_schema,
    validate_config=validate_config,
    setup_provider=setup_provider,
    docs_url="https://qclaw.qq.com/docs/meituan-travel",
    token_url="https://developer.meituan.com/zh/v2/dev/token",
    help_text="前往 developer.meituan.com 创建 API Token 后填入",
    allow_multiple=True,
)
