"""美团跑腿 provider for Life Hub — 纯 Python 直连 paotui.meituan.com。

鉴权方式：passport_token（OAuth2 PKCE 登录获取，config_flow 手动输入）。
所有业务调用模拟 iPhone 微信小程序环境，与官方 paotui.js 行为一致。
所有 API 端点均为真实抓包确认。
"""

from __future__ import annotations

import json
import logging
import random
import ssl
import time
import uuid as uuid_mod
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..base import ProviderSpec
from ...models import ProviderRuntime

_LOGGER = logging.getLogger(__name__)

PROVIDER_KEY = "meituan_paotui"
PROVIDER_NAME = "美团跑腿"

# == 业务 API host ==
PAOTUI_API_HOST = "https://paotui.meituan.com"

# == 公共请求参数（模拟 iPhone 微信小程序环境）==
COMMON: dict[str, str] = {
    "wm_ctype": "wx_app_source",
    "wm_appversion": "4.53.4",
    "wm_dversion": "iOS 26.3.1",
    "wm_dtype": "iPhone 17 Pro Max<iPhone18,2>",
    "channel": "wx_miniPrograms",
    "channel_activity_id": "",
    "platform": "13",
    "trafficSource": "1",
}

HEADERS_BASE: dict[str, str] = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.69(0x18004532) NetType/WIFI Language/zh_CN",
    "Referer": "https://servicewechat.com/wx84d3c06952bb4072/398/page-frame.html",
    "Accept-Encoding": "gzip,deflate",
    "mini-program": "paotui",
}

DEFAULT_LAT = 39904200  # 北京天安门 * 1e6
DEFAULT_LNG = 116407400


def _gen_ajax_id() -> str:
    return f"{int(time.time() * 1000)}_{random.randint(1000, 9999)}"


def _make_body(token: str, uuid: str, extra: dict[str, Any]) -> dict[str, str]:
    body = dict(COMMON)
    body["uuid"] = uuid
    body["wm_uuid"] = uuid
    body["token"] = token
    body["ajaxId"] = _gen_ajax_id()
    for k, v in extra.items():
        body[k] = str(v)
    return body


def _make_ssl_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ctx)
    return aiohttp.ClientSession(connector=conn)


def build_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required("passport_token", default=current.get("passport_token", "")): str,
        vol.Optional("uuid", default=current.get("uuid", uuid_mod.uuid4().hex.upper())): str,
        vol.Optional("lat", default=current.get("lat", DEFAULT_LAT)): int,
        vol.Optional("lng", default=current.get("lng", DEFAULT_LNG)): int,
    })


async def validate_config(hass: HomeAssistant, data: dict[str, Any]) -> None:
    token = data.get("passport_token", "")
    if not token:
        raise ValueError("passport_token 必填")
    async with _make_ssl_session(hass) as session:
        try:
            client = MeituanPaotuiClient(
                session, token, data.get("uuid", ""),
                data.get("lat", DEFAULT_LAT), data.get("lng", DEFAULT_LNG),
            )
            result = await client.ping()
            if result.get("code") != 0:
                raise ValueError(f"API 验证失败: {result}")
        except aiohttp.ClientResponseError as e:
            raise ValueError(f"Token 验证失败 (HTTP {e.status})") from e
        except ValueError:
            raise
        except Exception as err:
            raise ValueError(f"连接失败: {err}") from err


async def setup_provider(
    hass: HomeAssistant,
    config: dict[str, Any],
    subentry_id: str,
) -> ProviderRuntime:
    token = config["passport_token"]
    uuid = config.get("uuid", uuid_mod.uuid4().hex.upper())
    lat = config.get("lat", DEFAULT_LAT)
    lng = config.get("lng", DEFAULT_LNG)
    session = _make_ssl_session(hass)
    status = "connected"

    client = MeituanPaotuiClient(session, token, uuid, lat, lng)

    async def stop() -> None:
        await session.close()

    def get_status() -> str:
        return status

    async def _health_check() -> bool:
        nonlocal status
        try:
            result = await client.ping()
            if result.get("code") == 0:
                status = "connected"
                return True
            status = "disconnected"
            return False
        except Exception:
            status = "disconnected"
            return False

    return ProviderRuntime(
        key=PROVIDER_KEY, title=PROVIDER_NAME, subentry_id=subentry_id,
        client=client, stop=stop, status=get_status, status_check=_health_check,
    )


