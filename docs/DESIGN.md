# Homeboard — design (v1, approved by the owner 2026-11-22)

> Name **Homeboard**, domain `homeboard` (owner's choice). Scope approved as designed **plus
> recurring chores in v1** (see `docs/PROTOCOL.md` section 2). Frontend decision: **zero
> third-party runtime code** (hand-rolled keyed renderer instead of the vendored Preact mentioned
> in section 7). The data contract is in `docs/PROTOCOL.md`.

A Jira-inspired kanban / issue tracker that lives natively inside Home Assistant: projects with
issue keys (`HOME-12`), a configurable workflow, a drag-and-drop board, a status overview, quick
add (text, Assist, Siri/Shortcuts) and automation hooks. Everything runs inside HA: no server, no
cloud, no extra add-on. Distributed through the Marketplace (HACS) as a custom repository first.

Not affiliated with Atlassian; "Jira" appears only as "inspired by" in the README. The name, icons
and code are our own. Reference repos (aktive/hakboard, neilellis/hakanban) were studied for
*ideas only*; nothing is copied.

## 1. What we take from the references (and what we do differently)

| Reference | Good idea we keep | What we do differently |
|-----------|-------------------|------------------------|
| **hakboard** (pulls Kanboard into sensors) | Status / users / projects overview: counts per column, overdue, last activity, tasks per person. Sensors so dashboards and automations can use the numbers. | No external server. Our data *is* the source, so we can also write (create / move issues), not only read. Per-status and per-person sensors are built in, no YAML cards that need other HACS add-ons. |
| **hakanban** (native kanban) | Native HA primitives (device, `todo`, `calendar`), single JSON store, websocket push, bundled card + panel, no build step, auto-registered frontend. | Jira data model (project key, issue types, priority, workflow with status categories, reporter/assignee, activity log) instead of Trello cards. One `todo` per *project* (not per column) so the entity count stays low. Touch-first custom drag and drop. Service responses, dedupe keys and quick-add parser for automations / voice. |
| **Jira** | Issue key, types, priority, status categories (To do / In progress / Done), backlog + board, quick filters, swimlanes by assignee, comments + activity history. | Household scale: one workflow shape per project, any-to-any transitions, people = HA `person` entities. No sprints, no custom fields. |
| **owner's blueriot-hass** | Layout (`custom_components/<domain>/`, `hacs.json`, MIT, `@joachimdj` codeowner, config flow, README with Marketplace + manual install). | Frontend is registered with the modern API (`add_extra_js_url` + `panel_custom`) with a version in the static path for cache busting, instead of copying files into `/config/www`. |

## 2. Data model

One store: `homeassistant.helpers.storage.Store(hass, version=1, key="homeboard")` →
`/config/.storage/homeboard`, debounced save (`async_delay_save`), migration hook ready. HA
backups already include `.storage`. Plain dicts; one class `HomeboardData` is the **single mutation
point** (every change = validate → apply → activity entry → bus event → dispatcher signal →
delayed save). Entities, services and the websocket API are thin views over it.

```jsonc
{
  "projects": { "<project_id>": {
    "id": "...", "key": "HOME",               // 2-6 chars A-Z0-9, unique, immutable
    "name": "Home", "description": "", "color": "#2f80ed", "icon": "mdi:home",
    "lead": "person.joachim",                   // optional
    "default_assignee": null,
    "statuses": [                               // = board columns, ordered (Jira "workflow")
      { "id": "...", "name": "Backlog",     "category": "todo",        "backlog": true,  "wip": null },
      { "id": "...", "name": "To do",       "category": "todo",        "backlog": false, "wip": null },
      { "id": "...", "name": "In progress", "category": "in_progress", "backlog": false, "wip": 3 },
      { "id": "...", "name": "Done",        "category": "done",        "backlog": false, "wip": null }
    ],
    "labels": ["garden", "car"],                // free-form, colour derived from the text
    "issue_seq": 12,                            // monotonic, numbers are never reused
    "archived": false, "created": "<iso>"
  }},
  "issues": { "<issue_id>": {
    "id": "...", "project_id": "...", "number": 12, "key": "HOME-12",
    "type": "task",                              // task | bug | story | epic
    "summary": "Fix the gate latch", "description": "",
    "status": "<status_id>",                     // category decides open vs done
    "priority": "medium",                        // highest | high | medium | low | lowest
    "assignee": "person.joachim", "reporter": "person.padmaja",   // person entity ids or null
    "labels": ["garden"], "parent": null,        // epic link (one level)
    "due": "2026-11-30",                         // date or tz-aware datetime, or null
    "rank": 3000,                                // sparse int order inside the status, gap 1000, rebalanced when gap < 2
    "dedupe_key": null,                          // for sensor-created issues, see §5
    "source": "ui",                              // ui | service | assist | siri | automation
    "created": "<iso>", "updated": "<iso>", "resolved": null,
    "overdue_notified": false, "due_soon_notified": false,
    "comments": [ { "id": "...", "author": "person.joachim", "ts": "<iso>", "text": "..." } ],
    "activity": [ { "ts": "<iso>", "actor": "person.joachim", "kind": "moved",
                    "field": "status", "from": "To do", "to": "In progress" } ]   // capped at 100
  }}
}
```

Decisions worth knowing:
- **Project = one board** (Jira "project + board" collapsed). Backlog is a status flagged
  `backlog: true`: it is listed in the Backlog view and hidden from the Board unless toggled on.
- **Status category** (`todo | in_progress | done`) is what the counts, overdue logic, events
  (`completed` / `reopened`) and the `todo` entity mapping use, so users can rename or add columns
  freely. Any-to-any transitions (no workflow rules).
- **People** are HA `person` entities. The acting user of a websocket call or service call is mapped
  to a person through `person.attributes.user_id` (so reporter / activity actor are filled in
  automatically). Unknown actor → `null`, `source` still says where it came from.
- **Deleting a status that still has issues** requires `move_to`; deleting a project asks for an
  explicit confirm flag (service) / dialog (UI).

## 3. Entities (native HA, so Assist, dashboards and automations work)

Device per project (`identifiers={("homeboard", project_id)}`) + one service device "Homeboard".

| Platform | Entity | Notes |
|----------|--------|-------|
| `todo` | one per **project** (name = project name) | Assist "add milk to the Home list" creates an issue (default status = first non-backlog "todo"-category status, type task, `source: assist`). Open issues listed; completing moves to the first `done` status, un-completing to the first `todo` status. Supports create / update (summary, description, due) / delete / move-item. |
| `calendar` | one per project | Issues with `due` become events (all-day for a date, 1 h block for a datetime), summary `HOME-12 Fix the gate`. Read-only. |
| `sensor` | per project: `open_issues`, `overdue`, `due_soon`, `unassigned`, `last_activity` (timestamp), and one **count per status** | Attributes on `open_issues`: counts per status / priority / type. `overdue` / `due_soon` carry the top 10 issues (key, summary, due, assignee) for cards and notification templates. |
| `sensor` | global: `total_open`, `total_overdue`, `total_due_soon`, `last_activity`; **per person**: `<person>_assigned` | Per-person state = open issues assigned; attributes `overdue`, `in_progress`, `done_7d`, top issues. Created for every `person` entity (options can restrict). |
| `binary_sensor` | `has_overdue` per project (device class `problem`) | Handy trigger/condition. |

Sensors update from the dispatcher signal (instant) plus a 5-minute tick, because "overdue" changes
with the clock, not only with edits. Removing a status or project cleans up its entities from the
registry.

## 4. Events (HA bus) — triggers for automations

`homeboard_issue_created`, `_updated` (with `changes`), `_moved` (`from_status`, `to_status`,
categories), `_assigned`, `_commented`, `_completed`, `_reopened`, `_deleted`, `_overdue` (fires
once when the due date passes), `_due_soon` (once when entering the window), `homeboard_wip_exceeded`,
`homeboard_project_changed`.
Common payload: `project`, `key`, `issue_id`, `summary`, `type`, `priority`, `status`,
`assignee`, `reporter`, `labels`, `actor`, `source`, `url` (deep link to the panel).

## 5. Services (`homeboard.*`, with `services.yaml`, `strings.json`, entity/target selectors)

| Service | Purpose |
|---------|---------|
| `create_issue` | `project`, `summary`, optional type/priority/assignee/labels/due/description/status/`dedupe_key`/`on_duplicate` (`skip` \| `comment` \| `reopen`). **Returns** `{key, id, created: bool}` (service response). The sensor → issue path: trigger "battery low", `dedupe_key: battery_<entity>` so it never makes duplicates. |
| `update_issue`, `move_issue`, `assign_issue`, `add_comment`, `delete_issue` | Address the issue by `issue` (`HOME-12` or id) **or** by `project` + `dedupe_key` (so an automation can close what it opened: "sensor OK again → move to Done"). `move_issue` takes a status name or id plus optional position. |
| `quick_add` | One free-text line (`text`), optional `project`, `source`. For the text box, Assist and Siri/Shortcuts. Parser (pure Python, deterministic, no LLM): `@joachim` assignee, `!high` / `!1..5` priority, `#label`, `due tomorrow` / `due fri` / `due 2026-12-01`, leading `bug:` / `story:` type, leading `HOME:` project. Danish words (`i morgen`, `fredag`, `vigtig`) are a stretch goal, the parser is built with per-language word lists. Returns the created key and what it parsed. |
| `create_project`, `update_project`, `add_status`, `update_status`, `remove_status` | Setup from scripts; the panel has full UI for this. |

Permissions: issue operations are open to every signed-in user (kids, wall tablet user); project and
status management is admin only. Services run with the caller's context.

## 6. Websocket API (`homeboard/*`)

Same proven pattern as hakanban, own contract: `homeboard/subscribe` streams a full payload
(projects with statuses, non-archived issues with comment/activity *counts*, people with picture,
stats) immediately and after every change; `homeboard/get` once. Mutations
(`homeboard/issue/create|update|move|delete|comment`, `homeboard/project/*`, `homeboard/status/*`,
`homeboard/quick_add`) return the object, and state propagates through the subscription, so the
client does an optimistic update and reconciles on the next push. `homeboard/issue/get` returns one
issue with full comments and activity. Voluptuous-validated, admin checks where §5 says so. Contract
documented in `docs/PROTOCOL.md` (written alongside the code).

## 7. Frontend (plain ES modules, no npm/build, shadow DOM, HA theme variables)

Served from `/homeboard_static/<version>/…` (version in the *path*, so every release busts the
cache even for relative `import`s, with no build step). Registered automatically:
`panel_custom` sidebar panel **Board** (all users, title/icon configurable) and
`frontend.add_extra_js_url` for the cards, so there is **no manual Lovelace resource**.

No third-party code at runtime: a small hand-rolled keyed renderer (`dom.js`) so live pushes never
destroy a drag in progress.

**Panel** `homeboard-panel` (phone, desktop, wall tablet):
- Tabs: **Summary** (the hakboard-style status overview), **Board**, **Backlog**, **List**.
- Project switcher, quick-add bar (parsed chips preview, mic button where the browser supports
  speech recognition), quick filters (My issues, Unassigned, Overdue, Due soon, label, type,
  free-text search), swimlanes: none / by assignee / by priority, WIP badges per column.
- **Drag and drop** with Pointer Events (not HTML5 DnD, which does not work on touch): immediate on
  mouse, 300 ms long-press on touch so scrolling still works, auto-scroll at edges, drop marker,
  "Undo" toast that moves the card back, plus a *Move to…* menu in every card for accessibility.
- Issue dialog: summary, description, type, priority, assignee, labels, due, status, epic link,
  comments, activity log. Project settings dialog: statuses (add / rename / reorder / category / WIP),
  labels, lead, default assignee.
- Wall-tablet mode (`?kiosk`): large touch targets, no chrome, auto-reconnect.

**Lovelace cards** (all with visual editors, listed in the card picker):
`homeboard-board-card` (compact board, `project`, `show_backlog`, `swimlanes`, `filter`),
`homeboard-status-card` (counts per status as a stacked bar, overdue, due soon, last activity,
issues per person; entity-based so it also updates from sensors), `homeboard-quick-add-card`
(text box + mic + a "send to" project picker).

English UI; the string table is built for translation, Danish is a stretch goal.

## 8. Config flow and options

UI config flow, **single entry** (`single_config_entry: true`), one confirm step with a checkbox
"Create a starter project HOME". Options: due-soon window (default 72 h), tracked people, panel
title / icon / admin-only, notifications: one or more `notify.*` services plus toggles for
*done*, *overdue*, *due soon* (the notification logic only listens to our own events, so anything
more custom is done with a normal automation).

## 9. Repo layout (`~/ha-kanban/`, repo-ready, MIT)

```
custom_components/homeboard/
  __init__.py const.py manifest.json config_flow.py strings.json services.yaml icons.json
  translations/ (en.json, da.json)       # generated by scripts/gen_strings.py
  model.py        # pure Python: ids, templates, validation, ranks, due-date maths
  recurrence.py   # pure Python: recurring schedule maths
  quickadd.py     # pure Python quick-add parser (EN + DA words)
  stats.py        # pure Python statistics for the payload and the sensors
  data.py store.py                       # HomeboardData = the single mutation point, Store wrapper
  health.py                              # detectors + reconciler for auto-generated issues
  services.py websocket_api.py frontend.py notify.py entity.py
  todo.py calendar.py sensor.py binary_sensor.py
  brand/ (icon, logo, dark variants)     # HA reads these locally (scripts/make_brand.py)
  static/ (homeboard-panel.js, homeboard-card.js, modules)   # no build step, no third-party code
tests/ (pytest backend, js/ node --test, browser/ mock-HA harness)
scripts/ (check_hacs.py, check_hassfest.sh, gen_strings.py, make_brand.py)
.github/workflows/validate.yml   # hassfest + HACS action + pytest + ruff + node tests
hacs.json  README.md  CHANGELOG.md  LICENSE  docs/ (DESIGN, PROTOCOL)  .gitignore
```

`manifest.json`: `integration_type: hub`, `iot_class: local_push`, `config_flow: true`,
`single_config_entry: true`, dependencies `http, websocket_api, frontend, panel_custom, todo,
calendar, person`, codeowner `@joachimdj`, version in the owner's style (`0.1.0`, patch bumps).

## 10. Test plan

1. **Pure logic** (pytest, no HA): rank insert/rebalance, key allocation, category transitions,
   overdue / due-soon maths across timezones, quick-add parser (EN + DA word lists), dedupe rules.
2. **Integration tests** with `pytest-homeassistant-custom-component` in a project-local venv:
   config flow + options, setup / unload / reload (no leaked panel, services or listeners), every
   service incl. responses and errors, events fired with the right data, entity states after each
   mutation, `todo` / `calendar` behaviour, per-person sensors, persistence and migration through
   the store, websocket commands incl. admin vs non-admin, notification fan-out with a mocked
   `notify`. Target ≥ 90 % coverage of the backend.
3. **Static checks, locally**: `ruff` (HA ruleset), JSON validity of manifest / strings /
   translations, **hassfest** by running the Home Assistant core `script.hassfest` against the
   integration (shallow checkout, or the official Docker action image, Docker is installed here),
   and a script mirroring the HACS validation rules (hacs.json keys, manifest keys, brand files,
   README, release tags). The GitHub workflow runs the real `hacs/action` and hassfest on push.
4. **Frontend**: `node --test` for the pure JS (rank maths, filters, quick-add preview) and the
   `tests/browser/` mock-hass page with a fake websocket, driven in a browser with synthetic
   pointer events to verify drag and drop, filters, swimlanes and dialogs, at phone and tablet
   widths, light and dark.
5. **Real HA (after the owner deploys and approves a restart)**: read-only smoke test through the
   owner's signed-in Chrome: panel loads, card appears in the picker, create a test project, drag
   cards, see the entities and events in Developer Tools, then clean up the test data. **No sirens,
   lights or spoken announcements; no notification tests without asking; no restart without the
   owner's OK and the alarm disarmed** (cameras are offline ~4 min).

## 11. v1 scope

**In:** projects with keys, 4 issue types, priorities, configurable statuses with categories + WIP
(soft), board + backlog + list + summary, drag and drop (touch + mouse), quick filters, swimlanes by
assignee / priority, comments + activity log, `todo` + `calendar` + sensors, events, services with
responses and dedupe, quick-add parser + text / mic / Assist (native todo) / Siri docs, overdue / due
soon / done notifications, sidebar panel + 3 Lovelace cards auto-registered, English UI, tests, CI,
README with Marketplace custom-repository and manual install, MIT.

**Also in v1 (owner's pick):** recurring issues / chores (every N days / weeks / months / years,
weekday rules, "create N days before", skip while the previous one is open).

**Out (deliberately later):** sprints, velocity / burndown, subtasks and checklists, epic progress
roll-up, attachments, custom fields, rules per transition and per-project permissions, time
tracking, import from Jira / Kanboard / hakanban / CSV and export,
device triggers in the automation UI, Assist custom sentences installed automatically (v1 documents
an automation with sentence triggers; the native todo route "add X to the Home list" works out of
the box), per-person push targets, Danish UI (stretch), Marketplace *default store* listing (needs a
public repo, a release and a PR to `hacs/default`; the README documents the path).

## 11b. Home health: the board fills itself (owner's request, in v1)

The integration also **generates issues for things in the smart home that need fixing**: offline
devices, low batteries, Home Assistant repairs, failing / re-authentication-needing integrations and
(opt-in) pending updates. It closes them again when the fault is gone, snoozes what a human closed,
and has flood protection (grace period, two-scan debounce, cap, grouping per integration). Details,
dedupe keys and rules: `docs/PROTOCOL.md` section 3b. Implemented in `health.py` (pure detectors over
HA state / registries + a reconciler that only talks to `HomeboardData`), with a `scan_health` service
(incl. `dry_run`), a global `sensor.homeboard_auto_issues`, optional push notification when a high
priority auto issue appears, and an "Auto" badge + quick filter + "Home health" tile in the UI.
Safety on the owner's live HA: switched on only after a `dry_run` review (many cameras and the water
meter are offline today, so a first real scan would create issues at once).

## 12. Milestones

M1 core (`model`, `data`, store, quick-add, tests) → M2 HA wiring (entities, services, events, WS,
options, notifications, tests) → M3 panel (board, DnD, dialogs) → M4 cards + summary → M5 packaging
(brand, README, CI, hassfest/HACS checks) → M6 deploy to the owner's HA and verify by eye.
