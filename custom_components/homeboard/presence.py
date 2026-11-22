"""Small helpers about people being home (shared by push and the rhythm learner)."""

from __future__ import annotations

from datetime import time

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.util.location import distance as location_distance


def is_home(hass: HomeAssistant, state: State | None) -> bool | None:
    """Return True / False for a person state, None when unknown.

    A person state is the name of the zone they are in. Overlapping home zones
    (a small ``House`` inside a big ``Home``) make the state differ from
    ``home`` while still being at home, so the coordinates are checked against
    ``zone.home`` as well.
    """
    if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    if state.state == "home":
        return True
    home = hass.states.get("zone.home")
    lat, lon = state.attributes.get("latitude"), state.attributes.get("longitude")
    if home is None or lat is None or lon is None:
        return False
    home_lat, home_lon = home.attributes.get("latitude"), home.attributes.get("longitude")
    if home_lat is None or home_lon is None:
        return False
    radius = float(home.attributes.get("radius") or 100)
    meters = location_distance(home_lat, home_lon, lat, lon)
    return meters is not None and meters <= radius


def parse_hhmm(text: str, default: time) -> time:
    """Parse ``HH:MM`` (or ``HH:MM:SS``), falling back to ``default``."""
    try:
        parts = [int(p) for p in str(text).split(":")[:2]]
        return time(parts[0], parts[1])
    except (ValueError, IndexError):
        return default


def in_quiet_hours(now: time, start: time, end: time) -> bool:
    """Return True if ``now`` falls in the quiet window (which may wrap past midnight)."""
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end
