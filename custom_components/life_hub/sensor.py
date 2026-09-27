"""Sensor platform for Life Hub.

Generic coordinators (LifeHubCoordinator, ProviderStatusSensor) live here.
Provider-specific sensors (yiming, mcdonalds) are in each provider subpackage.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN
from .models import HubRuntime, ProviderRuntime

_LOGGER = logging.getLogger(__name__)

_DEVICE_MODEL = "Life Hub Provider"
_MANUFACTURER = "Life Hub"

_PROVIDER_ICONS: dict[str, str] = {
    "meituan": "mdi:food",
    "meituan_travel": "mdi:airplane",
    "ctrip": "mdi:bed",
    "mcdonalds": "mdi:hamburger",
    "yiming": "mdi:bottle-soda",
    "baidu_map": "mdi:map",
    "didi": "mdi:car",
    "music": "mdi:music",
    "fliggy": "mdi:airplane",
    "gaode": "mdi:map-marker-radius",
}
_DEFAULT_ICON = "mdi:hub"

from .providers.yiming.sensors import SENSOR_SUFFIXES as YIMING_SUFFIXES
from .providers.mcdonalds.sensors import SENSOR_SUFFIXES as MCD_SUFFIXES
from .providers.meituan.sensors import SENSOR_SUFFIXES as MEITUAN_SUFFIXES
from .providers.baidu_map.sensors import SENSOR_SUFFIXES as BAIDU_MAP_SUFFIXES
from .providers.didi.sensors import SENSOR_SUFFIXES as DIDI_SUFFIXES


def _build_known_sensor_ids(entry: ConfigEntry) -> set[str]:
    """Build set of known valid sensor unique_ids for the entry."""
    valid: set[str] = set()
    for rk, rt in entry.runtime_data.providers.items():
        valid.add(f"{entry.entry_id}_{rk}_status")
        if rt.subentry_type == "yiming":
            for suffix in YIMING_SUFFIXES:
                valid.add(f"{entry.entry_id}_{rk}_{suffix}")
        if rt.subentry_type == "mcdonalds":
            for suffix in MCD_SUFFIXES:
                valid.add(f"{entry.entry_id}_{rk}_{suffix}")
        if rt.subentry_type == "meituan":
            for suffix in MEITUAN_SUFFIXES:
                valid.add(f"{entry.entry_id}_{rk}_{suffix}")
        if rt.subentry_type == "baidu_map":
            for suffix in BAIDU_MAP_SUFFIXES:
                valid.add(f"{entry.entry_id}_{rk}_{suffix}")
        if rt.subentry_type == "didi":
            for suffix in DIDI_SUFFIXES:
                valid.add(f"{entry.entry_id}_{rk}_{suffix}")
    return valid


def _cleanup_stale_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    registry = er.async_get(hass)
    valid = _build_known_sensor_ids(entry)
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        if ent.domain == "sensor" and ent.platform == DOMAIN and ent.unique_id not in valid:
            registry.async_remove(ent.entity_id)


_FIRST_REFRESH_TIMEOUT = 8  # seconds — must be < 10 to avoid HA platform timeout warning


async def _safe_first_refresh(coordinator: DataUpdateCoordinator, name: str) -> None:
    """Run async_refresh with a short timeout, never aborting entity creation."""
    try:
        await asyncio.wait_for(coordinator.async_refresh(), timeout=_FIRST_REFRESH_TIMEOUT)
    except asyncio.TimeoutError:
        _LOGGER.warning("%s first refresh timed out after %ss", name, _FIRST_REFRESH_TIMEOUT)
    except Exception:
        _LOGGER.warning("%s first refresh failed", name, exc_info=True)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    _cleanup_stale_entities(hass, entry)
    runtime: HubRuntime = entry.runtime_data
    _LOGGER.debug("sensor: providers count=%d", len(runtime.providers))

    # Build all provider tasks in parallel so the total time is bounded by the
    # longest single provider, not the sum of all providers.
    async def _setup_one(provider_key: str, provider_rt: ProviderRuntime) -> None:
        coordinator = LifeHubCoordinator(hass, provider_rt)
        await _safe_first_refresh(coordinator, f"health_{provider_key}")
        status_sensor = ProviderStatusSensor(entry, provider_key, provider_rt, coordinator)
        entities: list[SensorEntity] = [status_sensor]
        # Store health coordinator for on-demand refresh from services
        coords = hass.data.setdefault(DOMAIN, {}).setdefault("coordinators", {})
        coords[f"health_{provider_key}"] = coordinator

        if provider_rt.subentry_type == "yiming":
            from .providers.yiming.api import YimingApi
            if isinstance(provider_rt.client, YimingApi):
                from .providers.yiming.sensors import LifeHubDataCoordinator, build_sensors as build_yiming
                yc = LifeHubDataCoordinator(hass, provider_rt)
                await _safe_first_refresh(yc, f"yiming_data_{provider_key}")
                entities.extend(build_yiming(entry, provider_key, provider_rt, yc))
                coords[provider_key] = yc

        if provider_rt.subentry_type == "mcdonalds":
            from .providers.mcdonalds.sensors import McdonaldsDataCoordinator, build_sensors as build_mcd
            mc = McdonaldsDataCoordinator(hass, provider_rt)
            await _safe_first_refresh(mc, f"mcdonalds_data_{provider_key}")
            entities.extend(build_mcd(entry, provider_key, provider_rt, mc))
            coords[provider_key] = mc

        if provider_rt.subentry_type == "meituan":
            from .providers.meituan.sensors import MeituanDataCoordinator, build_sensors as build_mt
            mc = MeituanDataCoordinator(hass, provider_rt)
            await _safe_first_refresh(mc, f"meituan_data_{provider_key}")
            entities.extend(build_mt(entry, provider_key, provider_rt, mc))
            coords[provider_key] = mc

        if provider_rt.subentry_type == "baidu_map":
            from .providers.baidu_map.sensors import BaiduMapWeatherCoordinator, build_sensors as build_bm
            bmc = BaiduMapWeatherCoordinator(hass, provider_rt)
            await _safe_first_refresh(bmc, f"baidu_map_{provider_key}")
            entities.extend(build_bm(entry, provider_key, provider_rt, bmc))
            coords[provider_key] = bmc

        if provider_rt.subentry_type == "didi":
            from .providers.didi.sensors import DidiDataCoordinator, build_sensors as build_didi
            dc = DidiDataCoordinator(hass, provider_rt)
            await _safe_first_refresh(dc, f"didi_data_{provider_key}")
            entities.extend(build_didi(entry, provider_key, provider_rt, dc))
            coords[provider_key] = dc

        async_add_entities(entities, True, config_subentry_id=provider_rt.subentry_id)

    tasks = [_setup_one(pk, prt) for pk, prt in runtime.providers.items()]
    if tasks:
        await asyncio.gather(*tasks)

    if not runtime.providers:
        _LOGGER.warning("No providers loaded, no sensors to add")


class LifeHubCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to poll provider health periodically."""

    def __init__(self, hass: HomeAssistant, provider_rt: ProviderRuntime) -> None:
        interval = max(provider_rt.refresh_interval, 10)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{provider_rt.subentry_type}",
            update_interval=timedelta(minutes=interval),
        )
        self._provider_rt = provider_rt

    async def _async_update_data(self) -> dict[str, Any]:
        if self._provider_rt.status_check is not None:
            try:
                online = await self._provider_rt.status_check()
                return {"status": "connected" if online else "disconnected"}
            except Exception as err:
                _LOGGER.warning("Health check failed for %s: %s", self._provider_rt.key, err)
                return {"status": "error"}
        try:
            return {"status": self._provider_rt.status()}
        except Exception as err:
            raise UpdateFailed(f"Provider poll failed: {err}") from err


