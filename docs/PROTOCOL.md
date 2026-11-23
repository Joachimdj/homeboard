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
integration when 3 or more of its devices are offline; media players, remotes, light-only devices and
browser / phone integrations are skipped unless `health_noisy_devices` is on), **low batteries** (< threshold;
security devices get one issue each with key `health:battery:<device_id>`, every other device goes into ONE
grouped issue `health:battery_group` whose title follows the count; devices with a lawn mower / vacuum entity,
a `battery_charging` sensor or a phone / browser platform are skipped unless `health_noisy_devices` is on), **repairs** (open Home Assistant repair issues), **integration problems** (config
entry in setup error / retry / migration error, or waiting for re-authentication), **updates
available** (one grouped issue, off by default).

Rules that keep it from flooding the board: ignores disabled / hidden / diagnostic-only entities
and registry ghosts (`restored`); 10 minute grace after Home Assistant starts; a problem must be
seen in two consecutive scans before an issue is created and absent for two scans before it is
closed ("Resolved automatically" comment, `auto_resolved = true`); at most `health_max_open` (15)
open auto issues, highest priority first; device findings are replaced by the integration finding
when the whole integration is down. Security devices (doors, windows, motion, smoke, gas, water,
tamper, locks, cameras, alarm panels) get priority `high` and label `security`.

**Patience.** Devices that answer once a day, or go offline for hours and come back, would open and close
a card again and again. When an `offline` or `silent` card closes by itself, Homeboard remembers how long the fault lasted
(`learning.health.patience[<dedupe_key>] = {minutes, n, last}`, kept 90 days, only outages up to 2 days count). The same
fault is reported again only after 1.5 x the longest such time (at most 3 days). Faults held back are listed in the scan
result under `waiting`. On the first scan after the update the cards that already closed by themselves are used
(`health.patience_seeded`). Needs the *Sensor rhythms and noisy faults* learning (`learn_health`, on by default); without it the fixed wait applies.

`dedupe_key` is `health:<detector>:<id>` (`health:offline:<device_id>`, `health:battery:<device_id>`,
`health:repair:<domain>:<issue_id>`, `health:entry:<entry_id>`, `health:reauth:<entry_id>`,
`health:updates`, `health:battery_group`). Grouped findings (offline per integration, battery group) rewrite
their title as well as their description when the affected set changes. Closing an auto issue by hand while the fault persists **snoozes** it for
`health_snooze_days` (7); after that it is reopened with a "Problem is back" comment. The label
`ignore` on an auto issue suppresses that fault for good. Auto issues go to the project chosen in the
options (default: key `FIX`, "Smart home fixes", created on demand) and to the optional default
assignee. The scan can be run by hand with the `scan_health` service / `homeboard/health/scan`
(`dry_run` lists what it would do without writing anything).

**First-scan review.** Until a person has looked at the first scan, the scanner (automatic scans only) creates
ONE issue (`dedupe_key` `review:health`, labels `auto`, `review`, `source` `health`) that lists the findings and
keeps its list current; scan results carry `skipped: "awaiting_review"` and every finding the action `held`.
Closing or deleting that issue, or a manual non-dry `scan_health`, sets `reviewed` (persisted in the store under
`health`) and the scanner goes ahead. A board that already has health issues, or a first scan with nothing to
find, counts as reviewed. `sensor.homeboard_auto_generated_issues` has the attribute `awaiting_review`.

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
| `homeboard/health/scan` (admin) | `dry_run?` | `{created, reopened, closed, suppressed, findings:[{key, summary, priority, detector}], waiting:[{key, summary, detector, waited_minutes, reported_after_minutes}]}` |

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
| `scan_health` | `dry_run?` | `{created, reopened, closed, suppressed, findings, waiting}` |

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
`/homeboard?kiosk` hides the chrome for wall tablets, `?project=HOME` selects a project, `?tab=insights` opens the Insights tab.

## 10. Version 0.2 additions (checklists, files, push, Assist, learning)

