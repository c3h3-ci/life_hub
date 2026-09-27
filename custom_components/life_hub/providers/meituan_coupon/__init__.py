"""美团红包助手 provider — 纯 Python 直连 peppermall.meituan.com。
支持 HA 配置向导两步登录：输手机号→发验证码→输验证码→自动拿 token。
"""

from __future__ import annotations

import hashlib
import logging
import ssl
from datetime import datetime, timezone, timedelta
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigSubentryFlow, SubentryFlowResult
from homeassistant.core import HomeAssistant

from ..base import ProviderSpec
from ...models import ProviderRuntime

_LOGGER = logging.getLogger(__name__)

PROVIDER_KEY = "meituan_coupon"
PROVIDER_NAME = "美团红包助手"

BASE_URL = "https://peppermall.meituan.com"
SUB_CHANNEL_CODE = "6511ba14351d4bbc8957722912b4c2d6"

SMS_SEND_PATH = "/eds/claw/login/sms/code/get"
SMS_VERIFY_PATH = "/eds/claw/login/sms/code/verify"
TOKEN_VERIFY_PATH = "/eds/claw/login/token/verify"
ISSUE_PATH = "/eds/standard/equity/pkg/issue/claw"

_UTC8 = timezone(timedelta(hours=8))


def _make_ssl_session(hass: HomeAssistant) -> aiohttp.ClientSession:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = aiohttp.TCPConnector(ssl=ctx)
    return aiohttp.ClientSession(connector=conn)


def _gen_redeem_code(user_token: str, phone_masked: str, date_str: str) -> str:
    raw = f"{user_token}_{phone_masked}_{date_str}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def build_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required("user_token", default=current.get("user_token", "")): str,
    })


