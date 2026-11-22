# Homeboard 0.2 — design draft (owner picked: push to assignee, photos + checklists, learning)

Status: **built in 0.2.0** (owner approved all four learning features; rhythm is off by default). Assist details and the route chosen for sentences: `docs/ASSIST_NOTES.md`.

## 1. Push to the person it is assigned to, and Assist sentences

**Per-person push.** Each Home Assistant `person` is mapped to the notify service of their phone.
Auto-detected from the person's `device_trackers` (a `mobile_app` tracker gives `notify.mobile_app_<device>`),
overridable per person in the options. Notified, per person and per switch (all default on except the digest):
assigned to you, someone commented on your issue, your issue is overdue / due soon, an issue you reported is
done, plus an optional **morning digest** (your open and overdue issues, at a time you choose; section 3
can later pick the time for you). Pushes carry the deep link (`/homeboard?issue=HOME-12`), a tag per issue
(so a newer push replaces the older), and never go to the person who made the change themselves.
The old "fixed list of notify services" stays for household-wide alerts.

**Assist.** English and Danish sentences, installed on request into `config/custom_sentences/<lang>/homeboard.yaml`
(option "Install Assist sentences"; removed again when switched off or the integration is removed; the
integration says exactly what it writes):
"add X to the board / to HOME", "what is overdue", "what is on my list", "what is Padmaja working on",
"mark HOME-12 as done", "how is the board doing". Handlers are real intents registered by the integration
(`HomeboardAdd`, `HomeboardOverdue`, `HomeboardMine`, `HomeboardStatus`, `HomeboardDone`) and answer in the
language of the request. The native "add X to the Home list" keeps working without any of this.

## 2. Checklists and photos

**Checklists (subtasks).** `checklist: [{id, text, done}]` on an issue; card shows `3/5`; dialog edits items;
all items done can optionally move the issue to the first Done status (project option). Services
`add_checklist_item`, `check_item`, `remove_checklist_item`; websocket `homeboard/checklist/*`; changes appear
in the activity log and in `homeboard_issue_updated`. Epics show a progress roll-up of their child issues.

**Photos and files.** Images (jpeg, png, webp, gif) and PDF up to 10 MB, stored in `config/homeboard_files/`
(not under `www`, so they are **not public**): served through an authenticated view
`/api/homeboard/files/<id>` with thumbnails generated on upload; upload with `POST /api/homeboard/upload`
(signed-in users only). Metadata on the issue (`attachments: [{id, name, mime, size, ts, author, source}]`),
removed together with the issue. Camera route: service `homeboard.attach_camera_snapshot` (`issue` or
`project` + `dedupe_key`, `camera` entity) stores a snapshot, so a health issue "Front door camera offline"
or an automation "person at the door" can carry a picture. The panel gets an attach button (file picker /
camera on phones), paste-an-image, and a gallery in the dialog.

## 3. Learning from tasks and everyday life (local, explainable, opt-in)

Principles: **statistics, not a black box**; everything stays in `.storage/homeboard`; nothing is sent anywhere;
every learned thing is shown on an **Insights** page with the evidence ("based on 9 similar issues"); the
system only **suggests** (one tap to accept), except notification timing which has its own switch;
**Forget everything** wipes it; each feature below has its own option.

| Feature | What it learns | What you get | Data it uses |
|---------|----------------|--------------|--------------|
| **A. Smart defaults** | which person, labels, priority and typical lead time go with similar titles (token overlap over past issues) | chips under the quick-add bar ("Padmaja, #bills, due in 3 days"), one tap to apply | issues only |
| **B. Pattern finder** | the same task being created again and again with a regular gap | "You create 'Order bin bags' about every 6 weeks. Make it a recurring chore?" | issues only |
| **C. Workload and speed** | how long things take per type / label / person, who finishes what | "usually takes 5 days, due in 2" hint, balanced assignee suggestion, weekly summary | issues only |
| **D. Everyday rhythm** | when each person is usually home and active (hour-of-week presence counts from `person` state changes, aggregated, no locations or coordinates) | pushes and the digest at times you are home, nothing while away, "best day for this chore" suggestion | person home / away state |
| **E. Health learning** | each sensor's normal reporting interval, flapping devices, faults you always close | per-sensor "silent for longer than normal" detector, suggestions to exclude or lengthen the threshold for noisy devices | state history of sensors |

Implementation: `insights.py` (pure Python, unit-tested: similarity, interval / histogram maths, pattern
detection), aggregates in the store under `learning`, updated incrementally from the data manager's events and a
nightly job; websocket `homeboard/insights/get|accept|dismiss|forget`; service `homeboard.suggest`
(returns the suggestion for a text); sensor `sensor.homeboard_suggestions` (count). Dismissed suggestions are
remembered so they do not come back.

## 4. Order of work

1. Push to assignee + digest, Assist intents and sentences (backend + options).
2. Checklists, attachments, camera snapshot (backend + upload view).
3. Insights engine A, B, C, then E, then D (D last, it is the most personal).
4. Frontend for all of it (subagent, same contract approach), docs, tests, release 0.2.0.
