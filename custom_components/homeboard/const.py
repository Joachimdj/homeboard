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

# --- 0.2: push, files, checklists, assist, learning ----------------------
CONF_PERSON_NOTIFY: Final = "person_notify"
CONF_PUSH_ASSIGNED: Final = "push_assigned"
CONF_PUSH_COMMENT: Final = "push_comment"
CONF_PUSH_OVERDUE: Final = "push_overdue"
CONF_PUSH_REPORTED_DONE: Final = "push_reported_done"
CONF_DIGEST_ENABLED: Final = "digest_enabled"
CONF_DIGEST_TIME: Final = "digest_time"
CONF_QUIET_START: Final = "quiet_start"
CONF_QUIET_END: Final = "quiet_end"
CONF_ASSIST_SENTENCES: Final = "assist_sentences"
CONF_ATTACHMENTS_ENABLED: Final = "attachments_enabled"
CONF_MAX_UPLOAD_MB: Final = "max_upload_mb"
CONF_CHECKLIST_AUTODONE: Final = "checklist_autodone"
CONF_LEARN_DEFAULTS: Final = "learn_defaults"
CONF_LEARN_PATTERNS: Final = "learn_patterns"
CONF_LEARN_WORKLOAD: Final = "learn_workload"
CONF_LEARN_HEALTH: Final = "learn_health"
CONF_LEARN_RHYTHM: Final = "learn_rhythm"
CONF_LEARN_HABITS: Final = "learn_habits"

DEFAULT_DIGEST_TIME: Final = "07:30"
DEFAULT_QUIET_START: Final = "22:00"
DEFAULT_QUIET_END: Final = "07:00"
DEFAULT_MAX_UPLOAD_MB: Final = 10
CHECKLIST_MAX_ITEMS: Final = 100
CHECKLIST_TEXT_MAX: Final = 200
FILES_DIR: Final = "homeboard_files"
FILES_URL_BASE: Final = "/api/homeboard"
SIGNED_URL_SECONDS: Final = 3600
ALLOWED_MIME: Final = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "application/pdf": ".pdf",
}
THUMB_SIZE: Final = 320

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
CONF_HEALTH_NOISY_DEVICES: Final = "health_noisy_devices"
CONF_HEALTH_AUTOMATIONS: Final = "health_automations"

DEFAULT_HEALTH_UNAVAILABLE_MINUTES: Final = 60
DEFAULT_HEALTH_BATTERY_THRESHOLD: Final = 20
DEFAULT_HEALTH_SNOOZE_DAYS: Final = 7
DEFAULT_HEALTH_MAX_OPEN: Final = 15
HEALTH_PROJECT_KEY: Final = "FIX"
HEALTH_PROJECT_NAME: Final = "Smart home fixes"
HEALTH_STARTUP_GRACE_MINUTES: Final = 10
HEALTH_DEBOUNCE_SCANS: Final = 2
HEALTH_REOPEN_COOLDOWN_MINUTES: Final = 30
HEALTH_PATIENCE_FACTOR: Final = 1.5
"""A fault that went away by itself is reported only after 1.5 x its longest such episode."""
HEALTH_PATIENCE_LEARN_MAX_MINUTES: Final = 2 * 24 * 60
"""Longer outages are real faults that somebody fixed, not a device that is slow to answer."""
HEALTH_PATIENCE_MAX_MINUTES: Final = 3 * 24 * 60
"""However patient Homeboard has become, a device silent for 3 days is always reported."""
HEALTH_PATIENCE_KEEP_DAYS: Final = 90
HEALTH_IGNORE_LABEL: Final = "ignore"
# Browsers and phones come and go and charge themselves: not faults, unless the owner asks for them.
HEALTH_EPHEMERAL_PLATFORMS: Final = frozenset({"browser_mod", "mobile_app", "ios"})
# Dedupe key of the one issue that holds back the very first scan until a person has looked at it.
HEALTH_REVIEW_KEY: Final = "review:health"
# Helper-like platforms: an unavailable one is not a device that needs fixing.
HEALTH_IGNORED_PLATFORMS: Final = frozenset(
    {
        "template",
        "group",
        "derivative",
        "integration",
        "utility_meter",
        "min_max",
        "threshold",
        "statistics",
        "history_stats",
        "trend",
        "filter",
        "generic_thermostat",
        "generic_hygrostat",
        "switch_as_x",
        "random",
        "scene",
        "automation",
        "script",
        "schedule",
        "input_boolean",
        "input_number",
        "input_select",
        "input_text",
        "input_datetime",
        "input_button",
        "counter",
        "timer",
        "person",
        "zone",
        "sun",
        DOMAIN,
    }
)

DEFAULT_DUE_SOON_HOURS: Final = 72
DEFAULT_AUTO_ARCHIVE_DAYS: Final = 30
DEFAULT_PANEL_TITLE: Final = "Board"
DEFAULT_PANEL_ICON: Final = "mdi:view-column"

# --- AI Fix (docs/DESIGN-0.3.md) ---------------------------------------------
CONF_AI_FIX_ENABLED: Final = "ai_fix_enabled"
CONF_AI_FIX_ENTITY: Final = "ai_fix_entity"
CONF_AI_FIX_ALLOW_PROTECTED: Final = "ai_fix_allow_protected"
CONF_AI_FIX_DAILY_LIMIT: Final = "ai_fix_daily_limit"
DEFAULT_AI_FIX_DAILY_LIMIT: Final = 20
BACKUP_DIR: Final = "homeboard_backups"
# Domains whose automations the AI may explain but Homeboard never rewrites (unless the owner allows it).
PROTECTED_DOMAINS: Final = frozenset({"alarm_control_panel", "siren", "lock", "valve", "alarmo"})
AI_FIX_KINDS: Final = (
    "automation_edit",
    "automation_disable",
    "reload_integration",
    "manual_steps",
)
AI_MAX_PROPOSALS: Final = 3
AI_MAX_RECORDS: Final = 50
AI_NOTE_MAX: Final = 500
AI_CONTEXT_CHARS: Final = 24_000
AI_TIMEOUT_SECONDS: Final = 240

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
EVENT_ATTACHMENT_ADDED: Final = f"{DOMAIN}_attachment_added"
EVENT_ATTACHMENT_REMOVED: Final = f"{DOMAIN}_attachment_removed"
EVENT_AI_PROPOSAL_READY: Final = f"{DOMAIN}_ai_proposal_ready"
EVENT_AI_FIX_APPLIED: Final = f"{DOMAIN}_ai_fix_applied"
EVENT_AI_FIX_UNDONE: Final = f"{DOMAIN}_ai_fix_undone"
EVENT_HABIT_AUTOMATION_CREATED: Final = f"{DOMAIN}_habit_automation_created"

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
SERVICE_ADD_CHECKLIST_ITEM: Final = "add_checklist_item"
SERVICE_CHECK_ITEM: Final = "check_item"
SERVICE_REMOVE_CHECKLIST_ITEM: Final = "remove_checklist_item"
SERVICE_ATTACH_CAMERA_SNAPSHOT: Final = "attach_camera_snapshot"
SERVICE_SUGGEST: Final = "suggest"
SERVICE_SEND_DIGEST: Final = "send_digest"
SERVICE_FORGET_LEARNING: Final = "forget_learning"
SERVICE_AI_ANALYZE: Final = "ai_analyze"
SERVICE_SCAN_HABITS: Final = "scan_habits"