class ProviderStatusSensor(CoordinatorEntity[LifeHubCoordinator], SensorEntity):
    """Sensor representing a provider's connection status."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: ConfigEntry,
        provider_key: str,
        provider_rt: ProviderRuntime,
        coordinator: LifeHubCoordinator,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._provider_key = provider_key
        self._provider_rt = provider_rt

        self._subentry_id = provider_rt.subentry_id
        self._attr_config_subentry_id = provider_rt.subentry_id
        self._attr_unique_id = f"{entry.entry_id}_{provider_key}_status"
        self._attr_name = "连接状态"
        self._attr_icon = _PROVIDER_ICONS.get(provider_rt.subentry_type, _DEFAULT_ICON)
        self._attr_translation_key = f"status_{provider_rt.subentry_type}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id, provider_rt.subentry_type, provider_rt.subentry_id)},
            name=provider_rt.title,
            manufacturer=_MANUFACTURER,
            model=_DEVICE_MODEL,
            entry_type="service",
        )

    @property
    def native_value(self) -> str:
        if self.coordinator.data:
            return str(self.coordinator.data.get("status", "unknown"))
        return "unknown"

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        attrs: dict[str, object] = {
            "provider_type": self._provider_rt.subentry_type,
            "refresh_interval": self._provider_rt.refresh_interval,
            "subentry_id": self._provider_rt.subentry_id,
        }
        coord = self.coordinator
        if coord.last_update_success:
            attrs["last_update_success"] = bool(coord.last_update_success)
        if coord.last_exception:
            attrs["last_error"] = str(coord.last_exception)
        return attrs
