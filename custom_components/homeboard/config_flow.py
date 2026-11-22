"""Config flow and options flow for Homeboard."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    IconSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_AUTO_ARCHIVE_DAYS,
    CONF_DUE_SOON_HOURS,
    CONF_HEALTH_ASSIGNEE,
    CONF_HEALTH_BATTERY,
    CONF_HEALTH_BATTERY_THRESHOLD,
    CONF_HEALTH_ENABLED,
    CONF_HEALTH_EXCLUDE_ENTITIES,
    CONF_HEALTH_EXCLUDE_INTEGRATIONS,
    CONF_HEALTH_INTEGRATIONS,
    CONF_HEALTH_MAX_OPEN,
    CONF_HEALTH_PROJECT,
    CONF_HEALTH_REPAIRS,
    CONF_HEALTH_SNOOZE_DAYS,
    CONF_HEALTH_UNAVAILABLE,
    CONF_HEALTH_UNAVAILABLE_MINUTES,
    CONF_HEALTH_UPDATES,
    CONF_NOTIFY_DONE,
    CONF_NOTIFY_DUE_SOON,
    CONF_NOTIFY_HEALTH,
    CONF_NOTIFY_OVERDUE,
    CONF_NOTIFY_SERVICES,
    CONF_PANEL_ADMIN_ONLY,
    CONF_PANEL_ICON,
    CONF_PANEL_TITLE,
    CONF_STARTER_PROJECT,
    CONF_TRACKED_PEOPLE,
    DEFAULT_AUTO_ARCHIVE_DAYS,
    DEFAULT_DUE_SOON_HOURS,
    DEFAULT_HEALTH_BATTERY_THRESHOLD,
    DEFAULT_HEALTH_MAX_OPEN,
    DEFAULT_HEALTH_SNOOZE_DAYS,
    DEFAULT_HEALTH_UNAVAILABLE_MINUTES,
    DEFAULT_PANEL_ICON,
    DEFAULT_PANEL_TITLE,
    DOMAIN,
    NAME,
)

INT_KEYS = (
    CONF_DUE_SOON_HOURS,
    CONF_AUTO_ARCHIVE_DAYS,
    CONF_HEALTH_UNAVAILABLE_MINUTES,
    CONF_HEALTH_BATTERY_THRESHOLD,
    CONF_HEALTH_SNOOZE_DAYS,
    CONF_HEALTH_MAX_OPEN,
)


def _number(low: int, high: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=low, max=high, step=1, mode=NumberSelectorMode.BOX)
    )


class HomeboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Homeboard (a single instance)."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask whether to create a starter project."""
        if user_input is not None:
            return self.async_create_entry(
                title=NAME, data={CONF_STARTER_PROJECT: user_input[CONF_STARTER_PROJECT]}
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_STARTER_PROJECT, default=True): BooleanSelector()}
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> HomeboardOptionsFlow:
        """Return the options flow."""
        return HomeboardOptionsFlow()


class HomeboardOptionsFlow(OptionsFlowWithReload):
    """Three short pages: general, notifications, home health."""

    def __init__(self) -> None:
        """Initialise the flow."""
        self._options: dict[str, Any] = {}

    def _finish_page(self, user_input: dict[str, Any]) -> None:
        for key in INT_KEYS:
            if key in user_input:
                user_input[key] = int(user_input[key])
        # Empty optional fields mean "not set": drop them instead of storing blanks.
        for key, value in user_input.items():
            if value in (None, "", []):
                self._options.pop(key, None)
            else:
                self._options[key] = value

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """General settings."""
        if user_input is not None:
            self._finish_page(user_input)
            return await self.async_step_notifications()
        self._options = dict(self.config_entry.options)
        schema = vol.Schema(
            {
                vol.Optional(CONF_DUE_SOON_HOURS, default=DEFAULT_DUE_SOON_HOURS): _number(1, 720),
                vol.Optional(CONF_AUTO_ARCHIVE_DAYS, default=DEFAULT_AUTO_ARCHIVE_DAYS): _number(
                    0, 365
                ),
                vol.Optional(CONF_PANEL_TITLE, default=DEFAULT_PANEL_TITLE): TextSelector(),
                vol.Optional(CONF_PANEL_ICON, default=DEFAULT_PANEL_ICON): IconSelector(),
                vol.Optional(CONF_PANEL_ADMIN_ONLY, default=False): BooleanSelector(),
                vol.Optional(CONF_TRACKED_PEOPLE): EntitySelector(
                    EntitySelectorConfig(domain="person", multiple=True)
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, self._options),
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Push notifications."""
        if user_input is not None:
            self._finish_page(user_input)
            return await self.async_step_health()
        services = sorted(self.hass.services.async_services_for_domain("notify"))
        schema = vol.Schema(
            {
                vol.Optional(CONF_NOTIFY_SERVICES): SelectSelector(
                    SelectSelectorConfig(
                        options=services,
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_NOTIFY_DONE, default=False): BooleanSelector(),
                vol.Optional(CONF_NOTIFY_OVERDUE, default=False): BooleanSelector(),
                vol.Optional(CONF_NOTIFY_DUE_SOON, default=False): BooleanSelector(),
                vol.Optional(CONF_NOTIFY_HEALTH, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="notifications",
            data_schema=self.add_suggested_values_to_schema(schema, self._options),
        )

    async def async_step_health(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Home health (auto-generated issues)."""
        if user_input is not None:
            self._finish_page(user_input)
            return self.async_create_entry(data=self._options)
        integrations = sorted({e.domain for e in self.hass.config_entries.async_entries()})
        schema = vol.Schema(
            {
                vol.Optional(CONF_HEALTH_ENABLED, default=True): BooleanSelector(),
                vol.Optional(CONF_HEALTH_UNAVAILABLE, default=True): BooleanSelector(),
                vol.Optional(CONF_HEALTH_BATTERY, default=True): BooleanSelector(),
                vol.Optional(CONF_HEALTH_INTEGRATIONS, default=True): BooleanSelector(),
                vol.Optional(CONF_HEALTH_REPAIRS, default=True): BooleanSelector(),
                vol.Optional(CONF_HEALTH_UPDATES, default=False): BooleanSelector(),
                vol.Optional(
                    CONF_HEALTH_UNAVAILABLE_MINUTES, default=DEFAULT_HEALTH_UNAVAILABLE_MINUTES
                ): _number(5, 1440),
                vol.Optional(
                    CONF_HEALTH_BATTERY_THRESHOLD, default=DEFAULT_HEALTH_BATTERY_THRESHOLD
                ): _number(1, 60),
                vol.Optional(CONF_HEALTH_PROJECT): TextSelector(),
                vol.Optional(CONF_HEALTH_ASSIGNEE): EntitySelector(
                    EntitySelectorConfig(domain="person")
                ),
                vol.Optional(CONF_HEALTH_SNOOZE_DAYS, default=DEFAULT_HEALTH_SNOOZE_DAYS): _number(
                    0, 90
                ),
                vol.Optional(CONF_HEALTH_MAX_OPEN, default=DEFAULT_HEALTH_MAX_OPEN): _number(
                    1, 200
                ),
                vol.Optional(CONF_HEALTH_EXCLUDE_ENTITIES): EntitySelector(
                    EntitySelectorConfig(multiple=True)
                ),
                vol.Optional(CONF_HEALTH_EXCLUDE_INTEGRATIONS): SelectSelector(
                    SelectSelectorConfig(
                        options=integrations,
                        multiple=True,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="health",
            data_schema=self.add_suggested_values_to_schema(schema, self._options),
        )