Design: `docs/DESIGN-0.2.md`. Everything here is additive; 0.1 clients keep working.

### 10.1 Store additions

Issue: `checklist: [{ "id", "text", "done" }]`, `attachments: [{ "id", "name", "mime", "size", "ts", "author", "source" }]`
(`source` = `upload` | `camera`). Top level: `learning: { ... }` (private to `insights.py`).

### 10.2 Payload additions

- Issue (list payload): `checklist_total`, `checklist_done`, `attachment_count`; for `type == "epic"` also
  `epic_total`, `epic_done` (child issues, done = category done). Issue detail (`issue/get`) additionally has
  `checklist` (the items) and `attachments`: `{ id, name, mime, size, ts, author, source, url, thumb_url }` where
  `url` / `thumb_url` are **signed paths** (valid one hour, usable in `<img src>` and `<a href>`; fetch the detail
  again when they expire).
- `settings.learning` = `{ defaults, patterns, workload, health, rhythm }` (booleans), `settings.attachments` = `{ enabled, max_mb }`,
  `settings.insights_open` = number of open suggestions (for a badge).

### 10.3 WebSocket additions

| type | params | result |
|------|--------|--------|
| `homeboard/checklist/add` | `issue_id`, `text` | item |
| `homeboard/checklist/update` | `issue_id`, `item_id`, `text?`, `done?` | item |
| `homeboard/checklist/remove` | `issue_id`, `item_id` | `{deleted}` |
| `homeboard/checklist/reorder` | `issue_id`, `item_ids` (complete list) | `{ok}` |
| `homeboard/attachment/remove` | `issue_id`, `attachment_id` | `{deleted}` |
| `homeboard/attachment/snapshot` | `issue_id`, `entity_id` (a `camera.*`) | attachment |
| `homeboard/insights/get` | - | insights (10.5) |
| `homeboard/insights/accept` | `suggestion_id` | `{applied, issue?, recurring_id?}` |
| `homeboard/insights/dismiss` | `suggestion_id` | `{dismissed}` |
| `homeboard/insights/forget` (admin) | `feature?` (`defaults` \| `patterns` \| `workload` \| `health` \| `rhythm`; omitted = all) | `{forgotten: [what was cleared]}` (defaults / patterns / workload are computed live from the issues, so only their dismissed suggestions are stored) |
| `homeboard/suggest` | `text`, `project?` | suggestion or `null` |

`homeboard/quick_add/preview` now also returns `suggestion` (10.4, or `null`) next to the parsed fields. `homeboard/quick_add`
and the `quick_add` service take `suggest?` (bool, default false over the service, the panel sends true when the user keeps
the chips): fields the text did not specify are filled from the suggestion.

**Files over HTTP** (signed-in users only, `hass.fetchWithAuth` from the frontend):
`POST /api/homeboard/upload` as `multipart/form-data` with fields `issue_id` and `file` -> the attachment JSON (with `url`,
`thumb_url`); 413 above `max_mb`, 415 for other types than jpeg / png / webp / gif / pdf, 404 unknown issue.
`GET /api/homeboard/files/<attachment_id>` and `.../thumb` are served with a valid `authSig` signature or a bearer token.

### 10.4 Suggestion (smart defaults)

`{ "assignee": "person.x" | null, "labels": ["bills"], "priority": "high" | null, "due_in_days": 3 | null,
"similar": [ { "key": "HOME-12", "summary": "...", "status": "Done" } ], "evidence": "based on 4 similar issues",
"confidence": 0.0-1.0 }` or `null` (feature off, or nothing similar). Only fields the quick-add text did not already set.

### 10.5 Insights

