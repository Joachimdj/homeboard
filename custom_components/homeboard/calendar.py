"""Calendar entity: open issues with a due date, one calendar per project."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HomeboardConfigEntry
from .data import HomeboardData
from .entity import HomeboardEntity, async_setup_synced_entities

PARALLEL_UPDATES = 0

TIMED_EVENT_LENGTH = timedelta(hours=1)


class HomeboardCalendar(HomeboardEntity, CalendarEntity):
    """Due dates of open issues as calendar events."""

    _attr_translation_key = "due_dates"

    def __init__(self, manager: HomeboardData, project_id: str) -> None:
        """Initialise the calendar."""
        super().__init__(manager, project_id)
        self._attr_unique_id = f"{project_id}_calendar"

    def _events(self) -> list[CalendarEvent]:
        project = self.project
        if project is None:
            return []
        events = []
        for issue in self.manager.project_issues(project["id"]):
            due = issue["due"]
            if not due or self.manager.category(issue) == "done":
                continue
            if len(due) == 10:
                start: date | datetime = date.fromisoformat(due)
                end: date | datetime = start + timedelta(days=1)
            else:
                start = dt_util.as_local(datetime.fromisoformat(due))
                end = start + TIMED_EVENT_LENGTH
            events.append(
                CalendarEvent(
                    start=start,
                    end=end,
                    summary=f"{issue['key']} {issue['summary']}",
                    description=issue["description"] or None,
                    uid=issue["id"],
                )
            )
        return sorted(events, key=lambda e: e.start_datetime_local)

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current or next upcoming event."""
        now = dt_util.now()
        for event in self._events():
            if event.end_datetime_local > now:
                return event
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return events overlapping the requested range."""
        return [
            event
            for event in self._events()
            if event.start_datetime_local < end_date and event.end_datetime_local > start_date
        ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeboardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one calendar per project."""
    manager = entry.runtime_data

    def desired() -> dict[str, Callable[[], Entity]]:
        return {
            f"{pid}_calendar": lambda p=pid: HomeboardCalendar(manager, p)
            for pid in manager.projects
        }

    async_setup_synced_entities(
        hass, manager, "calendar", async_add_entities, desired, entry.async_on_unload
    )
