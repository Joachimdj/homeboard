# Frontend notes and open protocol questions

Written by the frontend work (static/, tests/js, tests/browser). Nothing in `PROTOCOL.md` or
`DESIGN.md` was changed. Each item is an assumption the frontend makes; please confirm or correct it
on the backend side (or tell the frontend to adapt).

## Assumptions about the backend

1. **`homeboard/status/update` with `wip: null` clears the WIP limit.** The settings dialog sends
   `wip: null` when the field is emptied. `PROTOCOL.md` only says `wip?`.
2. **`homeboard/project/update` with `labels` replaces the whole vocabulary** (the Labels tab sends the
   complete new list, lower-case, sorted).
3. **`quick_add` / `quick_add/preview` return `project` as the project key** (as `quickadd.py` does) and
   may carry `unresolved: ["@nobody", "!x"]`. The frontend shows unresolved tokens as dashed chips; this
   field is not in `PROTOCOL.md` section 3 (the frontend works without it). The frontend also accepts a
   project id in `parsed.project`.
4. **Activity entries**: `moved` carries status *names* in `from` / `to`; `assigned` carries person entity
   ids (or `null`); other `updated` entries carry `field`, `from`, `to`. Unknown values are shown as text.
5. **`issue/update` with `archived: true`** removes the issue from the next pushed payload (the payload
   leaves archived issues out). The frontend removes it optimistically.
6. **`issue/move` with `before` = an id in another lane**: with swimlanes the drop target is the card in the
   *visible* cell, so `before` can be an issue that is not adjacent in the real column. The backend only
   has to place the issue in front of it. `before: null` is sent explicitly for "end of the column".
7. **Wire name of the issue type is `issue_type`** (`issue/create`, `issue/update`, `recurring/create`,
   `recurring/update`), as in the corrected section 5. `store.call` puts the command name last, so a stray
   `type` field can never overwrite it.
8. **`recurring/create` takes `project_id`** plus the recurring fields; `status: null` means "first
   non-backlog todo status".
9. **Stats**: counts (open / overdue / due soon / unassigned / per status / per person) are derived from the
   pushed issues so that a drag shows up immediately; `done_7d` and `last_activity` are taken from
   `payload.stats` (archived issues are not in the list). `stats.total.health_open` is used for the Home
   health tile; high priority and `security` counts are derived from the issues (`source === "health"`).
10. **Due datetimes** typed in the issue dialog are sent with the *browser's* UTC offset
    (`2026-11-30T18:00:00+01:00`), not Home Assistant's time zone. Date-only values are sent as `YYYY-MM-DD`.

## Behaviour choices worth knowing

- **Recurring chores are open to every user** (section 5 permissions), so non-admins get a repeat icon in
  the panel header instead of the cog. It opens the settings dialog with only the Recurring tab. Admins
  get General / Statuses / Labels / Recurring.
- **Panel URL**: the cards and "Copy link" assume the panel is registered at `/homeboard` (section 9).
  The status card links to `/homeboard?project=KEY`; the summary tab's richer click-through (overdue,
  due soon, unassigned, per person, home health) lives inside the panel and uses its filters, which have
  no URL form.
- **Deep links** `?issue=KEY`, `?project=KEY` are consumed once (removed from the URL after use);
  `?kiosk` stays. The fullscreen button in the header toggles the same mode.
- **Auto issues** (`source: "health"`) get an "Auto" chip and a hint in the dialog; the "Auto-generated"
  quick filter shows when `settings.health_enabled` is true or at least one auto issue exists in the
  project. The `auto` label is hidden on cards because the chip says the same.
- **`static/package.json`** (`{"type": "module"}`) exists only so `node --test` can import the modules
  as ES modules; `tests/package.json` does the same for the tests. Both are harmless to ship.
- **Browser dependencies**: `ha-icon` and `ha-card` only, plus constructable stylesheets,
  `color-mix()` and container queries (all in every current Chrome / Safari / Firefox and in the HA
  companion apps).
- **Speech recognition** (mic button) appears only when `SpeechRecognition` / `webkitSpeechRecognition`
  exists; the language comes from `hass.locale.language` mapped to a region (`da` -> `da-DK`).
