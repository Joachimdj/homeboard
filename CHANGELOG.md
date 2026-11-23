# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Versions follow
[Semantic Versioning](https://semver.org/); while the project is 0.x only the patch number is bumped
for small changes.

## [0.3.0] - 2026-11-23

### Added
- **AI Fix.** Press *Analyse with AI* on a smart-home issue: Home Assistant's AI Task entity diagnoses it and
  proposes up to three fixes (edit an automation, switch it off, reload an integration, or manual steps that go
  on the checklist). The AI only proposes. An administrator reviews the diff and presses *Apply*; the whole
  `automations.yaml` is backed up first (`config/homeboard_backups`), the automation is checked after the
  reload and rolled back by itself if it does not come up, and *Undo* restores it. Details in
  `docs/DESIGN-0.3.md`.
- Guard rails: the AI may only touch what it was shown; a proposed automation must pass Home Assistant's own
  validation and may not use entities that do not exist; automations that control the alarm, sirens, locks, valves
  or Alarmo are never written unless allowed in the options; a proposal for an automation that changed since the
  analysis is refused; secrets (`secrets.yaml` values and keys such as `password`, `token`, `code`) are masked in
  what is sent and in what is shown, and put back when applying.
- The protected check is wide (case, templates, device / area / label / group targets, scripts, blueprints) and
  runs again at Apply; Apply and Undo never overlap, backups have unique names, and Undo refuses to overwrite an edit
  made after the fix. Found by an independent review before release; see `docs/DESIGN-0.3.md` section 5b.
- *Show what is sent* previews the exact text before anything leaves Home Assistant. One analysis at a time,
  at most 20 a day by default.
- Service `homeboard.ai_analyze`, websocket `homeboard/ai/*` (admin only), events `homeboard_ai_proposal_ready`,
  `homeboard_ai_fix_applied`, `homeboard_ai_fix_undone`. There is deliberately no service that applies a proposal.
- New smart-home health detector (off by default): **Automations that use entities that no longer exist**, one
  issue per enabled automation, high priority when it involves the alarm.
- Options: *Configure > AI Fix* (switch on, AI Task entity, allow protected automations, daily limit).

## [0.2.2] - 2026-11-23

### Fixed
- **No close button on phones**: Home Assistant draws under the notch and status bar, so the header of a
  full-screen dialog (with the close button) ended up behind them on iPhones. Dialog headers and footers now
  respect the safe area, and the issue dialog has a big **Close** button at the bottom on phones. Long project
  names no longer push the header buttons out of view.

## [0.2.1] - 2026-11-23

Calmer smart-home health scanner, based on what the first real install showed (35 issues at once, most of
them noise).

### Changed
- **Low batteries are grouped**: security devices (smoke, doors, motion, ...) still get an issue of their own,
  every other battery goes into one issue ("5 batteries are running low", lowest first). The title follows the
  count. Old per-device battery issues close themselves ("no longer detected") when the group takes over.
- **Things that are off on purpose are skipped**: televisions, speakers and other media players, remotes,
  light-only devices (bulbs on a wall switch), Browser Mod browsers and phones are no longer reported offline,
  and robot mowers, vacuums, phones and anything with a charging sensor are no longer reported as "replace
  battery". The new option "Also report TVs, speakers, light bulbs, robot mowers and phones" brings them back.
- The default cap of open auto issues is **15** (was 30). A cap you saved yourself is kept.
- The title of a grouped offline issue ("Hue: 3 devices are offline") now follows the count too.

### Added
- **First-scan review**: on a fresh install the scanner no longer creates dozens of issues at once. It creates
  ONE "Review" issue listing what it found; closing it (or running `scan_health`) lets the scanner go ahead.
  Boards that already have auto issues are not held back. New attribute `awaiting_review` on
  `sensor.homeboard_auto_generated_issues`.

### Fixed
- No more deprecation warnings from Home Assistant 2026.10+ for the device registry (`devices` mapping and
  `primary_config_entry`).

## [0.2.0] - 2026-11-23

### Added
- **Push to the right person**: per-person notifications on their own phone (detected from the
  `mobile_app` tracker or chosen in the options) for assignments, comments, deadlines and issues you reported
  being done; an optional morning digest (`homeboard.send_digest`); quiet hours; non-urgent pushes are held and
  delivered together.
- **Assist** (opt-in): six intents in English and Danish (add, overdue, my list, what is X working on, mark
  done, board status) with sentence files installed only when switched on.
- **Checklists** on issues with progress on the card, epic progress, optional auto-done, services and websocket
  commands.
- **Photos and PDFs** on issues (upload, paste, drag and drop, camera snapshot via
  `homeboard.attach_camera_snapshot`), stored privately in `config/homeboard_files` and served through
  signed links; content-checked, size-limited, thumbnails.
- **Learning** (local, explainable, suggestions only, with an Insights tab and Forget buttons): smart defaults for
  new issues, recurring-chore suggestions from repeated tasks, workload and speed, sensor rhythms (a sensor that
  goes quiet becomes a health issue) and noisy-fault suggestions, and an opt-in home / away rhythm that improves
  the digest time.
- Options are now a menu of sections.
- Services `add_checklist_item`, `check_item`, `remove_checklist_item`, `attach_camera_snapshot`, `suggest`,
  `send_digest`, `forget_learning`; sensor `sensor.homeboard_suggestions`.

## [0.1.0] - 2026-11-22

First version.

### Added
- Projects with issue keys (`HOME-12`), issue types (task, bug, story, epic), priorities, labels,
  assignee / reporter from Home Assistant `person` entities, due dates, comments and an activity log.
- Configurable statuses (board columns) with categories (to do / in progress / done), soft WIP
  limits and a backlog flag.
- Sidebar panel **Board** (Summary, Board, Backlog, List) with touch-friendly drag and drop,
  quick filters, swimlanes and an issue dialog; plus three Lovelace cards (board, status, quick add),
  all registered automatically.
- Quick add: one line of text (`bug: gate squeaks @joachim !high #garden due friday`) from the
  panel, a card, Assist (native `todo` list), Siri / Shortcuts or the `homeboard.quick_add` service.
- Entities: a `todo` list and a `calendar` per project, sensors for open / overdue / due soon /
  unassigned / last activity, one count per status, one sensor per person, `has_overdue` binary sensor.
- Bus events (`homeboard_issue_created`, `_moved`, `_completed`, `_overdue`, ...) and services with
  responses and dedupe keys, so sensors can open issues without duplicates.
- Recurring chores (every N days / weeks / months / years).
- Home health: issues are created, updated and closed automatically for offline devices, low
  batteries, Home Assistant repairs, integration problems and (optionally) pending updates.
- Danish translation of the integration screens, services and entity names (`translations/da.json`).
- Optional push notifications for done / overdue / due soon / new high-priority auto issues.