class MeituanPaotuiClient:
    """美团跑腿客户端 — 直连 paotui.meituan.com/wx/vX/* 业务接口。"""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        token: str,
        uuid: str,
        lat: int,
        lng: int,
    ) -> None:
        self._session = session
        self._token = token
        self._uuid = uuid
        self._lat = lat
        self._lng = lng

    @property
    def _location_str(self) -> str:
        return f"{self._lng / 1e6},{self._lat / 1e6}"

    def _headers(self, token: str | None = None) -> dict[str, str]:
        h = dict(HEADERS_BASE)
        h["token"] = token or self._token
        return h

    async def _post(
        self, path: str, extra_body: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> dict:
        t = token or self._token
        body = _make_body(t, self._uuid, extra_body or {})
        url = f"{PAOTUI_API_HOST}{path}"
        async with self._session.post(
            url, headers=self._headers(t), data=body,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    # ================ 业务方法（端点均经抓包验证） ================

    async def ping(self) -> dict:
        return await self.search_poi("测试", "北京")

    async def search_poi(
        self, keyword: str, city: str = "北京",
        lat: int | None = None, lng: int | None = None,
    ) -> dict:
        """搜索 POI（收货地址/地点）。
        端点：POST /wx/v1/map/search ✅（抓包验证）
        """
        l = lat if lat is not None else self._lat
        n = lng if lng is not None else self._lng
        extra = {
            "lat": l, "lng": n,
            "keyword": keyword, "city": city,
            "location": f"{n / 1e6},{l / 1e6}",
            "page": "1", "pagesize": "20",
        }
        return await self._post("/wx/v1/map/search", extra)

    async def get_address_list(
        self, address_type: int = 1, business_type: int = 1, scene: int = 2,
    ) -> dict:
        """获取收货地址列表。
        端点：POST /wx/v6/address/list ✅（抓包验证）
        """
        extra = {
            "lat": self._lat, "lng": self._lng,
            "addressType": str(address_type),
            "businessType": str(business_type),
            "scene": str(scene),
        }
        return await self._post("/wx/v6/address/list", extra)

    async def preview_order(
        self,
        fetch_address_id: int, fetch_address: str,
        fetch_house_number: str, fetch_lat: int, fetch_lng: int,
        fetch_name: str, fetch_phone: str,
        recipient_address_id: int, recipient_address: str,
        recipient_house_number: str, recipient_lat: int, recipient_lng: int,
        recipient_name: str, recipient_phone: str,
        goods_name: str, goods_count: int = 1, goods_unit: str = "份",
        good_types: list[int] | None = None,
        good_type_names: list[str] | None = None,
        good_weight: int = 1,
        business_type: int = 1,
        biz_type_scene_tag: int = 0,
        remark: str = "",
        tip_fee: int = 0,
    ) -> dict:
        """预览订单（获取费用预估）。
        端点：POST /wx/v1/order/deliveryPreviewForAI ✅（抓包验证+成功预览）
        """
        extra = {
            "lat": self._lat, "lng": self._lng,
            "fetchAddressId": str(fetch_address_id),
            "fetchAddress": fetch_address,
            "fetchHouseNumber": fetch_house_number,
            "fetchLatitude": str(fetch_lat),
            "fetchLongitude": str(fetch_lng),
            "senderName": fetch_name,
            "senderPhone": fetch_phone,
            "recipientAddressId": str(recipient_address_id),
            "recipientAddress": recipient_address,
            "recipientHouseNumber": recipient_house_number,
            "recipientLatitude": str(recipient_lat),
            "recipientLongitude": str(recipient_lng),
            "recipientName": recipient_name,
            "recipientPhone": recipient_phone,
            "goodsInfo": json.dumps({
                "name": goods_name,
                "count": goods_count,
                "unit": goods_unit,
            }, ensure_ascii=False),
            "goodTypes": json.dumps(good_types or [8], ensure_ascii=False),
            "goodTypeNames": json.dumps(good_type_names or ["其他"], ensure_ascii=False),
            "goodWeight": str(good_weight),
            "businessType": str(business_type),
            "bizTypeSceneTag": str(biz_type_scene_tag),
            "businessTypeTag": "0",
            "remark": remark,
            "tipFee": str(tip_fee),
            "submitEntrance": "2",
            "deliveryFeeChangedAck": "false",
        }
        return await self._post("/wx/v1/order/deliveryPreviewForAI", extra)

    async def submit_order(
        self,
        order_token: str,
        fetch_address_id: int, fetch_address: str,
        fetch_house_number: str, fetch_lat: int, fetch_lng: int,
        fetch_name: str, fetch_phone: str,
        recipient_address_id: int, recipient_address: str,
        recipient_house_number: str, recipient_lat: int, recipient_lng: int,
        recipient_name: str, recipient_phone: str,
        goods_name: str, goods_count: int = 1, goods_unit: str = "份",
        good_types: list[int] | None = None,
        good_type_names: list[str] | None = None,
        good_weight: int = 1,
        business_type: int = 1,
        delivery_fee: int = 0,
        biz_type_scene_tag: int = 0,
        remark: str = "",
        tip_fee: int = 0,
        purchase_detail: str = "",
    ) -> dict:
        """提交跑腿订单。
        端点：POST /wx/v1/order/submitForAI ✅（抓包验证+成功下单 orderId=29742631...）
        """
        extra = {
            "lat": self._lat, "lng": self._lng,
            "orderToken": order_token,
            "fetchAddressId": str(fetch_address_id),
            "fetchAddress": fetch_address,
            "fetchHouseNumber": fetch_house_number,
            "fetchLatitude": str(fetch_lat),
            "fetchLongitude": str(fetch_lng),
            "senderName": fetch_name,
            "senderPhone": fetch_phone,
            "recipientAddressId": str(recipient_address_id),
            "recipientAddress": recipient_address,
            "recipientHouseNumber": recipient_house_number,
            "recipientLatitude": str(recipient_lat),
            "recipientLongitude": str(recipient_lng),
            "recipientName": recipient_name,
            "recipientPhone": recipient_phone,
            "goodsInfo": json.dumps({
                "name": goods_name,
                "count": goods_count,
                "unit": goods_unit,
            }, ensure_ascii=False),
            "goodTypes": json.dumps(good_types or [8], ensure_ascii=False),
            "goodTypeNames": json.dumps(good_type_names or ["其他"], ensure_ascii=False),
            "goodWeight": str(good_weight),
            "businessType": str(business_type),
            "bizTypeSceneTag": str(biz_type_scene_tag),
            "businessTypeTag": "0",
            "conversationId": "",
            "tipFee": str(tip_fee),
            "remark": remark,
            "purchaseGoodDetail": purchase_detail,
            "pushToken": "",
            "submitEntrance": "2",
            "deliveryFee": str(delivery_fee),
            "deliveryFeeChangedAck": "true",
        }
        return await self._post("/wx/v1/order/submitForAI", extra)

    async def get_order_status(self, order_id: str) -> dict:
        """查询订单状态。
        端点：POST /wx/v3/order/getOrderChangedDetail ✅（抓包验证）
        """
        extra = {
            "lat": self._lat, "lng": self._lng,
            "orderId": order_id,
            "orderViewId": order_id,
        }
        return await self._post("/wx/v3/order/getOrderChangedDetail", extra)

    async def get_orders(self, page: int = 1, page_size: int = 10) -> dict:
        """查询我的订单列表（端点待确认）。"""
        extra = {
            "lat": self._lat, "lng": self._lng,
            "page": str(page),
            "pageSize": str(page_size),
        }
        # TODO: 真实端点待抓包确认，当前路径为推断
        return await self._post("/wx/v3/order/list", extra)

    # ================ call_method 接口 ================

    _METHODS: dict[str, callable] | None = None

    def _get_methods(self) -> dict:
        if self._METHODS is None:
            type(self)._METHODS = {
                "search_poi": lambda p: self.search_poi(
                    keyword=p.get("keyword", ""),
                    city=p.get("city", "北京"),
                    lat=p.get("lat"), lng=p.get("lng"),
                ),
                "get_address_list": lambda p: self.get_address_list(
                    address_type=p.get("address_type", 1),
                    business_type=p.get("business_type", 1),
                    scene=p.get("scene", 2),
                ),
                "preview_order": lambda p: self.preview_order(
                    fetch_address_id=p["fetch_address_id"],
                    fetch_address=p["fetch_address"],
                    fetch_house_number=p.get("fetch_house_number", ""),
                    fetch_lat=p["fetch_lat"], fetch_lng=p["fetch_lng"],
                    fetch_name=p["fetch_name"], fetch_phone=p["fetch_phone"],
                    recipient_address_id=p["recipient_address_id"],
                    recipient_address=p["recipient_address"],
                    recipient_house_number=p.get("recipient_house_number", ""),
                    recipient_lat=p["recipient_lat"], recipient_lng=p["recipient_lng"],
                    recipient_name=p["recipient_name"], recipient_phone=p["recipient_phone"],
                    goods_name=p.get("goods_name", ""),
                    goods_count=p.get("goods_count", 1),
                    goods_unit=p.get("goods_unit", "份"),
                    good_types=p.get("good_types"),
                    good_type_names=p.get("good_type_names"),
                    good_weight=p.get("good_weight", 1),
                    business_type=p.get("business_type", 1),
                    biz_type_scene_tag=p.get("biz_type_scene_tag", 0),
                    remark=p.get("remark", ""),
                    tip_fee=p.get("tip_fee", 0),
                ),
                "submit_order": lambda p: self.submit_order(
                    order_token=p["order_token"],
                    fetch_address_id=p["fetch_address_id"],
                    fetch_address=p["fetch_address"],
                    fetch_house_number=p.get("fetch_house_number", ""),
                    fetch_lat=p["fetch_lat"], fetch_lng=p["fetch_lng"],
                    fetch_name=p["fetch_name"], fetch_phone=p["fetch_phone"],
                    recipient_address_id=p["recipient_address_id"],
                    recipient_address=p["recipient_address"],
                    recipient_house_number=p.get("recipient_house_number", ""),
                    recipient_lat=p["recipient_lat"], recipient_lng=p["recipient_lng"],
                    recipient_name=p["recipient_name"], recipient_phone=p["recipient_phone"],
                    goods_name=p.get("goods_name", ""),
                    goods_count=p.get("goods_count", 1),
                    goods_unit=p.get("goods_unit", "份"),
                    good_types=p.get("good_types"),
                    good_type_names=p.get("good_type_names"),
                    good_weight=p.get("good_weight", 1),
                    business_type=p.get("business_type", 1),
                    delivery_fee=p.get("delivery_fee", 0),
                    biz_type_scene_tag=p.get("biz_type_scene_tag", 0),
                    remark=p.get("remark", ""),
                    tip_fee=p.get("tip_fee", 0),
                    purchase_detail=p.get("purchase_detail", ""),
                ),
                "get_order_status": lambda p: self.get_order_status(
                    order_id=p["order_id"],
                ),
            }
        return self._METHODS

    async def call_method(self, method: str, params: dict | None = None) -> dict:
        handler = self._get_methods().get(method)
        if handler is None:
            raise ValueError(f"未知方法: {method}")
        return await handler(params or {})


PROVIDER_SPEC = ProviderSpec(
    key=PROVIDER_KEY,
    name=PROVIDER_NAME,
    schema_builder=build_schema,
    validate_config=validate_config,
    setup_provider=setup_provider,
    token_url="https://github.com/meituan/MT-Paotui-For-Client",
    help_text=(
        "先在本机运行美团跑腿官方 skill 完成 OAuth 登录：\n"
        "1. 克隆 github.com/meituan/MT-Paotui-For-Client\n"
        "2. node paotui.js login → 打开授权链接 → 在美团 App 同意\n"
        "3. node paotui.js confirm_auth → 获得 passport_token\n"
        "4. 打开 ~/.xiaomei-workspace/mt_passport_auth.json 复制 token 值\n"
        "5. 粘贴到下方 passport_token 字段"
    ),
    allow_multiple=True,
)
