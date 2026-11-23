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
    CONF_ASSIST_SENTENCES,
    CONF_ATTACHMENTS_ENABLED,
    CONF_AUTO_ARCHIVE_DAYS,
    CONF_CHECKLIST_AUTODONE,
    CONF_DIGEST_ENABLED,
    CONF_DIGEST_TIME,
    CONF_DUE_SOON_HOURS,
    CONF_HEALTH_ASSIGNEE,
    CONF_HEALTH_BATTERY,
    CONF_HEALTH_BATTERY_THRESHOLD,
    CONF_HEALTH_ENABLED,
    CONF_HEALTH_EXCLUDE_ENTITIES,
    CONF_HEALTH_EXCLUDE_INTEGRATIONS,
    CONF_HEALTH_INTEGRATIONS,
    CONF_HEALTH_MAX_OPEN,
    CONF_HEALTH_NOISY_DEVICES,
    CONF_HEALTH_PROJECT,
    CONF_HEALTH_REPAIRS,
    CONF_HEALTH_SNOOZE_DAYS,
    CONF_HEALTH_UNAVAILABLE,
    CONF_HEALTH_UNAVAILABLE_MINUTES,
    CONF_HEALTH_UPDATES,
    CONF_LEARN_DEFAULTS,
    CONF_LEARN_HEALTH,
    CONF_LEARN_PATTERNS,
    CONF_LEARN_RHYTHM,
    CONF_LEARN_WORKLOAD,
    CONF_MAX_UPLOAD_MB,
    CONF_NOTIFY_DONE,
    CONF_NOTIFY_DUE_SOON,
    CONF_NOTIFY_HEALTH,
    CONF_NOTIFY_OVERDUE,
    CONF_NOTIFY_SERVICES,
    CONF_PANEL_ADMIN_ONLY,
    CONF_PANEL_ICON,
    CONF_PANEL_TITLE,
    CONF_PERSON_NOTIFY,
    CONF_PUSH_ASSIGNED,
    CONF_PUSH_COMMENT,
    CONF_PUSH_OVERDUE,
    CONF_PUSH_REPORTED_DONE,
    CONF_QUIET_END,
    CONF_QUIET_START,
    CONF_STARTER_PROJECT,
    CONF_TRACKED_PEOPLE,
    DEFAULT_AUTO_ARCHIVE_DAYS,
    DEFAULT_DIGEST_TIME,
    DEFAULT_DUE_SOON_HOURS,
    DEFAULT_HEALTH_BATTERY_THRESHOLD,
    DEFAULT_HEALTH_MAX_OPEN,
    DEFAULT_HEALTH_SNOOZE_DAYS,
    DEFAULT_HEALTH_UNAVAILABLE_MINUTES,
    DEFAULT_MAX_UPLOAD_MB,
    DEFAULT_PANEL_ICON,
    DEFAULT_PANEL_TITLE,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    DOMAIN,
    NAME,
)

