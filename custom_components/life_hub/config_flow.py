"""Config flow for Life Hub."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow as HAConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .const import DOMAIN
from .providers.registry import get_provider_flow_handlers

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(HAConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return self.async_create_entry(title="Life Hub", data={})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowHandler:
        return OptionsFlowHandler(config_entry)

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type]:
        return get_provider_flow_handlers()


class OptionsFlowHandler(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={"address": user_input.get("address", "")},
            )

        current = self._config_entry.options
        data_schema = vol.Schema({
            vol.Optional("address", default=current.get("address", "")): str,
        })
        return self.async_show_form(
            step_id="init",
            data_schema=data_schema,
            description_placeholders={"ha_address": str(self.hass.config.latitude) + ", " + str(self.hass.config.longitude)},
        )