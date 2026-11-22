# Homeboard protocol and data contract

The shared interface between the Python integration, the websocket API and the frontend (panel +
Lovelace cards). Source of truth: when code and this file disagree, fix one of them in the same
change. Working name and domain: **Homeboard / `homeboard`**.

Conventions

- Ids (`project_id`, `status_id`, `issue_id`, `comment_id`, `recurring_id`) are opaque strings.
- Time: ISO-8601 strings with offset (`2026-11-22T20:15:00+01:00`). `due` is either a date
  (`2026-11-30`, all-day, overdue once the local date is after it) or a tz-aware datetime
  (overdue once `now` is after it).
- Enums: issue `type` = `task | bug | story | epic`; `priority` = `highest | high | medium | low |
  lowest`; status `category` = `todo | in_progress | done`; `source` = `ui | service | assist |
  siri | automation | recurring | sensor | todo | health` (`health` = created by the home-health
  scanner, section 3b).
- People are HA `person` entity ids (`person.joachim`) or `null`.
- "Open" issue = its status category is not `done`.

## 1. Store (`/config/.storage/homeboard`, `version: 1`)

```jsonc
{
  "projects": { "<project_id>": {
    "id": "", "key": "HOME", "name": "Home", "description": "", "color": "#2f80ed", "icon": "mdi:home",
    "lead": null, "default_assignee": null, "archived": false, "created": "<iso>",
    "statuses": [ { "id": "", "name": "To do", "category": "todo", "backlog": false, "wip": null } ],
    "labels": ["garden"],                       // free-form label vocabulary (also grows from issues)
    "issue_seq": 12                             // monotonic, numbers are never reused
  } },
  "issues": { "<issue_id>": {
    "id": "", "project_id": "", "number": 12, "key": "HOME-12",
    "type": "task", "summary": "", "description": "",
    "status": "<status_id>", "priority": "medium",
    "assignee": null, "reporter": null, "labels": [], "parent": null,     // parent = epic issue id
    "due": null, "rank": 3000,                  // sparse int order inside a status, gap 1000
    "dedupe_key": null, "recurring_id": null, "source": "ui",
    "created": "", "updated": "", "resolved": null, "archived": false,
    "overdue_notified": false, "due_soon_notified": false,
    "auto_resolved": false,                     // true when the health scanner closed it itself
    "comments": [ { "id": "", "author": null, "ts": "", "text": "" } ],
    "activity": [ { "ts": "", "actor": null, "kind": "created|moved|updated|assigned|commented|completed|reopened|archived",
                    "field": null, "from": null, "to": null } ]               // capped at 100, oldest dropped
  } },
  "recurring": { "<recurring_id>": {
    "id": "", "project_id": "", "enabled": true,
    "summary": "Put out the bins", "description": "", "type": "task", "priority": "medium",
    "assignee": null, "labels": [], "status": null,                      // null = first non-backlog todo status
    "repeat": { "every": 1, "unit": "week", "weekdays": [2], "day_of_month": null },   // weekdays Mon=0..Sun=6
    "next_due": "2026-11-25",                   // due date of the NEXT issue to create
    "create_days_before": 0, "skip_if_open": true,
    "last_issue_id": null, "last_created": null
  } }
}
```

## 2. Recurring issues (chores)

`repeat.unit` is `day | week | month | year`, `every` >= 1. `week` may carry `weekdays` (default:
the weekday of `next_due`); `month` uses `day_of_month` (1-31 clamped to the month length, or `-1` =
last day; default: day of `next_due`); `year` repeats month/day (29 Feb falls back to 28 Feb).

Engine (runs at startup, hourly, and after every recurring change), `today` = local HA date:
while `next_due - create_days_before <= today`: remember `next_due` as candidate and advance
`next_due` to the next occurrence. After the loop, create **one** issue for the last candidate
(so downtime never floods the board), unless `skip_if_open` is true and `last_issue_id` is still
open. The new issue: template fields, `due = candidate`, `source = "recurring"`, `recurring_id` set,
event `homeboard_issue_created`.

## 3. Quick-add grammar (`homeboard.quick_add`, WS `homeboard/quick_add*`)

Tokens may sit anywhere, the rest is the summary (whitespace collapsed; empty summary = error).

