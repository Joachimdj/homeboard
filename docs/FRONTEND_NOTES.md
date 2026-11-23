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

## 0.3 AI Fix (PROTOCOL section 11): assumptions and choices

Files: `static/ai-fix.js` (pure logic), `ai-fix-view.js` (vnode builders, no state), `ai-fix-section.js` (state and
calls, used by `issue-dialog.js`), the `aiChip` in `components.js`, `actions.ai*`, CSS in `styles.js`. Harness:
`tests/browser/mock-ai.js`.

- **Who sees what.** The dialog section needs `settings.ai_fix.enabled === true`, `is_admin` and an existing issue; it is shown
  for every issue, not only `source: "health"` (the contract does not restrict `ai/analyze`; filter on `issue.source` in
  `AiFixSection.enabled` if that is wanted). Cards and rows show the chip from `issue.ai` alone, so non-admins see nothing.
- **When `ai/get` is fetched.** On open, when the dialog moves to another issue, and whenever `issue.ai.rev` or
  `settings.ai_fix.entity` changes in the push; also after any failed AI call (to see the truth again). There is no polling.
  Consequence: `ready` / `reason` / `limit` are only as fresh as the last fetch. If the daily limit is used up by an analysis of
  another issue while a dialog stays open, the dialog learns it from the `ai_limit` error. If that should show at once, the
  backend would have to bump `rev` of every record (or the frontend refetch on focus).
- **While `state === "running"`** only the spinner is shown, any proposals of an older record are hidden. This assumes a new
  analysis replaces the record (and with it the chance to undo an earlier apply).
- **Buttons per proposal** (`proposalActions`): Apply only for the four known kinds and not when `blocked`; Dismiss for every
  `proposed` one (also blocked); Undo only when `undoable === true`; Copy YAML when `new_yaml` is set and the status is
  `proposed` or `failed`. A dismissed or undone proposal drops to title, explanation and a state line.
- **Apply is two-step** (confirm row, Escape cancels it) except `manual_steps` ("Add to checklist"): that is one press, because
  the confirm text (backup, undo) would not be true for it. The confirm text differs per kind (edit, disable, reload).
- **Only one AI call at a time**: while analyse, preview, apply, undo or dismiss runs, all of those buttons are disabled; the
  pressed one shows a spinner (analyse and preview can take up to a minute). After `ai/analyze` returns, the section shows
  "running" at once and the push with the new `rev` brings the real record.
- **Preview** is dropped when the note is edited (it would no longer be what is sent) and when an analysis starts. The note
  stays in the box after sending; the record's `note` is shown as "Your note: ...".
- **Reasons**: `disabled`, `no_entity`, `choose_entity`, `unsupported`, `limit` have their own text; any other value, and
  `ready: false` with `reason: null` while nothing is running, gives "AI Fix is not ready." (never an empty line).
- **Errors**: the codes `ai_disabled`, `ai_unavailable`, `ai_limit`, `ai_busy`, `not_applied` get translated texts, anything else
  (`blocked`, `not_found`, ...) shows the server's message. Shown in the section and as an error toast.
- **After apply or undo** the dialog refetches `issue/get` (comment, activity, and the checklist items of `manual_steps`).
  Adding the steps to the checklist is assumed to be done by the backend as part of `ai/apply`.
- **Copy YAML** uses `navigator.clipboard` and falls back to `document.execCommand("copy")`, because the clipboard API does not
  exist on a Home Assistant served over plain http (the common case on a LAN address).
- **Untrusted text**: titles, explanations, warnings, steps, diff, error, prompt, entity name are only ever child strings
  (text nodes); risk, kind, status and confidence are mapped through fixed lists before they reach a class name or a text key.
  `tests/js/ai-fix-view.test.js` renders a payload full of `<img onerror>` through the real `patch()` and a small fake DOM and
  checks that no element, event attribute or attribute value carries it, and that the AI modules never use `innerHTML`.
