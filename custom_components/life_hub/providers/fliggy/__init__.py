"""Fliggy (飞猪旅行) provider for Life Hub."""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import logging
import os
import platform
import struct
import time
import uuid
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..base import ProviderSpec
from ..base_client import McpClientBase
from ...models import ProviderRuntime

_LOGGER = logging.getLogger(__name__)

PROVIDER_KEY = "fliggy"
PROVIDER_NAME = "飞猪旅行"

MCP_SERVER_URL = "https://flyai.open.fliggy.com/mcp"
DEFAULT_SIGN_SECRET = "XSbdYnucPARDc9knhD8+X6hxdD1Nh6ZGI6Hadg25kBw="


# ========== Signing/Encryption Functions (from original ha-fliggy) ==========

def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _hmac_sha256_sign(secret: str, data: str) -> str:
    h = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256)
    return base64.urlsafe_b64encode(h.digest()).rstrip(b"=").decode("ascii")


def _bearer_token(api_key: str) -> str:
    key = api_key.strip()
    if key.startswith("Bearer "):
        return key
    return f"Bearer {key}"


_DEVICE_ID: str | None = None


def _get_device_id() -> str:
    """Read (or lazily create) the stable device id. MUST only run off the event loop."""
    global _DEVICE_ID
    if _DEVICE_ID is not None:
        return _DEVICE_ID
    device_id_file = os.path.join(os.path.expanduser("~"), ".flyai", "device-id")
    did: str | None = None
    try:
        os.makedirs(os.path.dirname(device_id_file), exist_ok=True)
        if os.path.exists(device_id_file):
            with open(device_id_file, "r") as f:
                did = f.read().strip()
        if not did:
            did = str(uuid.uuid4())
            with open(device_id_file, "w") as f:
                f.write(did + "\n")
    except Exception:
        did = str(uuid.uuid4())
    _DEVICE_ID = did
    return did


def _get_device_fingerprint() -> dict:
    return {
        "machine": {
            "platform": platform.system().lower(),
            "arch": platform.machine().lower(),
            "cpus": os.cpu_count() or 4,
            "memoryTierGB": 4,
            "osType": platform.system(),
            "nodeVersion": "",
            "osReleaseMajor": "10",
        },
        "fingerprint": {
            "language": "zh",
            "platform": "Windows" if platform.system() == "Windows" else "Linux",
            "userAgent": f"flyai-cli/1.0.6 (HA ConfigFlow; {platform.system()} {platform.machine()})",
            "hardwareConcurrency": os.cpu_count() or 4,
            "deviceMemory": 4,
            "clientSurface": "cli",
            "timezoneOffset": -time.timezone // 60 if time.timezone else -480,
            "deviceId": _sha256_hex(_DEVICE_ID or str(uuid.uuid4())),
        },
    }


def _build_x_ff_ctx(sign_secret: str) -> str:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        raise RuntimeError(
            "飞猪签名需要 cryptography 库，请在 HA 环境中手动安装: "
            "pip install cryptography>=42.0"
        ) from None

    fp = _get_device_fingerprint()
    fp_json = json.dumps(fp, separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(fp_json)
    secret_bytes = _sha256(sign_secret.encode("utf-8"))
    iv = os.urandom(12)
    aesgcm = AESGCM(secret_bytes)
    ciphertext = aesgcm.encrypt(iv, compressed, None)
    result = struct.pack("B", 1) + iv + ciphertext
    return base64.b64encode(result).decode("ascii")


def _sign_request(
    method: str,
    pathname: str,
    body: str,
    authorization: str | None,
    timestamp_ms: str,
    sign_secret: str,
) -> dict[str, str]:
    if not sign_secret:
        return {}
    nonce = os.urandom(16).hex()
    body_hash = _sha256_hex(body)
    auth_header = _bearer_token(authorization or "")
    auth_hash = _sha256_hex(auth_header)
    sign_string = f"{method}\n{pathname}\n{timestamp_ms}\n{nonce}\n{body_hash}\n{auth_hash}"
    signature = _hmac_sha256_sign(sign_secret, sign_string)
    return {
        "x-flyai-sign-ver": "7",
        "x-flyai-sign-alg": "hmac-sha256",
        "x-flyai-ts": timestamp_ms,
        "x-flyai-nonce": nonce,
        "x-flyai-sign": signature,
    }


# ========== Schema & Config ==========

def build_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required("api_key", default=current.get("api_key", "")): str,
        vol.Optional("sign_secret", default=current.get("sign_secret", "")): str,
        vol.Optional("refresh_interval", default=current.get("refresh_interval", 30)): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=1440)
        ),
    })


