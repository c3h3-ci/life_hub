"""百度地图天气传感器。

定时查询天气数据，暴露温度、天气状况、湿度、风力等传感器。
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from ...models import ProviderRuntime

_LOGGER = logging.getLogger(__name__)

DOMAIN = "life_hub"

SENSOR_SUFFIXES = [
    "temperature",
    "condition",
    "humidity",
    "wind_power",
    "wind_direction",
]


class BaiduMapWeatherCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator to fetch weather data from Baidu Map."""

    def __init__(self, hass: HomeAssistant, provider_rt: ProviderRuntime) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_baidu_map_weather",
            update_interval=timedelta(minutes=30),
        )
        self._provider_rt = provider_rt

    async def _async_update_data(self) -> dict[str, Any]:
        client = getattr(self._provider_rt, "client", None)
        if client is None or not hasattr(client, "weather"):
            raise UpdateFailed("Baidu Map client not available")

        try:
            # Check life_hub options first (city name or lat,lng), fallback to HA coords
            location = ""
            entries = self.hass.config_entries.async_entries(DOMAIN)
            if entries:
                addr = entries[0].options.get("address", "") or ""
                if addr:
                    location = addr
            if not location:
                lat = self.hass.config.latitude
                lng = self.hass.config.longitude
                location = f"{lat},{lng}" if lat and lng else ""
            data = await client.weather(region=location)
            # Parse Agent Plan weather response
            return _parse_weather(data)
        except Exception as err:
            raise UpdateFailed(f"Weather fetch failed: {err}") from err


def _parse_weather(data: dict) -> dict[str, Any]:
    """Parse Agent Plan weather response into flat dict."""
    result: dict[str, Any] = {}

    # Try different response formats
    if "result" in data:
        info = data["result"]
    elif "data" in data:
        info = data["data"]
    else:
        info = data

    if isinstance(info, dict):
        # The actual weather data is nested inside "now" key
        if "now" in info:
            now = info["now"]
            result["temperature"] = now.get("temp")
            result["condition"] = now.get("text")
            result["humidity"] = now.get("rh")
            result["wind_power"] = now.get("wind_class")
            result["wind_direction"] = now.get("wind_dir")
        else:
            result["temperature"] = info.get("temperature") or info.get("temp")
            result["condition"] = info.get("condition") or info.get("weather") or info.get("text")
            result["humidity"] = info.get("humidity") or info.get("rh")
            result["wind_power"] = info.get("wind_power") or info.get("windSpeed") or info.get("wind")
            result["wind_direction"] = info.get("wind_direction") or info.get("windDir")

    # Remove None values
    return {k: v for k, v in result.items() if v is not None}


def build_sensors(
    entry: ConfigEntry,
    provider_key: str,
    provider_rt: ProviderRuntime,
    coordinator: BaiduMapWeatherCoordinator,
) -> list[SensorEntity]:
    """Build weather sensors."""
    return [
        TemperatureSensor(entry, provider_key, provider_rt, coordinator),
        WeatherConditionSensor(entry, provider_key, provider_rt, coordinator),
        HumiditySensor(entry, provider_key, provider_rt, coordinator),
        WindPowerSensor(entry, provider_key, provider_rt, coordinator),
        WindDirectionSensor(entry, provider_key, provider_rt, coordinator),
    ]


class BaseWeatherSensor(CoordinatorEntity[BaiduMapWeatherCoordinator], SensorEntity):
    """Base class for weather sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        entry: ConfigEntry,
        provider_key: str,
        provider_rt: ProviderRuntime,
        coordinator: BaiduMapWeatherCoordinator,
        suffix: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{provider_key}_{suffix}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id, provider_rt.subentry_type, provider_rt.subentry_id)},
        }
        self._suffix = suffix

    @property
    def native_value(self) -> Any:
        if self.coordinator.data:
            return self.coordinator.data.get(self._suffix)
        return None


class TemperatureSensor(BaseWeatherSensor):
    """Current temperature."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(
        self,
        entry: ConfigEntry,
        provider_key: str,
        provider_rt: ProviderRuntime,
        coordinator: BaiduMapWeatherCoordinator,
    ) -> None:
        super().__init__(entry, provider_key, provider_rt, coordinator,
                         "temperature", "温度", "mdi:thermometer")


class WeatherConditionSensor(BaseWeatherSensor):
    """Weather condition description."""

    def __init__(
        self,
        entry: ConfigEntry,
        provider_key: str,
        provider_rt: ProviderRuntime,
        coordinator: BaiduMapWeatherCoordinator,
    ) -> None:
        super().__init__(entry, provider_key, provider_rt, coordinator,
                         "condition", "天气状况", "mdi:weather-cloudy")


class HumiditySensor(BaseWeatherSensor):
    """Humidity percentage."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"

    def __init__(
        self,
        entry: ConfigEntry,
        provider_key: str,
        provider_rt: ProviderRuntime,
        coordinator: BaiduMapWeatherCoordinator,
    ) -> None:
        super().__init__(entry, provider_key, provider_rt, coordinator,
                         "humidity", "湿度", "mdi:water-percent")


class WindPowerSensor(BaseWeatherSensor):
    """Wind power/speed."""

    def __init__(
        self,
        entry: ConfigEntry,
        provider_key: str,
        provider_rt: ProviderRuntime,
        coordinator: BaiduMapWeatherCoordinator,
    ) -> None:
        super().__init__(entry, provider_key, provider_rt, coordinator,
                         "wind_power", "风力", "mdi:weather-windy")


class WindDirectionSensor(BaseWeatherSensor):
    """Wind direction."""

    def __init__(
        self,
        entry: ConfigEntry,
        provider_key: str,
        provider_rt: ProviderRuntime,
        coordinator: BaiduMapWeatherCoordinator,
    ) -> None:
        super().__init__(entry, provider_key, provider_rt, coordinator,
                         "wind_direction", "风向", "mdi:weather-windy-variant")