CONF_NOTIFY_SERVICE = "notify_service"
INT_KEYS = (
    CONF_DUE_SOON_HOURS,
    CONF_AUTO_ARCHIVE_DAYS,
    CONF_HEALTH_UNAVAILABLE_MINUTES,
    CONF_HEALTH_BATTERY_THRESHOLD,
    CONF_HEALTH_SNOOZE_DAYS,
    CONF_HEALTH_MAX_OPEN,
    CONF_MAX_UPLOAD_MB,
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
    """A menu of short sections; every section saves and closes."""

    def __init__(self) -> None:
        """Initialise the flow."""
        self._options: dict[str, Any] = {}
        self._people: list[str] = []
        self._notify_map: dict[str, list[str]] = {}

    def _merge(self, user_input: dict[str, Any]) -> None:
        for key in INT_KEYS:
            if key in user_input:
                user_input[key] = int(user_input[key])
        # Empty optional fields mean "not set": drop them instead of storing blanks.
        for key, value in user_input.items():
            if value in (None, "", []):
                self._options.pop(key, None)
            else:
                self._options[key] = value

    def _save(self) -> ConfigFlowResult:
        return self.async_create_entry(data=self._options)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose what to configure."""
        self._options = dict(self.config_entry.options)
        return self.async_show_menu(
            step_id="init",
            menu_options=["general", "alerts", "people", "files", "health", "learning"],
        )

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """General settings."""
        if user_input is not None:
            self._merge(user_input)
            return self._save()
        schema = vol.Schema(
            {
                vol.Optional(CONF_DUE_SOON_HOURS, default=DEFAULT_DUE_SOON_HOURS): _number(1, 720),
                vol.Optional(CONF_AUTO_ARCHIVE_DAYS, default=DEFAULT_AUTO_ARCHIVE_DAYS): _number(
                    0, 365
                ),
                vol.Optional(CONF_CHECKLIST_AUTODONE, default=False): BooleanSelector(),
                vol.Optional(CONF_PANEL_TITLE, default=DEFAULT_PANEL_TITLE): TextSelector(),
                vol.Optional(CONF_PANEL_ICON, default=DEFAULT_PANEL_ICON): IconSelector(),
                vol.Optional(CONF_PANEL_ADMIN_ONLY, default=False): BooleanSelector(),
                vol.Optional(CONF_TRACKED_PEOPLE): EntitySelector(
                    EntitySelectorConfig(domain="person", multiple=True)
                ),
            }
        )
        return self.async_show_form(
            step_id="general",
            data_schema=self.add_suggested_values_to_schema(schema, self._options),
        )

    async def async_step_alerts(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Household-wide push notifications."""
        if user_input is not None:
            self._merge(user_input)
            return self._save()
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
            step_id="alerts",
            data_schema=self.add_suggested_values_to_schema(schema, self._options),
        )

    async def async_step_people(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Per-person push: what to send and when, then which phone each person has."""
        if user_input is not None:
            self._merge(user_input)
            self._people = sorted(s.entity_id for s in self.hass.states.async_all("person"))
            self._notify_map = {
                person: list(services) if not isinstance(services, str) else [services]
                for person, services in (self._options.get(CONF_PERSON_NOTIFY) or {}).items()
            }
            return await self.async_step_person()
        schema = vol.Schema(
            {
                vol.Optional(CONF_PUSH_ASSIGNED, default=True): BooleanSelector(),
                vol.Optional(CONF_PUSH_COMMENT, default=True): BooleanSelector(),
                vol.Optional(CONF_PUSH_OVERDUE, default=True): BooleanSelector(),
                vol.Optional(CONF_PUSH_REPORTED_DONE, default=True): BooleanSelector(),
                vol.Optional(CONF_DIGEST_ENABLED, default=False): BooleanSelector(),
                vol.Optional(CONF_DIGEST_TIME, default=DEFAULT_DIGEST_TIME): TextSelector(),
                vol.Optional(CONF_QUIET_START, default=DEFAULT_QUIET_START): TextSelector(),
                vol.Optional(CONF_QUIET_END, default=DEFAULT_QUIET_END): TextSelector(),
            }
        )
        return self.async_show_form(
            step_id="people",
            data_schema=self.add_suggested_values_to_schema(schema, self._options),
        )

    async def async_step_person(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """One person's phone (empty = detect it from their device tracker)."""
        if user_input is not None and self._people:
            person = self._people.pop(0)
            chosen = user_input.get(CONF_NOTIFY_SERVICE)
            if chosen:
                self._notify_map[person] = [chosen.removeprefix("notify.")]
            else:
                self._notify_map.pop(person, None)
        if not self._people:
            if self._notify_map:
                self._options[CONF_PERSON_NOTIFY] = self._notify_map
            else:
                self._options.pop(CONF_PERSON_NOTIFY, None)
            return self._save()
        person = self._people[0]
        state = self.hass.states.get(person)
        services = sorted(self.hass.services.async_services_for_domain("notify"))
        schema = vol.Schema(
            {
                vol.Optional(CONF_NOTIFY_SERVICE): SelectSelector(
                    SelectSelectorConfig(
                        options=services, custom_value=True, mode=SelectSelectorMode.DROPDOWN
                    )
                )
            }
        )
        current = (self._notify_map.get(person) or [None])[0]
        return self.async_show_form(
            step_id="person",
            data_schema=self.add_suggested_values_to_schema(schema, {CONF_NOTIFY_SERVICE: current}),
            description_placeholders={"person": state.name if state else person},
        )

    async def async_step_files(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Photos and files, and Assist sentences."""
        if user_input is not None:
            self._merge(user_input)
            return self._save()
        schema = vol.Schema(
            {
                vol.Optional(CONF_ATTACHMENTS_ENABLED, default=True): BooleanSelector(),
                vol.Optional(CONF_MAX_UPLOAD_MB, default=DEFAULT_MAX_UPLOAD_MB): _number(1, 50),
                vol.Optional(CONF_ASSIST_SENTENCES, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="files",
            data_schema=self.add_suggested_values_to_schema(schema, self._options),
        )

    async def async_step_learning(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """What Homeboard may learn from."""
        if user_input is not None:
            self._merge(user_input)
            return self._save()
        schema = vol.Schema(
            {
                vol.Optional(CONF_LEARN_DEFAULTS, default=True): BooleanSelector(),
                vol.Optional(CONF_LEARN_PATTERNS, default=True): BooleanSelector(),
                vol.Optional(CONF_LEARN_WORKLOAD, default=True): BooleanSelector(),
                vol.Optional(CONF_LEARN_HEALTH, default=True): BooleanSelector(),
                vol.Optional(CONF_LEARN_RHYTHM, default=False): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="learning",
            data_schema=self.add_suggested_values_to_schema(schema, self._options),
        )

    async def async_step_health(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Home health (auto-generated issues)."""
        if user_input is not None:
            self._merge(user_input)
            return self._save()
        integrations = sorted({e.domain for e in self.hass.config_entries.async_entries()})
        schema = vol.Schema(
            {
                vol.Optional(CONF_HEALTH_ENABLED, default=True): BooleanSelector(),
                vol.Optional(CONF_HEALTH_UNAVAILABLE, default=True): BooleanSelector(),
                vol.Optional(CONF_HEALTH_BATTERY, default=True): BooleanSelector(),
                vol.Optional(CONF_HEALTH_INTEGRATIONS, default=True): BooleanSelector(),
                vol.Optional(CONF_HEALTH_REPAIRS, default=True): BooleanSelector(),
                vol.Optional(CONF_HEALTH_UPDATES, default=False): BooleanSelector(),
                vol.Optional(CONF_HEALTH_NOISY_DEVICES, default=False): BooleanSelector(),
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