async def validate_config(hass: HomeAssistant, data: dict[str, Any]) -> None:
    # 离线预读设备指纹文件，避免事件循环里同步 open() 触发 HA 阻塞调用告警
    await hass.async_add_executor_job(_get_device_id)
    api_key = data.get("api_key", "")
    sign_secret = data.get("sign_secret", "") or DEFAULT_SIGN_SECRET
    if not api_key:
        raise ValueError("api_key is required")

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {},
    }
    body = json.dumps(payload, separators=(",", ":"))
    timestamp_ms = str(int(time.time() * 1000))
    auth_header = _bearer_token(api_key)

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": auth_header,
        "x-ff-ctx": _build_x_ff_ctx(sign_secret),
        "x-ttid": "ai2c(sk.clawhub)",
        "User-Agent": f"flyai-cli/1.0.6 (HA ConfigFlow; {platform.system()} {platform.machine()})",
    }
    headers.update(
        _sign_request("POST", "/mcp", body, auth_header, timestamp_ms, sign_secret)
    )

    try:
        session = async_get_clientsession(hass)
        async with session.post(
            MCP_SERVER_URL,
            headers=headers,
            data=body,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 401:
                raise ValueError("Invalid API key")
            resp.raise_for_status()
            result = await resp.json()
            if "error" in result:
                raise ValueError(f"API error: {result['error']}")
            tools = result.get("result", {}).get("tools", [])
            _LOGGER.info("Fliggy MCP tools available: %d", len(tools))
    except ValueError:
        raise
    except Exception as err:
        raise ValueError(f"Connection failed: {err}") from err


# ========== Setup Provider ==========

async def setup_provider(
    hass: HomeAssistant,
    config: dict[str, Any],
    subentry_id: str,
) -> ProviderRuntime:
    api_key = config["api_key"]
    sign_secret = config.get("sign_secret", "") or DEFAULT_SIGN_SECRET
    session = async_get_clientsession(hass)
    # 离线预读设备指纹文件，避免事件循环里同步 open() 触发 HA 阻塞调用告警
    await hass.async_add_executor_job(_get_device_id)
    status = "connected"

    client = FliggyClient(session, api_key, sign_secret)

    async def stop() -> None:
        pass

    def get_status() -> str:
        return status

    async def _health_check() -> bool:
        return await client.health_check()

    return ProviderRuntime(
        key=PROVIDER_KEY, title=PROVIDER_NAME, subentry_id=subentry_id,
        client=client, stop=stop, status=get_status, status_check=_health_check,
    )


# ========== Client ==========

class FliggyClient(McpClientBase):
    def __init__(self, session: aiohttp.ClientSession, api_key: str, sign_secret: str) -> None:
        super().__init__(session, MCP_SERVER_URL)
        self._api_key = api_key
        self._sign_secret = sign_secret

    def _build_headers(self, body: str) -> dict[str, str]:
        auth_header = _bearer_token(self._api_key)
        timestamp_ms = str(int(time.time() * 1000))
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": auth_header,
            "x-ff-ctx": _build_x_ff_ctx(self._sign_secret),
            "x-ttid": "ai2c(sk.clawhub)",
            "User-Agent": f"flyai-cli/1.0.6 (HA ConfigFlow; {platform.system()} {platform.machine()})",
        }
        headers.update(
            _sign_request("POST", "/mcp", body, auth_header, timestamp_ms, self._sign_secret)
        )
        return headers

    async def fast_search(self, query: str) -> dict:
        return await self.call_tool("fliggy_fast_search", {"query": query})

    async def ai_search(self, query: str) -> dict:
        return await self.call_tool("fliggy_ai_search", {"query": query})

    async def search_flight(self, origin: str, destination: str = "", dep_date: str = "", **kwargs) -> dict:
        args = {"origin": origin}
        if destination:
            args["destination"] = destination
        if dep_date:
            args["dep_date"] = dep_date
        return await self.call_tool("search_flight", args)

    async def search_hotel(self, dest_name: str, **kwargs) -> dict:
        """搜酒店。优先使用 fast_search（自然语言）解决县级市 geocode 不准的问题。"""
        # 如果有 check_in/check_out/bed_types 等结构化参数,仍走 search_hotels MCP
        structured_params = {"check_in_date", "check_out_date", "hotel_bed_types", "hotel_stars", "max_price", "sort"}
        if structured_params & set(kwargs.keys()):
            args = {"dest_name": dest_name}
            for k, v in kwargs.items():
                if v:
                    args[k] = v
            return await self.call_tool("search_hotels", args)
        # 否则用 fast_search（自然语言），对县级市更准确
        query = dest_name
        if kwargs.get("key_words"):
            query += kwargs["key_words"]
        return await self.fast_search(query)

    async def search_train(self, origin: str, destination: str = "", dep_date: str = "", **kwargs) -> dict:
        args = {"origin": origin}
        if destination:
            args["destination"] = destination
        if dep_date:
            args["dep_date"] = dep_date
        return await self.call_tool("search_domestic_train", args)

    async def search_poi(self, city_name: str, **kwargs) -> dict:
        args = {"city_name": city_name}
        for k, v in kwargs.items():
            if v:
                args[k] = v
        return await self.call_tool("search_poi", args)

    async def search_marriott_hotel(self, dest_name: str, **kwargs) -> dict:
        args = {"dest_name": dest_name}
        for k, v in kwargs.items():
            if v:
                args[k] = v
        return await self.call_tool("search_marriott_hotels", args)

    async def search_marriott_package(self, dest_name: str, **kwargs) -> dict:
        args = {"dest_name": dest_name}
        for k, v in kwargs.items():
            if v:
                args[k] = v
        return await self.call_tool("search_marriott_packages", args)

    async def get_marriott_info(self, hotel_id: str) -> dict:
        return await self.call_tool("get_marriott_hotel_info", {"hotel_id": hotel_id})


PROVIDER_SPEC = ProviderSpec(
    key=PROVIDER_KEY,
    name=PROVIDER_NAME,
    schema_builder=build_schema,
    validate_config=validate_config,
    setup_provider=setup_provider,
    allow_multiple=True,
)