- **Harness**: admin user = the existing "Admin" box. Seeded records: FIX-2 ready (edit with diff, manual steps, blocked
  protected one), FIX-6 ready (reload, plus an applied and undoable disable), FIX-1 failed, FIX-3 running, FIX-4 / FIX-5 none.
  New controls: AI Fix on/off, a state select (limit, no entity, choose entity, unsupported, unknown reason), "calls fail", "slow
  preview / analyse"; query params `aireason=limit` and `aislow`. `ai/analyze` answers after 1.5 s (`backend.ai.delay`).

Open questions for the backend
1. Does `rev` change when only `ready` / `reason` / `limit` change (see above)?
2. Does a new analysis keep earlier applied proposals so that Undo stays possible?
3. Can `record.proposals` be non-empty while `state` is `failed`? (They would be listed below the error.)
4. Is `entity_name` always set when `entity` is? (Falls back to the entity id, then to "your AI Task entity".)

## 0.4 Habits (PROTOCOL section 12): assumptions and choices

Files: `static/habits.js` (pure logic), `habits-view.js` (vnode builders, no state), `habits-section.js` (state and calls, owned
by `InsightsController.habits`), `clipboard.js` (the copy helper that used to be private to `ai-fix-section.js`, now shared),
`actions.habits*`, CSS in `styles.js` (panel part), the `habits` entry in `insights.js` / `insights-view.js`. Harness:
`tests/browser/mock-habits.js`. Tests: `tests/js/habits.test.js`, `habits-view.test.js`.

- **Where it shows.** An "Inbox: automation ideas" section on top of the Insights tab, only when `insights/get` has
  `features.habits`. `true` = inbox; `false` = the calm explanation card (shown to everyone, it has no button); missing (a 0.3
  backend) = nothing at all. The old "Suggestions" section lists only the other kinds, with its own count, as before.
- **`habits` is a learning feature for the tab.** `learningEnabled` now also looks at `settings.learning.habits`, so the Insights
  tab stays when habits is the only feature on. `FEATURES` is still the 0.2 list (a test pins it); `ALL_FEATURES` adds `habits`
  and `LEARNED_FEATURES` gets a `habits` card (label, "Uses:" text, a note, Forget with its own confirm text).
- **Phone rules** are in the existing `@container insights (max-width: 520px)` block, not in the `@media (max-width: 720px)`
  block: that block is in `overlayCss` (dialogs) and does not reach the panel's shadow root. 44px targets, buttons share the row,
  the YAML scrolls inside its own box (checked: the page never gets a horizontal scrollbar at 375px).
- **Evidence line.** Built from whatever numbers exist, in the same words for every pattern: `days`/`of` ("On 17 of 21 days"),
  `share` as percent (clamped 0..1), `window` ("between 06:28 and 06:42"), `delay_minutes` ("about 4 min after the sensor turned
  off"), else `samples`. Nothing assumes 28 days. For `follow_up` and `switch_back` the contract does not say what `days` / `of`
  count (DESIGN-0.4 talks about cases); they are read as days. The pattern name only picks the icon and a chip (Routine /
  Follow-up / Switch back); an unknown pattern gets the generic icon and the chip "Idea".
- **YAML** is in a native `<details>` (collapsed, keyboard friendly, open state survives re-renders) with a `<pre>` and a
  Copy YAML button (clipboard API, `execCommand` fallback as in AI Fix).
- **Create is two-step** (confirm row, Confirm focused, Escape cancels and focus goes back to Create). On success: toast
  "Created, switched off: <alias>" (alias from `created.alias`, else `proposal.alias`) and a refetch of `insights/get`, which
  removes the idea and adds the record. The badge follows `settings.insights_open` by itself.
- **One call at a time.** While Create, Undo, Dismiss or a scan runs every one of those buttons is disabled (two writes to
  `automations.yaml` must not overlap, and a scan replaces the ideas Create refers to).
- **Errors** (inline on the card or row, and as an error toast): fixed friendly title per code (`exists`, `blocked`,
  `not_editable`, `create_failed`, `habits_disabled`, `not_found`, `backup_missing`), then the server's message; unknown codes get
  "That did not work" plus the message; `unauthorized` uses the existing text. `stale` shows only the fixed sentence from the
  brief. After any failed call the inbox is refetched; the contract does not say whether `exists` / `blocked` remove the idea,
  so the card stays until `insights/get` says otherwise.
- **Dismiss** is the existing `insights/dismiss` (same toast "Suggestion dismissed. It will not come back."); available to
  non-admins as before. `insights/accept` is never called for ideas.
- **Created list**: newest first by `ts` (the backend order is the tie-break), at most 20. `created` shows the alias, "Created
  <time>", "Open in Home Assistant" and Undo (two-step: "Remove this automation again?"); `undone` is a muted line (the record
  has no undo time, so only the state is shown); an unknown `state` shows no buttons at all. Non-admins see the list without
  link and Undo. Undo calls `habits/undo` with `created_id`.
