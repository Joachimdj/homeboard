"""Per-person push notifications and the morning digest.

People are mapped to the notify service of their phone, auto-detected from the
person's ``mobile_app`` device tracker unless overridden in the options. Pushes
for things that are not urgent wait during quiet hours (and, when the rhythm
learner is on, while the person is away) and are delivered together afterwards.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    CONF_DIGEST_ENABLED,
    CONF_DIGEST_TIME,
    CONF_LEARN_RHYTHM,
    CONF_PERSON_NOTIFY,
    CONF_PUSH_ASSIGNED,
    CONF_PUSH_COMMENT,
    CONF_PUSH_OVERDUE,
    CONF_PUSH_REPORTED_DONE,
    CONF_QUIET_END,
    CONF_QUIET_START,
    DEFAULT_DIGEST_TIME,
    DEFAULT_QUIET_END,
    DEFAULT_QUIET_START,
    EVENT_ISSUE_ASSIGNED,
    EVENT_ISSUE_COMMENTED,
    EVENT_ISSUE_COMPLETED,
    EVENT_ISSUE_DUE_SOON,
    EVENT_ISSUE_OVERDUE,
)
from .notify import _async_send
from .presence import in_quiet_hours, is_home, parse_hhmm

if TYPE_CHECKING:
    from .data import HomeboardData

_LOGGER = logging.getLogger(__name__)

TICK = timedelta(minutes=1)
BATCH_AFTER = 3  # more queued pushes than this are merged into one
DIGEST_LIST = 3


@dataclass
class Pending:
    """A push that is waiting for a better moment."""

    person: str
    title: str
    message: str
    url: str
    tag: str


class PushNotifier:
    """Listens to issue events and notifies the people they concern."""

    def __init__(self, hass: HomeAssistant, manager: HomeboardData) -> None:
        """Initialise the notifier (call ``async_start``)."""
        self.hass = hass
        self.manager = manager
        self._unsubs: list[CALLBACK_TYPE] = []
        self._queue: list[Pending] = []
        self._digest_sent: dict[str, date] = {}

    # -- lifecycle

    @callback
    def async_start(self) -> None:
        """Start listening and ticking."""
        bus = self.hass.bus
        options = self.manager.options
        wanted: list[tuple[str, bool, Callable[[Event], None]]] = [
            (EVENT_ISSUE_ASSIGNED, options.get(CONF_PUSH_ASSIGNED, True), self._on_assigned),
            (EVENT_ISSUE_COMMENTED, options.get(CONF_PUSH_COMMENT, True), self._on_commented),
            (EVENT_ISSUE_OVERDUE, options.get(CONF_PUSH_OVERDUE, True), self._on_deadline),
            (EVENT_ISSUE_DUE_SOON, options.get(CONF_PUSH_OVERDUE, True), self._on_deadline),
            (EVENT_ISSUE_COMPLETED, options.get(CONF_PUSH_REPORTED_DONE, True), self._on_completed),
        ]
        for event_type, enabled, handler in wanted:
            if enabled:
                self._unsubs.append(bus.async_listen(event_type, handler))
        self._unsubs.append(async_track_time_interval(self.hass, self._async_tick, TICK))

    @callback
    def async_stop(self) -> None:
        """Stop listening."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    # -- who gets what

    def services_for(self, person: str) -> list[str]:
        """Return the notify service names of a person (override, else auto-detected)."""
        chosen = (self.manager.options.get(CONF_PERSON_NOTIFY) or {}).get(person)
        if chosen:
            names = [chosen] if isinstance(chosen, str) else list(chosen)
            return [n.removeprefix("notify.") for n in names if n]
        return self.detect_services(person)

    def detect_services(self, person: str) -> list[str]:
        """Find ``notify.mobile_app_<device>`` services from the person's device trackers."""
        state = self.hass.states.get(person)
        if state is None:
            return []
        registry = er.async_get(self.hass)
        found: list[str] = []
        for tracker in state.attributes.get("device_trackers") or []:
            entry = registry.async_get(tracker)
            if entry is None or entry.platform != "mobile_app" or not entry.config_entry_id:
                continue
            config_entry = self.hass.config_entries.async_get_entry(entry.config_entry_id)
            device_name = config_entry.data.get("device_name") if config_entry else None
            service = f"mobile_app_{slugify(device_name)}" if device_name else None
            if (
                service
                and self.hass.services.has_service("notify", service)
                and service not in found
            ):
                found.append(service)
        return found

    def _name(self, person: str | None) -> str:
        if person and (state := self.hass.states.get(person)):
            return state.name
        return "Someone"

    # -- event handlers

    @callback
    def _on_assigned(self, event: Event) -> None:
        data = event.data
        target = data.get("to_assignee")
        if target and target != data.get("actor"):
            who = self._name(data.get("actor")) if data.get("actor") else "Homeboard"
            self._notify(
                target, f"Assigned to you: {data['key']}", f"{data['summary']} ({who})", data
            )

    @callback
    def _on_commented(self, event: Event) -> None:
        data = event.data
        if data.get("source") == "health":
            return  # "Problem is back." / "Resolved automatically": the scanner talking to itself
        text = (data.get("comment") or {}).get("text", "")
        for person in {data.get("assignee"), data.get("reporter")} - {None, data.get("actor")}:
            who = self._name(data.get("actor")) if data.get("actor") else "New comment"
            self._notify(
                person,
                f"{who} commented on {data['key']}",
                f"{data['summary']}: {text[:120]}",
                data,
            )

    @callback
    def _on_deadline(self, event: Event) -> None:
        data = event.data
        person = data.get("assignee")
        if not person:
            return
        label = "Overdue" if event.event_type == EVENT_ISSUE_OVERDUE else "Due soon"
        due = f" (due {data['due']})" if data.get("due") else ""
        self._notify(person, f"{label}: {data['key']}", f"{data['summary']}{due}", data)

    @callback
    def _on_completed(self, event: Event) -> None:
        data = event.data
        reporter = data.get("reporter")
        if reporter and reporter != data.get("actor") and data.get("source") != "health":
            who = f" by {self._name(data['actor'])}" if data.get("actor") else ""
            self._notify(reporter, f"Done: {data['key']}", f"{data['summary']}{who}", data)

    # -- delivering

    def _urgent(self, data: dict[str, Any]) -> bool:
        return data.get("priority") == "highest" or "security" in (data.get("labels") or [])

    def _may_disturb(self, person: str) -> bool:
        """Return False during quiet hours or while the person is away (rhythm learner on)."""
        options = self.manager.options
        start = parse_hhmm(options.get(CONF_QUIET_START, DEFAULT_QUIET_START), time(22, 0))
        end = parse_hhmm(options.get(CONF_QUIET_END, DEFAULT_QUIET_END), time(7, 0))
        if in_quiet_hours(dt_util.now().time(), start, end):
            return False
        away = is_home(self.hass, self.hass.states.get(person)) is False
        return not (options.get(CONF_LEARN_RHYTHM, False) and away)

    @callback
    def _notify(self, person: str, title: str, message: str, data: dict[str, Any]) -> None:
        if not self.services_for(person):
            return
        pending = Pending(person, title, message, data["url"], f"homeboard-{data['key']}")
        if self._urgent(data) or self._may_disturb(person):
            self._send(pending)
        else:
            self._queue = [
                q for q in self._queue if not (q.person == person and q.tag == pending.tag)
            ]
            self._queue.append(pending)

    def _send(self, pending: Pending) -> None:
        payload = {
            "title": pending.title,
            "message": pending.message,
            "data": {"url": pending.url, "tag": pending.tag, "group": "homeboard"},
        }
        for service in self.services_for(pending.person):
            self.hass.async_create_task(_async_send(self.hass, service, payload))

    async def _async_tick(self, _now: datetime) -> None:
        self.flush_queue()
        self.send_due_digests()

    @callback
    def flush_queue(self) -> None:
        """Deliver queued pushes to everyone who may be disturbed now."""
        if not self._queue:
            return
        ready: dict[str, list[Pending]] = {}
        waiting: list[Pending] = []
        for item in self._queue:
            (
                ready.setdefault(item.person, []) if self._may_disturb(item.person) else waiting
            ).append(item)
        self._queue = waiting
        for person, items in ready.items():
            if len(items) <= BATCH_AFTER:
                for item in items:
                    self._send(item)
                continue
            lines = "\n".join(f"{i.title}: {i.message}" for i in items[:6])
            self._send(
                Pending(
                    person,
                    f"{len(items)} updates on the board",
                    lines,
                    "/homeboard",
                    "homeboard-batch",
                )
            )

    # -- digest

    def digest_time(self, person: str) -> time:
        """Return the digest time of a person (learned time if accepted, else the option)."""
        learned = (self.manager.learning_data.get("digest_times") or {}).get(person)
        text = learned or self.manager.options.get(CONF_DIGEST_TIME, DEFAULT_DIGEST_TIME)
        return parse_hhmm(text, time(7, 30))

    @callback
    def send_due_digests(self) -> None:
        """Send each person's digest at their time (once a day)."""
        if not self.manager.options.get(CONF_DIGEST_ENABLED, False):
            return
        now = dt_util.now()
        for person in self.manager.tracked_people():
            at = self.digest_time(person)
            if self._digest_sent.get(person) == now.date() or now.time() < at:
                continue
            if now - datetime.combine(now.date(), at, tzinfo=now.tzinfo) > timedelta(minutes=30):
                self._digest_sent[person] = now.date()  # missed the window (restart): skip today
                continue
            self._digest_sent[person] = now.date()
            self.send_digest(person)

    @callback
    def send_digest(self, person: str) -> bool:
        """Push one person's open and overdue issues. Returns True if something was sent."""
        if not self.services_for(person):
            return False
        open_issues = self.manager.top_issues("open", person=person, limit=50)
        if not open_issues:
            return False
        overdue = self.manager.top_issues("overdue", person=person, limit=50)
        due_soon = self.manager.top_issues("due_soon", person=person, limit=50)
        lead = f"{len(open_issues)} open"
        if overdue:
            lead += f", {len(overdue)} overdue"
        if due_soon:
            lead += f", {len(due_soon)} due soon"
        shown = (overdue + due_soon + open_issues)[:DIGEST_LIST]
        seen: list[str] = []
        lines = []
        for item in shown:
            if item["key"] not in seen:
                seen.append(item["key"])
                lines.append(f"{item['key']} {item['summary']}")
        self._send(
            Pending(
                person,
                "Your board today",
                lead + "\n" + "\n".join(lines),
                "/homeboard",
                "homeboard-digest",
            )
        )
        return True

    @callback
    def send_digests_now(self, person: str | None = None) -> list[str]:
        """Send digests right away (service ``send_digest``). Returns the people notified."""
        sent = []
        for who in [person] if person else self.manager.tracked_people():
            if self.send_digest(who):
                sent.append(who)
        return sent