async def validate_config(hass: HomeAssistant, data: dict[str, Any]) -> None:
    token = data.get("user_token", "")
    if not token:
        raise ValueError("user_token 必填")
    async with _make_ssl_session(hass) as session:
        try:
            async with session.post(
                f"{BASE_URL}{TOKEN_VERIFY_PATH}",
                params={"token": token},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                body = await resp.json()
                if body.get("code") != 0:
                    raise ValueError(f"Token 无效: {body.get('message', '')}")
        except ValueError:
            raise
        except Exception as err:
            raise ValueError(f"验证失败: {err}") from err


async def setup_provider(
    hass: HomeAssistant,
    config: dict[str, Any],
    subentry_id: str,
) -> ProviderRuntime:
    token = config["user_token"]
    phone_masked = config.get("phone_masked", "")
    session = _make_ssl_session(hass)
    status = "connected"
    client = MeituanCouponClient(session, token, phone_masked)

    async def stop():
        await session.close()

    def get_status():
        return status

    async def _health_check():
        nonlocal status
        try:
            async with session.post(f"{BASE_URL}{TOKEN_VERIFY_PATH}", params={"token": token},
                timeout=aiohttp.ClientTimeout(total=10)) as resp:
                body = await resp.json()
                valid = body.get("code") == 0
                status = "connected" if valid else "disconnected"
                return valid
        except Exception:
            status = "disconnected"
            return False

    return ProviderRuntime(
        key=PROVIDER_KEY, title=PROVIDER_NAME, subentry_id=subentry_id,
        client=client, stop=stop, status=get_status, status_check=_health_check,
    )


class MeituanCouponClient:
    """美团红包助手客户端。"""

    def __init__(self, session: aiohttp.ClientSession, token: str, phone_masked: str):
        self._session = session
        self._token = token
        self._phone_masked = phone_masked

    async def _post(self, path: str, body: dict) -> dict:
        async with self._session.post(f"{BASE_URL}{path}", json=body,
            headers={"Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def ping(self) -> bool:
        async with self._session.post(f"{BASE_URL}{TOKEN_VERIFY_PATH}",
            params={"token": self._token}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            return (await resp.json()).get("code") == 0

    async def claim_coupons(self) -> dict:
        today = datetime.now(_UTC8).strftime("%Y%m%d")
        body = {
            "subChannelCode": SUB_CHANNEL_CODE,
            "token": self._token,
            "equityPkgRedeemCode": _gen_redeem_code(self._token, self._phone_masked, today),
        }
        return await self._post(ISSUE_PATH, body)

    _METHODS: dict[str, callable] | None = None

    def _get_methods(self) -> dict:
        if self._METHODS is None:
            type(self)._METHODS = {
                "claim_coupons": lambda p: self.claim_coupons(),
                "ping": lambda p: self.ping(),
            }
        return self._METHODS

    async def call_method(self, method: str, params: dict | None = None) -> dict:
        handler = self._get_methods().get(method)
        if handler is None:
            raise ValueError(f"未知方法: {method}")
        return await handler(params or {})


# ================ 配置流（两步 SMS 登录）================

async def _finish_flow(flow: ConfigSubentryFlow, data: dict) -> SubentryFlowResult:
    """保存配置并重载。"""
    entry_id = flow._entry_id
    entry = flow.hass.config_entries.async_get_known_entry(entry_id)
    if flow.source == "user":
        result = flow.async_create_entry(title="美团红包助手", data=data)
    else:
        sub = flow._get_reconfigure_subentry()
        result = flow.async_update_and_abort(entry, sub, data=data)
    flow.hass.async_create_task(
        flow.hass.config_entries.async_reload(entry.entry_id),
        "life_hub_reload_after_config",
    )
    return result


def _build_flow_handler() -> type[ConfigSubentryFlow]:
    """构建带有两步 SMS 登录的流动处理器。"""

    async def async_step_user(self, user_input=None):
        return await async_step_sms_login(self, user_input)

    async def async_step_reconfigure(self, user_input=None):
        return await async_step_sms_login(self, user_input)

    async def async_step_sms_login(self, user_input=None):
        errors = {}
        if user_input is not None:
            phone = user_input.get("phone", "")
            try:
                raw = f"{phone}{int(datetime.now(_UTC8).timestamp() * 1000)}0"
                device_token = hashlib.md5(raw.encode()).hexdigest()
                async with _make_ssl_session(self.hass) as session:
                    async with session.post(f"{BASE_URL}{SMS_SEND_PATH}",
                        json={"mobile": phone, "uuid": device_token},
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        result = await resp.json()
                if result.get("code") != 0:
                    raise ValueError(result.get("message", "发送失败"))
                device_token = result.get("uuid", device_token)
                self._ctx = {
                    "phone": phone,
                    "device_token": device_token,
                    "phone_masked": phone[:3] + "****" + phone[-4:],
                }
                return await async_step_verify_code(self)
            except ValueError as e:
                errors["base"] = str(e)
            except Exception as e:
                errors["base"] = f"发送失败: {e}"
        return self.async_show_form(
            step_id="sms_login",
            data_schema=vol.Schema({vol.Required("phone"): str}),
            errors=errors,
            description_placeholders={},
        )

    async def async_step_verify_code(self, user_input=None):
        errors = {}
        ctx = getattr(self, "_ctx", {})
        if user_input is not None:
            code = user_input.get("code", "")
            try:
                async with _make_ssl_session(self.hass) as session:
                    async with session.post(f"{BASE_URL}{SMS_VERIFY_PATH}",
                        json={
                            "mobile": ctx["phone"],
                            "smsVerifyCode": code,
                            "uuid": ctx["device_token"],
                        },
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        result = await resp.json()
                if result.get("code") != 0:
                    raise ValueError(result.get("message", "验证码错误"))
                user_token = result.get("data", {}).get("token", "")
                if not user_token:
                    raise ValueError("验证成功但未获取到 token")
                data = {"user_token": user_token, "phone_masked": ctx["phone_masked"]}
                return await _finish_flow(self, data)
            except ValueError as e:
                errors["base"] = str(e)
            except Exception as e:
                errors["base"] = f"验证失败: {e}"
        return self.async_show_form(
            step_id="verify_code",
            data_schema=vol.Schema({vol.Required("code"): str}),
            errors=errors,
            description_placeholders={"phone": ctx.get("phone_masked", "")},
        )

    return type(
        "CouponSubentryFlow",
        (ConfigSubentryFlow,),
        {
            "async_step_user": async_step_user,
            "async_step_reconfigure": async_step_reconfigure,
            "async_step_sms_login": async_step_sms_login,
            "async_step_verify_code": async_step_verify_code,
        },
    )


PROVIDER_SPEC = ProviderSpec(
    key=PROVIDER_KEY,
    name=PROVIDER_NAME,
    schema_builder=build_schema,
    validate_config=validate_config,
    setup_provider=setup_provider,
    flow_handler=_build_flow_handler(),
    allow_multiple=True,
)