- **Link to Home Assistant.** `edit_url` is only used when it matches `/config/automation/edit/<id>`; otherwise the path is built
  from `auto_id`; otherwise there is no link. A plain click does `history.pushState` + `location-changed` (the way the cards
  navigate; a real `window.location` assignment would reload the whole Home Assistant), a ctrl / cmd / middle click falls through to
  the `href` and opens a new tab.
- **Scan**: `habits/scan` answers with `error` as a result field (`no_recorder`, `no_history`, `failed`; any other value is shown
  as "The scan failed."). The text stays until the next scan; without a result from this session, `learned.habits.error` is shown
  under the status line. `no_history` says "Not enough history yet: I need at least 7 days of history" (`MIN_HISTORY_DAYS`).
  `learned.habits.days` is shown as given ("28 days of history", "9 days of history").
- **Reading is open to everyone**: `learned.habits` (with `created`) is assumed to be in `insights/get` for non-admins too.
- **Untrusted text**: title, detail, YAML, alias, error messages and ids are only ever text nodes (an id is also set as an inert
  `data-*` attribute with `setAttribute`); pattern, state and error code are mapped through fixed lists before they reach a class
  name or a text key. `habits-view.test.js` renders `<img onerror>` in all of them through the real `patch()` and a fake DOM, and
  `habits.js`, `habits-view.js`, `habits-section.js` and `clipboard.js` are guarded against `innerHTML` and friends.
- **Existing code touched**: `ai-fix-section.js` lost its private `copyText` (now `clipboard.js`, identical code);
  `insights.js`, `insights-view.js`, `insights-controller.js` (the `habits` section, `refresh()`, the forget text), `actions.js`.
- **Harness**: `new MockBackend({ habits: true })` switches the feature on and seeds three ideas (routine with window, follow-up,
  switch back with delay), a `created` and an `undone` record and `learned.habits` (120 entities, 28 days). Without the option
  the mock is a 0.3 backend (no `features.habits`), which keeps the older tests unchanged. `index.html` passes it, makes create
  1 s, undo 0.6 s and scan 1.5 s slow, adds a "habits" learning checkbox (`?habits=off` presets it) and a "Habits" select that
  makes create / undo fail with a code (`?habitsfail=stale`) or the scan answer with `no_recorder` / `no_history` / `failed`.
  Each scan finds one more idea (the second one has a pattern the UI does not know), then "Nothing new". Admin box = non-admin view.

Open questions for the backend
1. Does `habits/create` return `created.alias`? (Used in the toast; falls back to the idea's own alias.)
2. After `exists` or `blocked`, does the idea leave `insights/get`? (The frontend keeps the card and the error until a refetch says so.)
3. Is `learned.habits` (including `created`) part of `insights/get` for non-admins?
4. What do `days` / `of` count for `follow_up` and `switch_back`? (Read as days.)
5. `insights/get` is refetched when `settings.insights_open` changes; switching `habits` on or off with no open ideas does not change
   that number, so an open Insights tab shows the old state until it is reopened (true for every learning feature, not new).
