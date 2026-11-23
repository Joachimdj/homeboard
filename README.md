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
- **AI Fix** (opt-in): an AI diagnoses a smart-home issue and proposes a fix, for example a corrected
  automation. It only proposes: you review the change, press Apply, and can undo it
  ([how it works](#ai-fix)).
- **Checklists and photos**: subtasks on every issue, photos and PDFs on issues (also straight from a
  camera snapshot), stored privately.
- **Push to the right person**: assigned to you, comments, deadlines, a morning digest, on your own
  phone, with quiet hours.
- **Learns, but only suggests**: smart defaults for new issues, recurring-chore suggestions,
  workload and speed, sensor rhythms, and (opt-in) everyday home / away rhythm
  ([how it works](#insights-homeboard-learns)).
- **Automation ideas in an inbox** (opt-in): Homeboard looks at how your lights, switches and sensors have been
  used and suggests automations ("turn on the hall light at 06:30 on weekdays"). You create them with one press,
  they start switched off, and you can undo ([how it works](#habits-automation-ideas-in-your-inbox)).
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

### Assist sentences (optional)

Switch on **Configure > Photos, files and Assist > Install Assist sentences** and Homeboard writes
`homeboard.yaml` into `config/custom_sentences/en/` and `.../da/` (marked "Managed by Homeboard"; it never
touches a file without that mark, and removes its own again when you switch the option off or delete the
integration). Assist then understands, in English and Danish:

| Say | Does |
|-----|------|
| "add fix the gate due friday to the board", "put bulbs on the kitchen board" | creates an issue (quick-add words work; you become the reporter) |
| "what is overdue" | counts and names the first three |
| "what is on my list" / "what am I working on" | your open issues, in progress first |
| "what is Padmaja working on" | the same for someone else |
| "mark HOME-12 as done", "the gate is done" | moves it to Done; if several match it says which, and moves nothing |
| "how is the board doing" | open / overdue / due soon, and the home-health count |
| "tilføj køb pærer til tavlen", "hvad er forsinket", "hvordan går det med tavlen" | the same in Danish |

"What is on **my** list" needs to know who is speaking, so it works in the Assist dialog, the app and
`conversation.process` calls by a signed-in user, not from a voice satellite (satellites have no user).
Details and limits: [docs/ASSIST_NOTES.md](docs/ASSIST_NOTES.md).

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

## Checklists and photos

Every issue can have a **checklist** (progress `3/5` on the card; epics show how many of their
issues are done). Switch on "Move an issue to Done when its checklist is complete" in the options if you
want that. From automations: `homeboard.add_checklist_item`, `check_item`, `remove_checklist_item`.

**Photos and PDFs** (jpeg, png, webp, gif, pdf, up to 10 MB each) can be added in the issue dialog by
button, paste or drag and drop, or taken from a camera:

```yaml
action: homeboard.attach_camera_snapshot
data:
  project: FIX
  dedupe_key: health:offline:abc123    # or issue: FIX-4
  camera: camera.front_door
```

Files are stored in `config/homeboard_files/` (never under `www`, so not public) and served only to
signed-in users through short-lived signed links. The type is checked from the file's content, not its name,
so a renamed program or an SVG is refused. Photos from phones may contain GPS data in their metadata: they are
stored as uploaded.

## Push to the right person

Each Home Assistant person is notified on their own phone, detected from their `mobile_app` device tracker
(or chosen in **Configure > People and push**):

| You are told when | Option |
|-------------------|--------|
| an issue is assigned to you (not when you assign it to yourself) | `push_assigned` |
| someone comments on an issue you own or reported | `push_comment` |
| one of your issues is overdue or due soon | `push_overdue` |
| an issue you reported is done (by someone else) | `push_reported_done` |
| every morning: your open and overdue issues (off by default) | `digest_enabled`, `digest_time` |

Pushes that are not urgent wait during **quiet hours** (22:00-07:00 by default) and, if rhythm learning is
on, while you are away; they arrive together afterwards (more than 3 become one "N updates" push). Priority
`highest` and the label `security` always go straight through. `homeboard.send_digest` sends a digest now
(Developer tools), and nothing is sent when you have nothing open.

## Insights: Homeboard learns

Switch each feature on or off in **Configure > Learning**. Everything is plain statistics kept inside Home
Assistant (nothing leaves your network), shown on the **Insights** tab with the evidence, and Homeboard
**only suggests**: you accept or dismiss each one. **Forget** buttons wipe what is stored.

| Feature | What it learns | What you get |
|---------|---------------|--------------|
| Smart defaults | which person, labels, priority and lead time go with similar titles | grey suggestion chips under the quick-add bar, one tap to apply (`homeboard.suggest`, or `suggest: true` on `quick_add`) |
| Patterns | the same task created again and again at a regular rhythm | "Make 'Order bin bags' a recurring chore?" (accept creates it) |
| Workload and speed | how long things take, per person, type and label; who is busiest | numbers on the Insights tab, and a "least busy person" hint when nothing else decides |
| Sensor rhythms and noisy faults | how often each sensor normally reports; faults you keep closing or that keep coming back | a "stopped reporting" health issue for a sensor that went quiet, and "Stop reporting this?" suggestions |
| Everyday rhythm (**off by default**) | for each person, hour by hour and weekday by weekday, whether they are home (counts only: no places, no coordinates) | a better morning-digest time, and pushes held while someone is away |

Defaults, patterns and workload are computed live from the issues on the board, so they learn from what is
there (deleting issues makes them forget). Sensor rhythms need about a dozen observed updates per sensor, and
the rhythm needs roughly four weeks of data before it suggests anything. The rhythm feature reads each
person's home / away state: tell the people it concerns before you switch it on.

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
`create_recurring`, `update_recurring`, `delete_recurring`, `run_recurring`, `scan_health`,
`add_checklist_item`, `check_item`, `remove_checklist_item`, `attach_camera_snapshot`, `suggest`,
`send_digest`, `forget_learning`.
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
| Offline devices | all main entities of a device have been unavailable for 60 minutes (3 or more devices of one integration are merged into one issue). TVs, speakers, light bulbs and browsers / phones are skipped, they are off on purpose | high for security devices, else medium |
| Low batteries | a battery sensor is below 20 % (or a binary battery sensor is on). Security devices (smoke, doors, motion, ...) get an issue each; every other battery goes into **one** issue ("5 batteries are running low") listed lowest first. Robot mowers, vacuums and phones are skipped, they are recharged | high for security devices, else medium |
| Integration problems | a config entry fails to load or keeps retrying, or waits for a new sign-in | medium, sign-in high |
| Repairs | a Home Assistant repair is open | by severity |
| Updates (off by default) | one grouped issue listing pending updates | low |
| Automations (off by default) | an enabled automation uses entities that no longer exist ([AI Fix](#ai-fix) can propose the repair) | medium, high when it involves the alarm |

Rules that keep it calm:

- Ignores disabled, hidden and diagnostic-only entities, helpers (template, group, ...) and registry
  ghosts.
- Waits 10 minutes after Home Assistant starts, and a problem must be seen on two scans in a row
  before an issue appears and be gone for two scans before it is closed.
- **The very first scan creates nothing but one "Review" issue** that lists what it found. Close that issue to let
  Homeboard create the real ones (or run `scan_health`, which goes ahead right away). That way a fresh
  install never floods your board with months of old faults.
- At most 15 open auto issues (highest priority first; change it in the options).
- Issues close themselves ("Resolved automatically") and reopen with "Problem is back" if the fault
  returns.
- **Close an auto issue by hand and it is snoozed for 7 days.** Add the label `ignore` to stop that
  fault for good.
- Security devices (doors, windows, motion, smoke, gas, water, locks, cameras, alarm panels) get the
  label `security` and priority high.

Try it any time: call **homeboard.scan_health** with `dry_run: true` (Developer tools > Actions); it lists
what would be created without changing anything. A manual scan (without dry run) acts immediately.
Switch the whole thing off, exclude entities and integrations, or also report the normally-off devices
(TVs, bulbs, phones, robot mowers) in **Configure > Smart home health**.

## Habits: automation ideas in your inbox

Switch on **Configure > Learning > Habit ideas** and Homeboard reads the recorder history of your **lights, switches,
fans, covers and motion / door sensors** (only inside Home Assistant, nothing is sent anywhere, no AI involved) and
looks for habits. The ideas land in the **Insights** tab, in the inbox *Automation ideas*:

| Idea | Looks like | Rule |
|------|-----------|------|
| Routine | "Turn on the hall light at 06:30 on weekdays" | switched the same way within a 30-minute window on at least 5 days and at least 70 % of the days of its day group (every day, weekdays, weekends) |
| Follow-up | "Turn on the hall light when the hall motion sensor detects something" | the light turned on within a minute of the sensor at least 70 % of the time (at least 8 activations on at least 5 days); only after dark when it always happened after dark |
| Switch back | "Turn off the hall light 4 minutes after the motion has stopped" | the light went off 1-15 minutes after the sensor went quiet at least 70 % of the time; the median delay is used |

Every idea shows its evidence ("on 11 of the last 11 days, between 06:30 and 06:32") and the automation as YAML.
**Create** (administrators, two-step) writes it to `automations.yaml` with a backup, checks it with Home Assistant's own
validation and **switches it off**: you review it in Home Assistant and switch it on when you are happy. **Undo** removes
it again (not if you edited it in the meantime).

What it does not do: switches and smart plugs only ever get "turn off" ideas (a plug may be a heater); it never suggests anything for persons, device trackers, media players, climate, `alarm_control_panel`,
`siren`, `lock` or `valve`, nor for garage doors and gates, nor for switches, fans or covers whose name says alarm, siren, lock, garage, gate, door, valve,
heater, oven, pump and the like, nor for roof windows and awnings. Entities you excluded in the smart-home health options are excluded here too. It does not suggest
what an automation already does (same entity, same direction). It cannot tell who or what caused a change, so a person, a
button or an old script may be behind a habit: that is why you review before switching on.

Good to know: Home Assistant's recorder keeps **10 days** of history unless you raise `purge_keep_days`. Homeboard uses what
there is (it needs at least 7 days; up to 28 are used), so a longer `purge_keep_days` gives steadier ideas. Only administrators see the ideas. The scan runs at
04:00 and when you press **Scan now**; the service `homeboard.scan_habits` does the same. *Forget* on the Insights page clears
the ideas (created automations stay).

## AI Fix

Open a smart-home issue (for example one the health scanner made), press **Analyse with AI**, and an AI
tells you what is probably wrong and proposes up to three fixes:

| Proposal | What *Apply* does | Undo |
|----------|------------------|------|
| Edit an automation | replaces that automation in `automations.yaml` (shown as a diff first) | yes |
| Disable an automation | switches it off | yes |
| Reload an integration | reloads a config entry that failed to set up | no |
| Manual steps | adds the steps (replace the battery, re-pair ...) to the issue's checklist | no |

It uses the **AI Task** entity of Home Assistant that you already have (Anthropic, OpenAI, Google, Ollama, ...),
so Homeboard needs no API key. Switch it on and pick the entity in **Configure > AI Fix**.

How it stays safe:

- **The AI only proposes.** Nothing changes until an administrator presses *Apply*. There is no service or
  automation that applies a proposal.
- **Backup and undo.** Before an automation is rewritten, `automations.yaml` is copied to
  `config/homeboard_backups/`. After the change Homeboard checks that the automation loads; if not, it puts the
  old one back by itself. *Undo* restores just that automation.
- **Only what it was shown.** The AI may only touch the automations and integrations Homeboard listed in the
  question. Anything else it names is thrown away. A proposed automation must pass Home Assistant's own
  validation and may not use entities that do not exist.
- **Hands off the alarm.** Automations that control `alarm_control_panel`, `siren`, `lock`, `valve` or Alarmo can
  be analysed (you get the corrected YAML to copy) but Homeboard will not write them, unless you allow it in the
  options. The check is wide: it also catches upper case, devices / areas / labels / groups that contain such an
  entity, and anything it cannot read from the config (templated services or targets, `entity_id: all`, scripts and
  scenes), and it runs again when you press Apply.
- **Stale proposals are refused.** If the automation changed after the analysis, Apply refuses; analyse again.
  Undo likewise refuses to overwrite something you edited after the fix (the backup copy is named in the message).
  A change too large to show completely in the diff is blocked too: you always see everything that would change.
- **You can see what is sent.** *Show what is sent* displays the exact text before anything leaves Home Assistant:
  the issue, the automation, the entities involved and look-alike replacements. Values from `secrets.yaml` and keys
  named `password`, `token`, `api_key`, `code`, `webhook_id` ... are replaced by placeholders and put back when
  you apply. Error messages are cleaned the same way. Secrets shorter than 4 characters are not masked. The text goes to the AI Task entity you chose, which may be a cloud service.
- **Cheap by default.** One analysis at a time, at most 20 per day (change it in the options), only when you press
  the button or call `homeboard.ai_analyze`.

The new detector **Automations that use entities that no longer exist** (Configure > Smart home health, off by
default) makes an issue for each enabled automation that points at a deleted or renamed entity, which Home
Assistant itself never reports. Try it with `homeboard.scan_health` and `dry_run: true` first.

Limits: only UI automations (`automations.yaml`) can be written; YAML-mode automations and scripts are
explained but not edited. `!secret` and `!include` tags are written back as plain values, exactly as Home
Assistant's own automation editor does.

## Entities

| Entity | What |
|--------|------|
| `todo.<project>` | open issues (and recently done ones); works with Assist |
| `calendar.<project>_due_dates` | open issues with a due date |
| `sensor.<project>_open_issues`, `_overdue`, `_due_soon`, `_unassigned`, `_last_activity` | counts and timestamp (attributes list the top issues) |
| `sensor.<project>_<status>` | issues in one column (`category`, `wip` as attributes) |
| `binary_sensor.<project>_has_overdue` | problem when anything is overdue |
| `sensor.homeboard_open_issues`, `_overdue_issues`, `_issues_due_soon`, `_auto_generated_issues`, `_last_activity` | totals over all projects |
| `sensor.homeboard_suggestions` | number of open learning suggestions |
| `sensor.homeboard_<person>_assigned` | open issues per person (attributes: overdue, in progress, done in 7 days, next issues) |

## Options

**Settings > Devices & services > Homeboard > Configure** is a menu of short sections: general (due-soon
window, auto-archive, checklist auto-done, sidebar title / icon / admin only, people with sensors),
household alerts, people and push, photos / files / Assist, smart-home health, AI Fix, and learning.
Each section saves when you submit it.

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

Sprints, burndown, custom fields, per-transition rules,
time tracking, import from Jira / Kanboard / CSV and export, device triggers in the automation
editor, per-person push targets, and automatic installation of Assist custom sentences.

## License

MIT, see [LICENSE](LICENSE).
