<p align="center">
  <img src="custom_components/homeboard/brand/logo@2x.png" alt="Homeboard" width="420">
</p>

# Homeboard

A Jira-inspired kanban board and issue tracker that lives **inside Home Assistant**: projects with
issue keys (`HOME-12`), a drag-and-drop board that works on a phone and on a wall tablet, a status
overview, quick add by text, Assist or Siri, automation hooks, recurring chores, and a smart-home
health check that **creates tasks for the things that need fixing by itself**.

Everything runs inside Home Assistant: no server, no cloud, no extra add-on.

> Inspired by Jira's vocabulary (projects, issue types, priorities, status categories, backlog,
> swimlanes). Not affiliated with or endorsed by Atlassian. The code, name and icons are original.

## Features

- **Board**: columns are your own statuses (To do, In progress, Done, ...), cards can be dragged with
  mouse or finger, soft WIP limits, quick filters (My issues, Unassigned, Overdue, Due soon, label,
  type, search), swimlanes by assignee or priority.
- **Backlog, List and Summary** views. The Summary is the status overview: counts per status,
  overdue, due soon, last activity, issues per person, home health.
- **Issues** have a key, type (task, bug, story, epic), priority, labels, assignee and reporter (HA
  `person` entities), due date, epic link, comments and an activity log.
- **Quick add**: `bug: gate squeaks @joachim !high #garden due friday`, from the panel, a card, Assist,
  Siri / Shortcuts, or the `homeboard.quick_add` service. Optional microphone button where the
  browser supports speech recognition.
- **Automations**: bus events for everything that happens to an issue, services with responses, and
  dedupe keys so a sensor can open an issue without ever creating the same one twice.
