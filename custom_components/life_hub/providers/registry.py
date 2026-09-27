"""Provider registry with explicit imports."""

from __future__ import annotations

from functools import lru_cache

from ..provider_flow import build_simple_provider_flow
from .base import ProviderSpec
from .meituan import PROVIDER_SPEC as MEITUAN_PROVIDER_SPEC
from .meituan_travel import PROVIDER_SPEC as MEITUAN_TRAVEL_PROVIDER_SPEC
from .ctrip import PROVIDER_SPEC as CTRIP_PROVIDER_SPEC
from .mcdonalds import PROVIDER_SPEC as MCDONALDS_PROVIDER_SPEC
from .yiming import PROVIDER_SPEC as YIMING_PROVIDER_SPEC
from .baidu_map import PROVIDER_SPEC as BAIDU_MAP_PROVIDER_SPEC
from .music import PROVIDER_SPEC as MUSIC_PROVIDER_SPEC
from .fliggy import PROVIDER_SPEC as FLIGGY_PROVIDER_SPEC
from .gaode import PROVIDER_SPEC as GAODE_PROVIDER_SPEC
from .didi import PROVIDER_SPEC as DIDI_PROVIDER_SPEC
from .luckin import PROVIDER_SPEC as LUCKIN_PROVIDER_SPEC
from .meituan_paotui import PROVIDER_SPEC as MEITUAN_PAOTUI_PROVIDER_SPEC
from .meituan_coupon import PROVIDER_SPEC as MEITUAN_COUPON_PROVIDER_SPEC


# 历史 subentry 命名兼容：旧版 life_hub 把美团旅行拆成 meituan_travel，
# 当前代码统一注册为 meituan。
SUBENTRY_TYPE_ALIASES: dict[str, str] = {
    "meituan_travel": "meituan",
}


_PROVIDER_SPECS: tuple[ProviderSpec, ...] = (
    MEITUAN_PROVIDER_SPEC,
    MEITUAN_TRAVEL_PROVIDER_SPEC,
    CTRIP_PROVIDER_SPEC,
    MCDONALDS_PROVIDER_SPEC,
    YIMING_PROVIDER_SPEC,
    BAIDU_MAP_PROVIDER_SPEC,
    GAODE_PROVIDER_SPEC,
    MUSIC_PROVIDER_SPEC,
    FLIGGY_PROVIDER_SPEC,
    DIDI_PROVIDER_SPEC,
    LUCKIN_PROVIDER_SPEC,
    MEITUAN_PAOTUI_PROVIDER_SPEC,
    MEITUAN_COUPON_PROVIDER_SPEC,
)


@lru_cache(maxsize=1)
def get_provider_specs() -> dict[str, ProviderSpec]:
    """Return all registered provider specs."""
    return {spec.key: spec for spec in _PROVIDER_SPECS}


def get_provider_spec(subentry_type: str) -> ProviderSpec | None:
    """Return a single provider spec, resolving historical subentry aliases.

    Returns None when neither the type nor its alias matches a registered spec.
    """
    specs = get_provider_specs()
    spec = specs.get(subentry_type)
    if spec is None:
        alias = SUBENTRY_TYPE_ALIASES.get(subentry_type)
        if alias:
            spec = specs.get(alias)
    return spec


@lru_cache(maxsize=1)
def get_provider_flow_handlers() -> dict[str, type]:
    """Return subentry flow handlers for all providers (incl. historical aliases)."""
    handlers: dict[str, type] = {}
    for key, spec in get_provider_specs().items():
        handler = spec.flow_handler or build_simple_provider_flow(spec)
        setattr(handler, "_provider_spec", spec)
        handlers[key] = handler
    # 兼容历史 subentry 命名（如 meituan_travel / meituan_order），
    # 让旧 subentry 在 reconfigure 时也能找到对应的 flow handler。
    for alias, real in SUBENTRY_TYPE_ALIASES.items():
        if real in handlers and alias not in handlers:
            handlers[alias] = handlers[real]
    return handlers