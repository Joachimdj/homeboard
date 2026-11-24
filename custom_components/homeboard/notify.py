"""Optional push notifications for done / overdue / due-soon / new auto issues.

This only listens to Homeboard's own bus events; anything more custom is a
normal automation on the same events.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later

from .const import (
    CONF_NOTIFY_DONE,
    CONF_NOTIFY_DUE_SOON,
    CONF_NOTIFY_HEALTH,
    CONF_NOTIFY_OVERDUE,
    CONF_NOTIFY_SERVICES,
    EVENT_ISSUE_COMPLETED,
    EVENT_ISSUE_CREATED,
    EVENT_ISSUE_DUE_SOON,
    EVENT_ISSUE_OVERDUE,
    HEALTH_PUSH_SETTLE_MINUTES,
)

_LOGGER = logging.getLogger(__name__)


def _message(event_type: str, data: dict[str, Any]) -> tuple[str, str]:
    key, summary = data["key"], data["summary"]
    if event_type == EVENT_ISSUE_COMPLETED:
        return f"Done: {key}", summary
    if event_type == EVENT_ISSUE_OVERDUE:
        due = f" (due {data['due']})" if data.get("due") else ""
        return f"Overdue: {key}", f"{summary}{due}"
    if event_type == EVENT_ISSUE_DUE_SOON:
        due = f" (due {data['due']})" if data.get("due") else ""
        return f"Due soon: {key}", f"{summary}{due}"
    return f"Needs attention: {key}", summary


@callback
def async_setup_notifications(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Listen for events and push them to the chosen notify services."""
    options = entry.options
    services = [
        name.removeprefix("notify.") for name in options.get(CONF_NOTIFY_SERVICES, []) if name
    ]
    if not services:
        return

    waiting: set[CALLBACK_TYPE] = set()
    """Timers of new fault pushes that are still settling."""

    @callback
    def send(event_type: str, data: dict[str, Any]) -> None:
        title, message = _message(event_type, data)
        payload = {
            "title": title,
            "message": message,
            "data": {"url": data["url"], "tag": f"homeboard-{data['key']}"},
        }
        for service in services:
            hass.async_create_task(_async_send(hass, service, payload))

    @callback
    def still_open(issue_id: str) -> bool:
        manager = entry.runtime_data
        issue = manager.issues.get(issue_id)
        return issue is not None and not issue["archived"] and manager.category(issue) != "done"

    @callback
    def send_when_settled(data: dict[str, Any]) -> None:
        """Push a new fault only if it is still there after a while.

        Devices that blink off and on create a card and close it again minutes later; the
        person should not be woken for that.
        """
        cancel: Callable[[], None]

        @callback
        def later(_now: Any) -> None:
            waiting.discard(cancel)
            if still_open(data["issue_id"]):
                send(EVENT_ISSUE_CREATED, data)

        cancel = async_call_later(hass, timedelta(minutes=HEALTH_PUSH_SETTLE_MINUTES), later)
        waiting.add(cancel)

    @callback
    def on_event(event: Event) -> None:
        data = event.data
        if data.get("source") == "health" and event.event_type == EVENT_ISSUE_COMPLETED:
            return  # the scanner closed it because the fault went away: not worth a "Done"
        if event.event_type == EVENT_ISSUE_CREATED:
            if data.get("source") != "health" or data.get("priority") not in ("highest", "high"):
                return
            send_when_settled(data)
            return
        send(event.event_type, data)

    @callback
    def cancel_waiting() -> None:
        for cancel in list(waiting):
            cancel()
        waiting.clear()

    entry.async_on_unload(cancel_waiting)

    wanted = (
        (CONF_NOTIFY_DONE, EVENT_ISSUE_COMPLETED),
        (CONF_NOTIFY_OVERDUE, EVENT_ISSUE_OVERDUE),
        (CONF_NOTIFY_DUE_SOON, EVENT_ISSUE_DUE_SOON),
        (CONF_NOTIFY_HEALTH, EVENT_ISSUE_CREATED),
    )
    for option, event_type in wanted:
        if options.get(option):
            entry.async_on_unload(hass.bus.async_listen(event_type, on_event))


async def _async_send(hass: HomeAssistant, service: str, payload: dict[str, Any]) -> None:
    try:
        await hass.services.async_call("notify", service, payload, blocking=True)
    except HomeAssistantError as err:
        _LOGGER.warning("Could not send notification through notify.%s: %s", service, err)
