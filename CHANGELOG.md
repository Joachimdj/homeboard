# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/). Versions follow
[Semantic Versioning](https://semver.org/); while the project is 0.x only the patch number is bumped
for small changes.

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