```jsonc
{
  "features": { "defaults": true, "patterns": true, "workload": true, "health": true, "rhythm": false },
  "suggestions": [ { "id": "...", "kind": "recurring" | "health_ignore" | "digest_time",
                     "title": "Make 'Order bin bags' a recurring chore?", "detail": "Created 4 times, about every 6 weeks",
                     "evidence": { "count": 4, "interval_days": 42 }, "proposal": { /* kind specific */ } } ],
  "learned": {
    "defaults": { "issues_analysed": 34, "top_labels": [ ["bills", 5] ], "people": [ { "person": "person.x", "issues": 12 } ] },
    "workload": { "people": { "person.x": { "open": 3, "done_30d": 8, "avg_days": 3.5 } },
                  "types": { "bug": 4.2 }, "labels": { "garden": 6.0 } },          // average days created -> done
    "rhythm":   { "people": { "person.x": { "samples": 2016, "grid": [[0.0, ...24 numbers 0..1], ...7 rows, Mon=0] } } },
    "health":   { "tracked_sensors": 812, "silent": [ { "entity_id": "sensor.x", "normal_minutes": 15, "silent_minutes": 190 } ],
                  "flapping": [ { "key": "health:offline:...", "summary": "...", "reopened": 3 } ],
                  "patient": 4 }
  }
}
```

Suggestion kinds and `proposal`: `recurring` = `{ project_id, summary, repeat, next_due, assignee, labels, priority }`;
`health_ignore` = `{ key, summary }` (accept = stop reporting that fault); `digest_time` = `{ person, time: "07:30" }`.
Accepting is always a user action; nothing is applied silently. `rhythm` is absent unless the feature is on.

### 10.6 Services and events

Services: `add_checklist_item`, `check_item`, `remove_checklist_item`, `attach_camera_snapshot` (`issue` or `project` +
`dedupe_key`, `camera`), `suggest` (response = suggestion), `send_digest` (`person?`), `forget_learning` (`feature?`).
Events: `homeboard_attachment_added`, `homeboard_attachment_removed` (issue data + `attachment`); checklist edits fire
`homeboard_issue_updated` with `changes.checklist` = `{from: "2/5", to: "3/5"}`; accepting a suggestion fires the normal
events of what it creates. New source value: `assist` is already present, `digest` is not an issue source.

### 10.7 Options (config entry)