- **Recurring chores**: "put out the bins every Wednesday", "pay rent on the 1st", created ahead of time.
- **Smart-home health**: issues for offline devices, low batteries, Home Assistant repairs and
  failing integrations, closed again when the fault is gone ([details](#smart-home-health)).
- **Native entities**: a `todo` list and a `calendar` per project, sensors for counts, per status and
  per person, so dashboards, Assist and automations can use the numbers.
- **No manual setup of the frontend**: the sidebar panel and the Lovelace cards register themselves.
  No Lovelace resource to add.

## Installation

### Marketplace (HACS) as a custom repository

1. Open the Marketplace (HACS) in Home Assistant, menu **Custom repositories**.
2. Add `https://github.com/Joachimdj/homeboard` with category **Integration**.
3. Download **Homeboard** and **restart Home Assistant** (a new integration always needs a restart).
4. **Settings > Devices & services > Add integration > Homeboard**.

### Manual

1. Copy the folder `custom_components/homeboard` into `config/custom_components/` of Home Assistant.
2. Restart Home Assistant and add the integration as above.

Requires Home Assistant 2026.10 or newer. Only one instance can be added.

## Getting started

1. Add the integration; leave "Create a starter project (HOME)" ticked.
2. Open **Board** in the sidebar. Type a line in the quick-add bar and press Enter.
3. Drag the card to another column.
4. Add the **Homeboard board**, **Homeboard status** or **Homeboard quick add** card to a dashboard
   (they show up in the card picker).
5. Optional: **Settings > Devices & services > Homeboard > Configure** for notifications, sidebar title
   and the smart-home health options.

Each project is a device with its own entities. Rename a project or a column and the entity ids stay
the same.

## Quick add

Tokens can be anywhere in the line, everything else becomes the title.

| Token | Meaning |
|-------|---------|
| `@joachim`, `@me` | assignee (name or id, unique prefix is enough; `@me` = you) |
| `!high`, `!1` ... `!5` | priority: `!highest` `!high` `!medium` `!low` `!lowest`, or 1 (highest) to 5 |
| `#garden` | label |
| `due tomorrow`, `due fri`, `due 2026-12-01`, `due 1/12`, `due in 3 days`, `due next week`, `due friday 18:00` | due date (weekdays never mean today; `next week` = next Monday) |
| `bug:`, `story:`, `task:`, `epic:` at the start | issue type |
| `HOME:` at the start | project key |

Danish words work too for dates and priorities (`i morgen`, `fredag`, `om 2 dage`, `!vigtig`).

### Assist (voice)

Each project has a `todo` list entity named after the project, so the built-in Assist sentence works
with no setup: *"Add light bulbs to the Home list"* creates `HOME-n` in the first To do column.
Give the entity an alias if you want a friendlier name. Completing an item in a native to-do card
moves the issue to the first Done column.

### Siri / Shortcuts

In the Shortcuts app: **Dictate Text** then **Perform action** (Home Assistant app) with
`homeboard.quick_add` and the data

```yaml
text: "<Dictated Text>"
source: siri
```

### Voice in the browser

The microphone button in the quick-add bar uses the browser's speech recognition. It only appears
where the browser supports it, and most browsers want HTTPS (Home Assistant Cloud or your own
certificate) for the microphone. It is a convenience; the Assist and Siri routes do not depend on it.

## Dashboard cards

All three are auto-registered. Add them from the card picker or by YAML:

```yaml
type: custom:homeboard-board-card
project: HOME            # key or id; empty = first project
title: House board
show_backlog: false
swimlanes: none          # none | assignee | priority
filter: ""               # my | unassigned | overdue | due_soon | auto
kiosk: false             # bigger touch targets for a wall tablet
max_height: 600
```

```yaml
type: custom:homeboard-status-card
projects: [HOME, FIX]    # empty = all
show_people: true
show_health: true
```

```yaml
type: custom:homeboard-quick-add-card
project: HOME
title: Add to the board
```

Wall tablet: open `/homeboard?kiosk` for the full-page panel without chrome. Deep links:
`/homeboard?issue=HOME-12` opens an issue, `/homeboard?project=HOME` selects a project.

## Automations

### Events

Every issue event carries `project`, `key`, `issue_id`, `summary`, `type`, `priority`, `status`,
`category`, `assignee`, `reporter`, `labels`, `due`, `actor`, `source` and `url`.

| Event | When | Extra data |
|-------|------|------------|
| `homeboard_issue_created` | an issue is created | |
| `homeboard_issue_updated` | fields change | `changes` |
| `homeboard_issue_moved` | status changes | `from_status`, `to_status`, `from_category`, `to_category` |
| `homeboard_issue_assigned` | assignee changes | `from_assignee`, `to_assignee` |
| `homeboard_issue_commented` | comment added | `comment` |
| `homeboard_issue_completed` / `_reopened` | moved into / out of a Done column | |
| `homeboard_issue_deleted` | deleted | |
| `homeboard_issue_overdue` | due time passed (once) | |
| `homeboard_issue_due_soon` | entered the due-soon window (once) | |
| `homeboard_wip_exceeded` | a column went over its WIP limit | `status`, `wip`, `count` |
| `homeboard_project_changed` | project created / updated / deleted | `action` |

### Services

`create_issue`, `update_issue`, `move_issue`, `assign_issue`, `add_comment`, `delete_issue`,
`quick_add`, `create_project`, `update_project`, `add_status`, `update_status`, `remove_status`,
`create_recurring`, `update_recurring`, `delete_recurring`, `run_recurring`, `scan_health`.
Issue services take `issue: HOME-12` **or** `project` + `dedupe_key`. Most return a response
(`key`, `id`, ...) you can use with `response_variable`.

### Open an issue from a sensor, close it when it recovers

```yaml
automation:
  - alias: Freezer too warm
    triggers:
      - trigger: numeric_state
        entity_id: sensor.freezer_temperature
        above: -12
        for: "00:30:00"
    actions:
      - action: homeboard.create_issue
        data:
          project: HOME
          summary: "Freezer is too warm ({{ states('sensor.freezer_temperature') }} °C)"
          type: bug
          priority: high
          labels: [kitchen]
          dedupe_key: freezer_warm      # never opens a second issue while one is open
          source: sensor

  - alias: Freezer recovered
    triggers:
      - trigger: numeric_state
        entity_id: sensor.freezer_temperature
        below: -15
    actions:
      - action: homeboard.move_issue
        data:
          project: HOME
          dedupe_key: freezer_warm
          status: Done
```

`on_duplicate` decides what happens when an open issue with the same key exists: `skip` (default),
`comment` (adds a comment) or `reopen` (also revives a done one).

### Notify when something is done

```yaml
automation:
  - alias: Tell me when a chore is done
    triggers:
      - trigger: event
        event_type: homeboard_issue_completed
    actions:
      - action: notify.mobile_app_my_phone
        data:
          title: "Done: {{ trigger.event.data.key }}"
          message: "{{ trigger.event.data.summary }}"
```

The options flow can send these push notifications for you (done, overdue, due soon, new
high-priority auto issues) to the notify services you pick.

## Recurring chores

Create them with the `create_recurring` service or in the project settings of the panel:

```yaml
action: homeboard.create_recurring
data:
  project: HOME
  summary: Put out the bins
  repeat: { unit: week, weekdays: [2] }   # Monday = 0
  next_due: "2026-12-02"
  create_days_before: 1
  assignee: person.padmaja
```

An issue is created `create_days_before` days ahead, with the due date set. While the previous issue
is still open no second one is made (`skip_if_open`). After downtime only the most recent missed
occurrence is created, never a pile.

## Smart-home health

Homeboard looks at your smart home every 5 minutes and keeps a project (default key **FIX**, "Smart
home fixes", created on demand) up to date:

| Detector | Creates an issue when | Priority |
|----------|----------------------|----------|
| Offline devices | all main entities of a device have been unavailable for 60 minutes (3 or more devices of one integration are merged into one issue) | high for security devices, else medium |
| Low batteries | a battery sensor is below 20 % (or a binary battery sensor is on), one issue per device | high for security devices, else medium |
| Integration problems | a config entry fails to load or keeps retrying, or waits for a new sign-in | medium, sign-in high |
| Repairs | a Home Assistant repair is open | by severity |
| Updates (off by default) | one grouped issue listing pending updates | low |

Rules that keep it calm:

- Ignores disabled, hidden and diagnostic-only entities, helpers (template, group, ...) and registry
  ghosts.
- Waits 10 minutes after Home Assistant starts, and a problem must be seen on two scans in a row
  before an issue appears and be gone for two scans before it is closed.
- At most 30 open auto issues (highest priority first).
- Issues close themselves ("Resolved automatically") and reopen with "Problem is back" if the fault
  returns.
- **Close an auto issue by hand and it is snoozed for 7 days.** Add the label `ignore` to stop that
  fault for good.
- Security devices (doors, windows, motion, smoke, gas, water, locks, cameras, alarm panels) get the
  label `security` and priority high.

Try it first: call **homeboard.scan_health** with `dry_run: true` (Developer tools > Actions); it lists
what would be created without changing anything. A manual scan (without dry run) acts immediately.
Switch the whole thing off, or exclude entities and integrations, in **Configure > Smart home health**.

## Entities

| Entity | What |
|--------|------|
| `todo.<project>` | open issues (and recently done ones); works with Assist |
| `calendar.<project>_due_dates` | open issues with a due date |
| `sensor.<project>_open_issues`, `_overdue`, `_due_soon`, `_unassigned`, `_last_activity` | counts and timestamp (attributes list the top issues) |
| `sensor.<project>_<status>` | issues in one column (`category`, `wip` as attributes) |
| `binary_sensor.<project>_has_overdue` | problem when anything is overdue |
| `sensor.homeboard_open_issues`, `_overdue_issues`, `_issues_due_soon`, `_auto_generated_issues`, `_last_activity` | totals over all projects |
| `sensor.homeboard_<person>_assigned` | open issues per person (attributes: overdue, in progress, done in 7 days, next issues) |

## Options

**Settings > Devices & services > Homeboard > Configure** has three short pages: general (due-soon
window, auto-archive of done issues, sidebar title / icon / admin only, people with sensors),
notifications, and smart-home health.

## Troubleshooting

- The panel or cards do not appear after install: restart Home Assistant, then hard-refresh the
  browser (Ctrl/Cmd+Shift+R). The frontend files are served under a versioned path, so an update
  never serves stale files after the restart.
- Only administrators can create projects and edit columns; everyone can add and move issues.
- Data lives in `config/.storage/homeboard` and is part of Home Assistant backups.

## Development

```bash
python3.14 -m venv .venv && . .venv/bin/activate     # Home Assistant 2026.x needs Python 3.14+
pip install -r requirements-dev.txt home-assistant-frontend
pytest --cov=custom_components/homeboard             # backend tests
ruff check . && ruff format --check .
node --test tests/js/                                # pure frontend logic (Node 20+)
python scripts/check_hacs.py                         # local mirror of the HACS rules
python scripts/gen_strings.py                        # regenerates services.yaml, strings and translations
scripts/check_hassfest.sh                            # runs Home Assistant's hassfest locally
python -m http.server 8099                           # then open http://localhost:8099/tests/browser/
```

The browser harness (`tests/browser/`) is a mock Home Assistant with demo data for working on the
panel and cards without a real instance. The data contract (store, websocket API, events, services)
is in [docs/PROTOCOL.md](docs/PROTOCOL.md), the design in [docs/DESIGN.md](docs/DESIGN.md).

## Listing in the default Marketplace

A custom repository works for everyone straight away. To appear in the default list the repository
needs to be public with a description and topics, have issues enabled, publish a GitHub release
(`gh release create v0.1.0`), pass the `hacs/action` and `hassfest` workflows, and be added through a
pull request to [`hacs/default`](https://github.com/hacs/default).

## Not in version 1

Sprints, burndown, subtasks and checklists, attachments, custom fields, per-transition rules,
time tracking, import from Jira / Kanboard / CSV and export, device triggers in the automation
editor, per-person push targets, and automatic installation of Assist custom sentences.

## License

MIT, see [LICENSE](LICENSE).