| Token | Meaning |
|-------|---------|
| `@joachim`, `@me` | assignee: case-insensitive match on person object id or friendly name, unique prefix allowed; `@me` = the acting person |
| `!highest` `!high` `!medium` `!low` `!lowest`, `!1`..`!5` | priority (`!1` = highest) |
| `#garden` | label (lower-cased) |
| `due <when>` | `today`, `tomorrow`, `mon`..`sun` / full weekday names (next occurrence, never today), `next week`, `in 3 days`, `2026-12-01`, `1/12`, `1.12`; optional time `18:00` (then due is a datetime) |
| leading `bug:` `story:` `task:` `epic:` | issue type |
| leading `HOME:` | project key (otherwise the `project` argument, otherwise the first non-archived project) |

Danish words (stretch): `i dag`, `i morgen`, `mandag`..`soendag`, `om 3 dage`, `vigtig`/`haster` = high.
The parser lives in `quickadd.py` and returns `{project, summary, type, priority, assignee, labels, due, unresolved}`
(`project` is the project *key*; `unresolved` lists `@x` / `!x` tokens that matched nothing and were left in the summary).

## 3b. Home health: issues Homeboard creates by itself

Homeboard scans the smart home every 5 minutes and creates, updates and closes issues for faults
(`source = "health"`, label `auto`, type `bug` for broken things and `task` for chores such as
batteries). Detectors (each switchable in the options): **offline devices** (all primary entities
of a device `unavailable` for longer than N minutes, grouped per device, or one issue per
integration when 3 or more of its devices are offline), **low batteries** (< threshold, grouped
per device), **repairs** (open Home Assistant repair issues), **integration problems** (config
entry in setup error / retry / migration error, or waiting for re-authentication), **updates
available** (one grouped issue, off by default).

Rules that keep it from flooding the board: ignores disabled / hidden / diagnostic-only entities
and registry ghosts (`restored`); 10 minute grace after Home Assistant starts; a problem must be
seen in two consecutive scans before an issue is created and absent for two scans before it is
closed ("Resolved automatically" comment, `auto_resolved = true`); at most `health_max_open` (30)
open auto issues, highest priority first; device findings are replaced by the integration finding
when the whole integration is down. Security devices (doors, windows, motion, smoke, gas, water,
tamper, locks, cameras, alarm panels) get priority `high` and label `security`.

`dedupe_key` is `health:<detector>:<id>` (`health:offline:<device_id>`, `health:battery:<device_id>`,
`health:repair:<domain>:<issue_id>`, `health:entry:<entry_id>`, `health:reauth:<entry_id>`,
`health:updates`). Closing an auto issue by hand while the fault persists **snoozes** it for
`health_snooze_days` (7); after that it is reopened with a "Problem is back" comment. The label
`ignore` on an auto issue suppresses that fault for good. Auto issues go to the project chosen in the
options (default: key `FIX`, "Smart home fixes", created on demand) and to the optional default
assignee. The scan can be run by hand with the `scan_health` service / `homeboard/health/scan`
(`dry_run` lists what it would do without writing anything).

## 4. Frontend payload (WS push / `homeboard/get`)

The frontend never sees the raw store. `comments` and `activity` are left out of the list payload
(fetch with `homeboard/issue/get`). Archived issues are left out.

```jsonc
{
  "version": "0.1.0",
  "settings": { "due_soon_hours": 72, "panel_title": "Board", "auto_archive_done_days": 30,
                "health_enabled": true },
  "me": "person.joachim",              // person of the signed-in user, or null
  "is_admin": true,
  "people": [ { "entity_id": "person.joachim", "name": "Joachim", "picture": "/api/image/..." | null, "user_id": "..." | null } ],
  "projects": [ { "id","key","name","description","color","icon","lead","default_assignee","archived",
                  "statuses":[{ "id","name","category","backlog","wip" }], "labels":[] } ],
  "issues": [ { "id","project_id","key","number","type","summary","description","status","priority",
                "assignee","reporter","labels","parent","due","rank","source","created","updated",
                "resolved","dedupe_key","recurring_id",
                "overdue": false, "due_soon": false, "comment_count": 0 } ],
  "recurring": [ { /* as in the store */ } ],
  "stats": {
    "total":    { "open","overdue","due_soon","unassigned","done_7d","last_activity","health_open" },
    "projects": { "<project_id>": { "open","overdue","due_soon","unassigned","done_7d","last_activity","health_open",
                                    "by_status":{"<status_id>":n}, "by_priority":{"high":n}, "by_type":{"bug":n} } },
    "people":   { "<person entity_id>": { "open","overdue","in_progress","done_7d" } }   // key "unassigned" for none
  }
}
```

