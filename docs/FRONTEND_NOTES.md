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

## Version 0.2 (PROTOCOL section 10): assumptions and choices

Checklists
- Items and counters: the card chip uses `checklist_done` / `checklist_total`, epics use `epic_done` /
  `epic_total`, the dialog edits the `checklist` of `issue/get`. Writes are shown at once (the dialog's copy
  and the card counters) and a failed write refetches the detail.
- The UI stops at 100 items and 200 characters per item (the limits in `const.py`); a pasted multi-line text
  becomes one item per line. `checklist/reorder` always sends the complete id list.
- `checklist_autodone` stays a backend matter: when it moves the issue to Done the normal push shows it.

Attachments
- The whole section is hidden unless `settings.attachments.enabled === true`, so a 0.1 backend (no such key)
  shows nothing. It is also hidden in the "New issue" form (there is no issue id yet). The paperclip chip on
  cards shows whenever `attachment_count > 0`, regardless of the setting.
- Upload goes through `hass.fetchWithAuth("/api/homeboard/upload", { method: "POST", body: FormData })` with the
  fields `issue_id` and `file`. `fetch` has no upload progress, so an upload shows a spinner tile instead of a
  percentage. The type (jpeg / png / webp / gif / pdf) and size (`settings.attachments.max_mb`) are checked in the
  browser first; 413 / 415 / 404 from the server get the same wording. The 413 toast contains the limit in MB and the
  literal name `settings.attachments.max_mb`, as asked.
- PDFs are assumed to have no `thumb_url` (a file icon is shown); they open in a new tab from `url`.
- Signed URLs: a failing `<img>` refetches `issue/get` (at most once every 10 seconds). The mock harness can
  revoke its URLs with the "Expire file URLs" button to prove that path.
- Paste and drop listen on `window` while the issue dialog is the top-most dialog and attachments are enabled.
  A pasted image without a name is called `pasted-image-<time>.<ext>`.
- Camera snapshot lists `camera.*` from `hass.states` and calls `homeboard/attachment/snapshot`.

Smart defaults
- `quick_add/preview` returns the parsed fields plus `suggestion`; the frontend splits it off. The chips show
  below the parsed chips, dimmed and dashed, with a "?" button for the evidence and the `similar` issues as links
  (links only for issues that are on the board). "Use suggestions" is remembered in `localStorage`
  (`homeboard.useSuggestions`, default on) and decides whether `quick_add` gets `suggest: true`. The row is shown
  when `settings.learning.defaults` is true.
- The new-issue "Suggest" button (same condition) calls `homeboard/suggest` and fills only empty fields:
  assignee, labels, priority (only if the user did not change it), and the due date = today + `due_in_days`
  (local date).

Insights
- The tab exists only while some `settings.learning` flag is true; the badge is `settings.insights_open`.
  `homeboard/insights/get` is fetched when the tab opens and again whenever `insights_open` changes. Reading is
  assumed to be open to every signed-in user; only `insights/forget` is admin (buttons hidden for non-admins).
- `accept` of a `recurring` suggestion shows a toast linking to the project settings > Recurring tab
  (`proposal.project_id` must be a project id); `health_ignore` and `digest_time` just confirm.
- Evidence text is built for `recurring` (`count`, `interval_days`), `health_ignore` (`reopened`) and
  `digest_time` (`samples`); anything else falls back to "key: value" pairs.
- Added deep link `?tab=insights` (used by the status card's suggestions tile); it is consumed like `?project`.
- `learned.patterns` does not exist in PROTOCOL 10.5, so the "Pattern finder" card only states what it uses.
- The rhythm grid is read as 7 rows (Monday first) of 24 values in 0..1; missing cells count as 0.

Open questions for the backend
1. What `field` name will the activity log use for attachment changes? The frontend knows `checklist` (as in
   `checklist.py`) and shows unknown names verbatim.
2. Does the upload response carry `url` and `thumb_url` (signed) like the detail does? The frontend refetches the
   detail after every upload anyway.
3. `suggestion.similar[].status` is shown as the status name.
