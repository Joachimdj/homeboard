"""Shared fixtures for the Homeboard tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, mock_component

from custom_components.homeboard.const import CONF_STARTER_PROJECT, DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load custom_components/homeboard."""


@pytest.fixture(autouse=True)
def no_frontend_registration(hass, request) -> Generator[None]:
    """Stub out the frontend for speed; ``@pytest.mark.real_frontend`` keeps the real one.

    The panel / static-path wiring is covered in test_frontend.py (mocked) and in
    test_frontend_real.py (the real http + frontend stack).
    """
    if request.node.get_closest_marker("real_frontend"):
        yield
        return
    mock_component(hass, "frontend")
    mock_component(hass, "panel_custom")
    with (
        patch("custom_components.homeboard.async_register_frontend"),
        patch("custom_components.homeboard.async_unregister_frontend"),
    ):
        yield


@pytest.fixture(autouse=True)
async def local_time_zone(hass) -> None:
    """Run the tests in the owner's time zone (the default is US/Pacific)."""
    await hass.config.async_set_time_zone("Europe/Copenhagen")


@pytest.fixture
def entry() -> MockConfigEntry:
    """A config entry that creates the HOME starter project."""
    return MockConfigEntry(domain=DOMAIN, data={CONF_STARTER_PROJECT: True}, options={})


def add_persons(hass, *names: str) -> None:
    """Create person states (id, name, user id)."""
    for index, name in enumerate(names):
        hass.states.async_set(
            f"person.{name}",
            "home",
            {"friendly_name": name.title(), "user_id": f"user-{index}", "entity_picture": None},
        )


async def setup(hass, entry: MockConfigEntry) -> None:
    """Add the entry, create two people and set Homeboard up."""
    add_persons(hass, "joachim", "padmaja")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
async def manager(hass, entry):
    """A running Homeboard with the HOME project and persons joachim / padmaja.

    The first-scan review of the health scanner is already done here (it is covered in
    test_health.py with ``fresh_manager``), so the scanner tests can create issues directly.
    """
    await setup(hass, entry)
    entry.runtime_data.health_state["reviewed"] = True
    return entry.runtime_data


@pytest.fixture
async def fresh_manager(hass, entry):
    """A running Homeboard whose health scanner has never run."""
    await setup(hass, entry)
    return entry.runtime_data


def status_id(manager, name: str, project: str = "HOME") -> str:
    """Return the id of a status by name."""
    return next(s["id"] for s in manager.resolve_project(project)["statuses"] if s["name"] == name)
