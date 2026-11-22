"""Constants for the Homeboard integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "homeboard"
NAME: Final = "Homeboard"

STORAGE_KEY: Final = DOMAIN
STORAGE_VERSION: Final = 1
SAVE_DELAY: Final = 2.0

# Dispatcher signal fired after every mutation and every clock tick.
SIGNAL_UPDATED: Final = f"{DOMAIN}_updated"

# --- enums -----------------------------------------------------------------
ISSUE_TYPES: Final = ("task", "bug", "story", "epic")
PRIORITIES: Final = ("highest", "high", "medium", "low", "lowest")
CATEGORIES: Final = ("todo", "in_progress", "done")
SOURCES: Final = (
    "ui",
    "service",
    "assist",
    "siri",
    "automation",
    "recurring",
    "sensor",
    "todo",
    "health",
)
REPEAT_UNITS: Final = ("day", "week", "month", "year")

DEFAULT_TYPE: Final = "task"
DEFAULT_PRIORITY: Final = "medium"

ORDER_STEP: Final = 1000
ACTIVITY_LIMIT: Final = 100
COMMENT_MAX_LENGTH: Final = 4000
SUMMARY_MAX_LENGTH: Final = 250

# --- options ---------------------------------------------------------------
CONF_STARTER_PROJECT: Final = "starter_project"
CONF_DUE_SOON_HOURS: Final = "due_soon_hours"
CONF_AUTO_ARCHIVE_DAYS: Final = "auto_archive_done_days"
CONF_TRACKED_PEOPLE: Final = "tracked_people"
CONF_NOTIFY_SERVICES: Final = "notify_services"
CONF_NOTIFY_DONE: Final = "notify_done"
CONF_NOTIFY_OVERDUE: Final = "notify_overdue"
CONF_NOTIFY_DUE_SOON: Final = "notify_due_soon"
CONF_NOTIFY_HEALTH: Final = "notify_health"
CONF_PANEL_TITLE: Final = "panel_title"
CONF_PANEL_ICON: Final = "panel_icon"
CONF_PANEL_ADMIN_ONLY: Final = "panel_admin_only"

# --- home health (auto-generated issues) ----------------------------------
CONF_HEALTH_ENABLED: Final = "health_enabled"
CONF_HEALTH_UNAVAILABLE: Final = "health_unavailable"
CONF_HEALTH_BATTERY: Final = "health_battery"
CONF_HEALTH_REPAIRS: Final = "health_repairs"
CONF_HEALTH_INTEGRATIONS: Final = "health_integrations"
CONF_HEALTH_UPDATES: Final = "health_updates"
CONF_HEALTH_UNAVAILABLE_MINUTES: Final = "health_unavailable_minutes"
CONF_HEALTH_BATTERY_THRESHOLD: Final = "health_battery_threshold"
CONF_HEALTH_PROJECT: Final = "health_project"
CONF_HEALTH_ASSIGNEE: Final = "health_assignee"
CONF_HEALTH_SNOOZE_DAYS: Final = "health_snooze_days"
CONF_HEALTH_MAX_OPEN: Final = "health_max_open"
CONF_HEALTH_EXCLUDE_ENTITIES: Final = "health_exclude_entities"
CONF_HEALTH_EXCLUDE_INTEGRATIONS: Final = "health_exclude_integrations"

DEFAULT_HEALTH_UNAVAILABLE_MINUTES: Final = 60
DEFAULT_HEALTH_BATTERY_THRESHOLD: Final = 20
DEFAULT_HEALTH_SNOOZE_DAYS: Final = 7
DEFAULT_HEALTH_MAX_OPEN: Final = 30
HEALTH_PROJECT_KEY: Final = "FIX"
HEALTH_PROJECT_NAME: Final = "Smart home fixes"
HEALTH_STARTUP_GRACE_MINUTES: Final = 10
HEALTH_DEBOUNCE_SCANS: Final = 2
HEALTH_REOPEN_COOLDOWN_MINUTES: Final = 30
HEALTH_IGNORE_LABEL: Final = "ignore"

DEFAULT_DUE_SOON_HOURS: Final = 72
DEFAULT_AUTO_ARCHIVE_DAYS: Final = 30
DEFAULT_PANEL_TITLE: Final = "Board"
DEFAULT_PANEL_ICON: Final = "mdi:view-column"

# --- frontend --------------------------------------------------------------
PANEL_URL_PATH: Final = "homeboard"
STATIC_URL_BASE: Final = "/homeboard_static"
PANEL_JS: Final = "homeboard-panel.js"
CARD_JS: Final = "homeboard-card.js"
PANEL_ELEMENT: Final = "homeboard-panel"
DATA_FRONTEND_READY: Final = f"{DOMAIN}_frontend_ready"

# --- events ----------------------------------------------------------------
EVENT_ISSUE_CREATED: Final = f"{DOMAIN}_issue_created"
EVENT_ISSUE_UPDATED: Final = f"{DOMAIN}_issue_updated"
EVENT_ISSUE_MOVED: Final = f"{DOMAIN}_issue_moved"
EVENT_ISSUE_ASSIGNED: Final = f"{DOMAIN}_issue_assigned"
EVENT_ISSUE_COMMENTED: Final = f"{DOMAIN}_issue_commented"
EVENT_ISSUE_COMPLETED: Final = f"{DOMAIN}_issue_completed"
EVENT_ISSUE_REOPENED: Final = f"{DOMAIN}_issue_reopened"
EVENT_ISSUE_DELETED: Final = f"{DOMAIN}_issue_deleted"
EVENT_ISSUE_OVERDUE: Final = f"{DOMAIN}_issue_overdue"
EVENT_ISSUE_DUE_SOON: Final = f"{DOMAIN}_issue_due_soon"
EVENT_WIP_EXCEEDED: Final = f"{DOMAIN}_wip_exceeded"
EVENT_PROJECT_CHANGED: Final = f"{DOMAIN}_project_changed"

# --- services --------------------------------------------------------------
SERVICE_CREATE_ISSUE: Final = "create_issue"
SERVICE_UPDATE_ISSUE: Final = "update_issue"
SERVICE_MOVE_ISSUE: Final = "move_issue"
SERVICE_ASSIGN_ISSUE: Final = "assign_issue"
SERVICE_ADD_COMMENT: Final = "add_comment"
SERVICE_DELETE_ISSUE: Final = "delete_issue"
SERVICE_QUICK_ADD: Final = "quick_add"
SERVICE_CREATE_PROJECT: Final = "create_project"
SERVICE_UPDATE_PROJECT: Final = "update_project"
SERVICE_ADD_STATUS: Final = "add_status"
SERVICE_UPDATE_STATUS: Final = "update_status"
SERVICE_REMOVE_STATUS: Final = "remove_status"
SERVICE_CREATE_RECURRING: Final = "create_recurring"
SERVICE_UPDATE_RECURRING: Final = "update_recurring"
SERVICE_DELETE_RECURRING: Final = "delete_recurring"
SERVICE_RUN_RECURRING: Final = "run_recurring"
SERVICE_SCAN_HEALTH: Final = "scan_health"