Issues are not nested; the client groups them by `project_id` and `status` and sorts by `rank`
(ascending, ties by `number`). `last_activity` = ISO time or `null`. `due_soon` = open and due within
`settings.due_soon_hours` (and not overdue).

## 5. WebSocket API

Semantics worth knowing: `status/update` with `wip: null` clears the limit; `project/update` with `labels`
replaces the whole vocabulary; `issue/update` with `archived: true` drops the issue from the next push;
activity entries of kind `moved` carry status *names* in `from` / `to`, `assigned` entries carry person
ids; `issue/move` with a `before` that is not in the target status is rejected with `not_found`.

Commands are `{ "id": n, "type": "homeboard/<cmd>", ... }`. Because `type` is the command name,
the *issue type* travels as **`issue_type`** in every command (`issue/create`, `issue/update`,
`recurring/create`, `recurring/update`); payload objects and bus events still call it `type`. `homeboard/subscribe` sends the result
first, then one **event whose body is the full payload** immediately and after every change (also
after clock-driven overdue changes). Mutations return the affected object, and the new state arrives
through the subscription (optimistic update, reconcile on next push). Errors:
`not_found`, `invalid_format`, `unauthorized` (admin only), `conflict` (duplicate key etc.).

| type | params | result |
|------|--------|--------|
| `homeboard/get` | - | payload |
| `homeboard/subscribe` | - | stream of payloads |
| `homeboard/project/create` (admin) | `key`, `name`, `description?`, `color?`, `icon?`, `lead?`, `template?` = `household` (default: Backlog, To do, In progress, Done) \| `software` (Backlog, To do, In progress, Review, Done) \| `blank` | project |
| `homeboard/project/update` (admin) | `project_id`, `name?`, `description?`, `color?`, `icon?`, `lead?`, `default_assignee?`, `archived?`, `labels?` | project |
| `homeboard/project/delete` (admin) | `project_id`, `confirm: true` | `{deleted}` |
| `homeboard/status/create` (admin) | `project_id`, `name`, `category`, `backlog?`, `wip?`, `position?` | status |
| `homeboard/status/update` (admin) | `project_id`, `status_id`, `name?`, `category?`, `backlog?`, `wip?` | status |
| `homeboard/status/reorder` (admin) | `project_id`, `status_ids` (complete list in new order) | `{ok}` |
| `homeboard/status/delete` (admin) | `project_id`, `status_id`, `move_to?` (required if issues exist) | `{deleted}` |
| `homeboard/issue/create` | `project_id`, `summary`, `issue_type?`, `priority?`, `assignee?`, `labels?`, `due?`, `description?`, `status?`, `parent?` | issue |
| `homeboard/issue/get` | `issue_id` | issue **with** `comments` and `activity` |
| `homeboard/issue/update` | `issue_id`, any of `summary, description, issue_type, priority, assignee, labels, due, parent, archived` (`null` clears assignee/due/parent) | issue |
| `homeboard/issue/move` | `issue_id`, `status`, `before?` (issue id to be placed in front of; `null`/absent = end of the status) | issue |
| `homeboard/issue/delete` | `issue_id` | `{deleted}` |
| `homeboard/issue/comment` | `issue_id`, `text` | comment |
| `homeboard/issue/list` | `project_id?`, `archived?`, `query?`, `limit?` (default 100), `offset?` | `{issues, total}` (archived and search) |
| `homeboard/quick_add` | `text`, `project?` (id or key) | `{issue, parsed}` |
| `homeboard/quick_add/preview` | `text`, `project?` | `parsed` (nothing written; for chips under the text box) |
| `homeboard/recurring/create` | `project_id` + recurring fields (`summary, description, issue_type, priority, assignee, labels, status, repeat, next_due, create_days_before, skip_if_open, enabled`) | recurring |
| `homeboard/recurring/update` | `recurring_id`, fields | recurring |
| `homeboard/recurring/delete` | `recurring_id` | `{deleted}` |
| `homeboard/recurring/run_now` | `recurring_id` | `{issue}` or `{issue: null}` when skipped |
| `homeboard/health/scan` (admin) | `dry_run?` | `{created, reopened, closed, suppressed, findings:[{key, summary, priority, detector}]}` |