Push: `person_notify` = `{ "person.x": ["mobile_app_x"] }` (empty = auto-detected from the person's device trackers),
`push_assigned`, `push_comment`, `push_overdue`, `push_reported_done` (default true), `digest_enabled` (default false),
`digest_time` (`"07:30"`). Assist: `assist_sentences` (default false: writes `config/custom_sentences/<lang>/homeboard.yaml`).
Files: `attachments_enabled` (default true), `max_upload_mb` (default 10). Checklists: `checklist_autodone` (default false: moving the
last item to done moves the issue to Done). Learning: `learn_defaults`, `learn_patterns`, `learn_workload`, `learn_health`
(default true), `learn_rhythm` (default **false**: reads person home / away state).

## 11. Version 0.3 additions (AI Fix)

Design and the reasons for every limit: `docs/DESIGN-0.3.md`. Everything here is additive and **admin only**
(a model answer can edit automations, so only administrators see or call any of it).

### 11.1 Store and payload

Store, top level: `ai: { "fixes": { "<issue_id>": Record }, "usage": { "day": "2026-11-23", "count": 3 } }`.

- Issue (list payload, administrators only): `ai: { state, rev, proposals, applied }` when the issue has a record,
  otherwise the key is absent. `state` is `running | ready | failed`; `rev` grows with every change of the record (refetch
  `homeboard/ai/get` when it changes); `proposals` counts proposals still `proposed`; `applied` counts applied ones.
- `settings.ai_fix = { enabled, entity, allow_protected }` (administrators only; `enabled` false when the option is off or
  no AI Task entity exists).

**Record** (what `homeboard/ai/get` returns as `record`):

```jsonc
{ "state": "ready", "rev": 3, "started": "<iso>", "finished": "<iso>|null", "entity": "ai_task.claude_ai_task",
  "note": "", "diagnosis": "plain text", "confidence": "low|medium|high", "error": null,
  "sent": { "chars": 11800, "entities": 14, "automations": 1 },
  "proposals": [ Proposal ] }
```

**Proposal** (the server also keeps the machine config; the client never sees or sends it):

```jsonc
{ "id": "p1", "kind": "automation_edit | automation_disable | reload_integration | manual_steps",
  "title": "Point the reminder at the new alarm panel", "explanation": "plain text", "risk": "low|medium|high",
  "target": "automation.alarm_reminder", "target_name": "Alarm reminder",   // null for manual_steps
  "status": "proposed | applied | dismissed | failed | undone",
  "blocked": null,                       // or { "code": "protected|not_editable|invalid|unknown_entities|stale", "message": "..." }
  "warnings": ["..."],                   // shown next to the diff
  "diff": "--- current\n+++ proposed\n@@ ...",   // unified diff (automation_edit), else ""
  "new_yaml": "alias: ...",              // the proposed automation as YAML (automation_edit), for "copy"
  "steps": ["..."],                      // manual_steps
  "applied_at": null, "undone_at": null, "error": null }
```

A `blocked` proposal can still be read and its `new_yaml` copied, but Apply is refused with the same code.
**All text from the model is untrusted: render it with `textContent`, never as HTML.**

### 11.2 WebSocket (all `require_admin`)

| type | params | result |
|------|--------|--------|
| `homeboard/ai/get` | `issue_id` | `{ enabled, ready, reason, entity, entity_name, limit: { used, max }, record }` |
| `homeboard/ai/preview` | `issue_id`, `note?` | `{ prompt, chars, entities, automations, redactions }` (exactly what would be sent, secrets masked) |
| `homeboard/ai/analyze` | `issue_id`, `note?` (the owner's hint, max 500 chars) | `{ state: "running" }` (returns at once; follow `issue.ai.rev`) |
| `homeboard/ai/apply` | `issue_id`, `proposal_id` | `{ proposal }` |
| `homeboard/ai/undo` | `issue_id`, `proposal_id` | `{ proposal }` |
| `homeboard/ai/dismiss` | `issue_id`, `proposal_id` | `{ proposal }` |

`reason` in `ai/get` explains `ready: false`: `disabled` (option off), `no_entity` (no AI Task entity), `choose_entity`
(several, none chosen), `unsupported` (no AI Task in this Home Assistant), `limit` (daily limit reached), or `null`.
`entity_name` is always set when `entity` is (the entity id when it has no friendly name). Error codes: `ai_disabled`,
`ai_unavailable`, `ai_limit`, `ai_busy` (already running), `blocked` (the proposal's `blocked.code` is in the message),
`not_proposed` (apply / dismiss of a proposal that is not `proposed`), `not_applied` (undo of something not applied
or not undoable), `stale` (undo refused: the automation was edited after the fix), `backup_missing`, `undo_failed`,
`not_found`. Every proposal also carries `undoable` (true only when `status` is `applied` and the kind is
`automation_edit` or `automation_disable`).

`rev` grows only when the record changes (not when `ready`, `reason` or `limit` change: refetch `ai/get` after a failed
call). A new analysis replaces the record but **keeps proposals that are `applied`**, so Undo stays possible; ids of new
proposals continue after the highest id in the record. A `failed` record can therefore still hold applied proposals.
Apply, undo and dismiss on one issue never overlap: the second of two simultaneous calls gets `not_proposed`.

### 11.3 Service and events

Service `ai_analyze` (`issue` or `project` + `dedupe_key`, `note?`; response `{ state }`). There is no service that applies a
proposal. Events: `homeboard_ai_proposal_ready` (`issue`, `key`, `proposals`), `homeboard_ai_fix_applied` and
`homeboard_ai_fix_undone` (`issue`, `key`, `proposal`, `kind`, `target`). Applying or undoing also writes a comment and an
activity line on the issue.

### 11.4 Options (config entry)

`ai_fix_enabled` (default false), `ai_fix_entity` (an `ai_task.*` entity; empty = the preferred one, else the only one),
`ai_fix_allow_protected` (default false), `ai_fix_daily_limit` (default 20), `health_automations` (default false: the
detector for automations that use missing entities, key `health:automation:<automation entity id>`, section 3b).

## 12. Version 0.4 additions (Habits: automation ideas in the inbox)

Design: `docs/DESIGN-0.4.md`. Administrators only for everything that creates or removes something.

### 12.1 Suggestions of kind `automation` (in `insights/get` `suggestions`, the inbox)

```jsonc
{ "id": "habit:time:light.hall:on:weekdays", "kind": "automation",
  "title": "Turn on Hall light at 06:35 on weekdays?",
  "detail": "It turned on on 17 of the last 21 weekdays between 06:28 and 06:42 (assuming no automation did it).",
  "evidence": { "pattern": "routine | follow_up | switch_back", "days": 17, "of": 21, "share": 0.81,
                "window": ["06:28", "06:42"], "samples": 17 },
  "proposal": { "alias": "Hall light on at 06:35 (weekdays)", "description": "Suggested by Homeboard from habits ...",
                "entity_id": "light.hall", "trigger_entity": null, "yaml": "alias: ...\ntriggers: ..." } }
```

`proposal.yaml` is for display and "copy"; the machine config stays on the server (the client only sends the
suggestion id). `evidence.window` is present for `routine`, `evidence.delay_minutes` for `switch_back`. `days` / `of` count days for every
pattern (days with a match out of days with data / activations); `samples` / `out_of` count cases (follow_up, switch_back).
An idea that `habits/create` refuses with `exists` leaves the inbox at once (it is already done); one refused with `blocked`
stays until the next scan. Suggestions of kind `automation` and `learned.habits` (including `created`) are only in `insights/get` for **administrators**
(a non-administrator gets the page without them, `settings.insights_open` does not count them, and `insights/dismiss` on one
is `unauthorized`); the three `habits/*` commands are administrator-only too. `insights/forget` and `forget_learning` accept
`habits`.
Pattern names are for icons / grouping; unknown patterns render with the generic text.

### 12.2 `insights/get` additions

`features.habits` (bool), `learned.habits` (only when the feature is on):
`{ last_scan: "<iso>|null", scanned_entities: 120, days: 28, error: null | "no_recorder" | "no_history" | "failed",
   created: [ Created ] }`. `settings.learning.habits` (bool) and `settings.insights_open` count these suggestions too.

**Created** (undoable list, newest first, at most 20; `habits/create` returns one of these, with the automation's `alias`): `{ id, suggestion_id, auto_id, entity_id, alias, ts,
state: "created | undone", edit_url: "/config/automation/edit/<auto_id>" }`. A created automation is **off**.

### 12.3 WebSocket (admin only)

| type | params | result |
|------|--------|--------|
| `homeboard/habits/scan` | - | `{ scanned, found, days, error }` (runs now; can take several seconds) |
| `homeboard/habits/create` | `suggestion_id` | `{ created: Created }` |
| `homeboard/habits/undo` | `created_id` | `{ created: Created }` (state `undone`) |

`insights/accept` on a suggestion of kind `automation` is refused with code `use_habits_create`. Error codes of
create / undo: `habits_disabled`, `not_found`, `exists` (an automation covers it now), `blocked` (protected or
rejected by validation; the message says why), `not_editable` (automations.yaml cannot be written), `stale`
(undo refused: the automation was edited), `backup_missing`, `create_failed` (it did not load; rolled back).
Create also fires the bus event `homeboard_habit_automation_created` (`suggestion_id`, `auto_id`, `entity_id`).

### 12.4 Service and options

Service `scan_habits` (response `{ scanned, found, days, error }`). Option `learn_habits` (default **false**).
The learning `forget` feature `habits` clears the cached candidates and the dismissed habit ideas (not the
automations that were created).
