# Homeboard 0.4 — Habits: automation ideas in an inbox (design)

Owner's request (Danish, 2026-11-23): the integration should *scan behaviour and suggest automations*, with the
suggestions landing **in an inbox** (the owner's words: "i en indbakke"). The Insights page already is a list of
suggestions a person accepts or dismisses, so the inbox is that list, with a new kind of card: *automation idea*.

## 1. Principles

1. **Suggest only.** Nothing is created until an administrator presses *Create*. A created automation starts
   **switched off**; the owner switches it on in Home Assistant when happy. Creating can be undone.
2. **Opt-in, local, explainable.** New learning feature `habits`, **off by default** (it reads how devices are
   used). Everything is computed inside Home Assistant from the recorder history; nothing is sent anywhere (no AI
   is involved). Every idea shows its evidence ("on 17 of the last 21 weekdays, between 06:28 and 06:42").
3. **Narrow on purpose.** Only lights, switches, fans and covers (the thing that is switched) and motion /
   occupancy / door / window sensors (a trigger). Never persons, device trackers, media players, climate, and
   **never** `alarm_control_panel`, `siren`, `lock` or `valve` (same protected list as AI Fix). Entities excluded
   in the health options are excluded here too.
4. **Do not suggest what exists.** An idea is dropped when an automation already acts on that entity (or, for a
   follow-up, already uses both the sensor and the entity).
5. **Same safe writer as AI Fix.** Creating validates with Home Assistant's own schema, copies `automations.yaml`
   to `config/homeboard_backups/` first, refuses files that use `!secret` / `!include` tags, reloads, checks the
   new automation loads (rolls back if not), switches it off. Undo removes it again, but refuses if it was edited
   in the meantime.

## 2. What it looks for (up to 28 days of history, at least 7 days of data)

| Pattern | Idea | Rule of thumb |
|---------|------|---------------|
| **Routine** | "Turn on / off X at 06:35 on weekdays" | X changed to the same state on at least 5 days within a 30-minute window on at least 70 % of the days of its day group (every day, weekdays, weekends) |
| **Follow-up** | "When the hall motion sensor sees someone, turn on the hall light" | the sensor turned on at least 8 times on at least 5 days (repeats within 5 minutes count once), and X turned on within 60 s of it in at least 70 % of those |
| **Switch back** | "Turn the hall light off 4 minutes after the motion has stopped" | same sensor / X pair, X turned off 1-15 minutes after the sensor turned off in at least 70 % of the cases (median delay) |

Home Assistant's recorder keeps only 10 days of history unless `purge_keep_days` is raised (the owner's keeps
~11), so the window is whatever exists (at least 7 days); a longer `purge_keep_days` gives steadier ideas.
Cause is not in the history (a person, a button or an old automation may have done it), so ideas for entities
that any automation already touches are dropped, and the card says "assuming no automation did it".

## 3. Flow

nightly (04:00) and on demand (`homeboard/habits/scan`, service `homeboard.scan_habits`) a scan reads the recorder
(`recorder.history.get_significant_states`, in the recorder's executor), the miner (`habits.py`, pure Python)
turns it into candidates, the candidates are cached in the learning store; `Insights` lists the open ones as
suggestions of kind `automation` (with a YAML preview). *Create* (`homeboard/habits/create`) writes the automation
(switched off) and records it in `learning.habits.created` so it can be undone. Dismissed ideas stay dismissed
(the id has no time in it, so a shifting minute does not bring one back).

## 3b. Hardening after an independent review

Found by a read-only review and fixed with a test each: a Monday-to-Friday routine could pass as "every day" (now "every
day" needs both weekdays and weekends to qualify); entities that toggle many times a day (cycled by something else) and
targets that switch so often that a "follow-up" would happen by chance are skipped; the pair loops stop early and are
capped; creating takes one lock (two presses make one automation), re-checks every safety rule, **verifies the new
automation is off** and removes it again if it cannot be (and names it if even that fails); the safety rules live in one
place and also hide ideas stored before a rule changed; plugs and switches only get "off" ideas, fans and switches are
checked for risky words (whole words, so "clock" is not "lock": heater, oven, pump, valve, door, garage ...), roof windows
and awnings are never offered; the "covered" check understands `data.entity_id`, registry ids and device actions; "exists"
removes the idea from the inbox; undo works when the automation was deleted in Home Assistant first; a failed scan is
retried after the next start; automation ideas and `learned.habits` are for administrators only; old backups are pruned
(newest 50 kept).

## 4. Out of scope for 0.4

Scenes ("goodnight" clusters), climate set-points, anything that needs conditions on presence, asking the AI to
refine an idea, learning from which ideas were accepted.