Permissions: issue, comment, quick-add and recurring operations are open to every signed-in user;
`project/*` and `status/*` need an admin.

## 6. Bus events

Common data on every issue event: `project` (key), `project_id`, `key`, `issue_id`, `summary`,
`type`, `priority`, `status` (name), `category`, `assignee`, `reporter`, `labels`, `due`, `actor`
(person or null), `source`, `url` (`/homeboard?issue=HOME-12`).

| event | extra data |
|-------|-----------|
| `homeboard_issue_created` | - |
| `homeboard_issue_updated` | `changes` = `{field: {"from":, "to":}}` |
| `homeboard_issue_moved` | `from_status`, `to_status`, `from_category`, `to_category` |
| `homeboard_issue_assigned` | `from_assignee`, `to_assignee` |
| `homeboard_issue_commented` | `comment` |
| `homeboard_issue_completed` | moved into a `done` category |
| `homeboard_issue_reopened` | moved out of `done` |
| `homeboard_issue_deleted` | - |
| `homeboard_issue_overdue` | fires once when the due time passes (open issues) |
| `homeboard_issue_due_soon` | fires once when an open issue enters the due-soon window |
| `homeboard_wip_exceeded` | `project`, `status`, `wip`, `count` |
| `homeboard_project_changed` | `project`, `project_id`, `action` (`created\|updated\|deleted`) |

## 7. Services (`homeboard.*`)

All issue services address the issue by `issue` (key `HOME-12` or id) **or** by `project` + `dedupe_key`.

| Service | Fields | Response |
|---------|--------|----------|
| `create_issue` | `project`, `summary`, `type?`, `priority?`, `assignee?`, `labels?`, `due?`, `description?`, `status?`, `parent?`, `dedupe_key?`, `on_duplicate?` = `skip` (default) \| `comment` \| `reopen` | `{key, id, created}` |
| `update_issue` | `issue` or `project`+`dedupe_key`, any editable field | `{key, id}` |
| `move_issue` | `issue`/dedupe, `status` (name or id), `position?` = `top` \| `bottom` | `{key, id}` |
| `assign_issue` | `issue`/dedupe, `assignee` (empty = unassign) | `{key, id}` |
| `add_comment` | `issue`/dedupe, `text` | `{key, id}` |
| `delete_issue` | `issue`/dedupe | - |
| `quick_add` | `text`, `project?`, `source?` (default `service`) | `{key, id, parsed}` |
| `create_project`, `update_project`, `add_status`, `update_status`, `remove_status` | as the WS equivalents | the object |
| `create_recurring`, `update_recurring`, `delete_recurring`, `run_recurring` | as the WS equivalents | the object |
| `scan_health` | `dry_run?` | `{created, reopened, closed, suppressed, findings}` |

## 8. Entities (summary; details in DESIGN.md section 3)

Device per project; `todo` + `calendar` + `binary_sensor.has_overdue` + sensors per project; global
sensors; one `<person>_assigned` sensor per person. Unique ids are `<project_id>_<suffix>`, so
renaming a project or status never changes an entity id.

## 9. Frontend delivery

Static files live in `custom_components/homeboard/static/` and are served at
`/homeboard_static/<manifest version>/`. All imports inside `static/` are **relative**, and nothing
loads from the network. Entry modules: `homeboard-panel.js` (defines custom element
`homeboard-panel`, registered by `panel_custom` at url path `homeboard`, receives `hass`, `narrow`,
`route`, `panel` as properties) and `homeboard-card.js` (defines `homeboard-board-card`,
`homeboard-status-card`, `homeboard-quick-add-card`, each pushed to `window.customCards`, each with
`getConfigElement` / `getStubConfig`). Deep links: `/homeboard?issue=HOME-12` opens the issue dialog,
`/homeboard?kiosk` hides the chrome for wall tablets, `?project=HOME` selects a project.
