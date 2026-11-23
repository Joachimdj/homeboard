# Homeboard 0.3 — AI Fix (design)

Owner's request (Danish, 2026-11-23): *"tilføj en løsning med AI som kan rette automationer og bugs baseret
på smarthome-fejl der er oprettet i boardet"*. The health scanner already puts smart-home faults on the board
(project FIX). AI Fix lets a language model **diagnose such an issue and propose a concrete fix**, which the
owner reviews and applies with one click (and can undo).

## 1. Principles (these decide every detail below)

1. **The AI only proposes. A person applies.** Nothing is ever changed without an admin pressing *Apply*.
   There is deliberately no service, Assist sentence or automation that applies a proposal.
2. **Closed set of actions.** A model answer is parsed into a few fix kinds (section 3). Anything else is
   ignored. Targets (automation, config entry) must come from the list Homeboard sent, so a made-up or
   injected target is rejected.
3. **Always reversible.** Before a write, the whole `automations.yaml` is copied to
   `config/homeboard_backups/`. *Undo* restores that one automation. After a write the result is verified
   (reload, the automation must be available again); if not, it is rolled back automatically.
4. **Protected things stay hands-off.** Automations that touch `alarm_control_panel`, `siren`, `lock`,
   `valve` or Alarmo can be *analysed* (the model explains and shows corrected YAML) but not *applied* by
   Homeboard, unless the owner switches on "allow protected" in the options (default off). The check is
   deliberately wide: every string and dict key is searched case-insensitively, devices / areas / floors /
   labels / groups that contain such an entity count, and a proposal may not *introduce* anything whose effect
   cannot be read from the config (templated service or target, `service_template`, `entity_id: all`, calls to
   `script`, `scene`, `homeassistant` or `automation`). An automation whose config cannot be read is not proven
   harmless and counts as protected. The check runs again when Apply is pressed.
5. **Explainable and private.** The exact text sent to the AI can be shown before it is sent. Secrets
   (`secrets.yaml` values, keys named `password`, `token`, `api_key`, `webhook_id` ...) are replaced by
   placeholders and put back only at apply time. Off by default; the owner picks which AI Task entity.
6. **No new keys, no new accounts.** The call goes through Home Assistant's own **AI Task** integration
   (`ai_task.generate_data`), so whatever AI the owner already set up (Anthropic, OpenAI, Google, Ollama,
   ...) is used and Homeboard never sees an API key. The owner's HA has `ai_task.claude_ai_task`.
7. **Cheap by default.** Manual button (or the `homeboard.ai_analyze` service), one analysis at a time, a
   daily limit (default 20), bounded prompt size.

## 2. Flow

```
issue in FIX  -->  [Analyse with AI]  -->  context builder (read-only facts, redacted)
                                    -->  ai_task.generate_data  -->  JSON answer
                                    -->  parse + validate  -->  record on the issue (diagnosis + proposals)
owner reviews diff  -->  [Apply]  -->  re-validate, backup, write, reload, verify  -->  comment + activity
                          [Undo]  -->  restore the automation from the backup
```

Analysis runs in the background (can take a minute); the board shows a spinner and updates by itself.
When a fix works, the health scanner closes the underlying issue by itself on its next scans (existing
"resolved automatically" behaviour); Homeboard does not close it.

## 3. Fix kinds

| kind | what Apply does | reversible |
|------|-----------------|------------|
| `automation_edit` | replaces one UI automation (`automations.yaml`) with a new config, after HA's own validation | yes (Undo) |
| `automation_disable` | `automation.turn_off` on one automation | yes (Undo = turn on) |
| `reload_integration` | reloads one config entry (integration that failed to set up) | n/a |
| `manual_steps` | adds the steps to the issue's checklist (replace battery, re-pair ...) | n/a |

Not editable by Homeboard (shown as "copy this YAML"): YAML-mode automations, anything protected, proposals
that reference entities that do not exist, a stale proposal (the automation changed after the analysis).

## 4. What the model sees (context builder)

Built from the issue's `dedupe_key` (`health:repair:automation:...`, `health:offline:...`,
`health:integration:...`, `health:automation:...`) and from entity ids written in the issue text:

- the issue (title, description, last comments, labels), Home Assistant version and language
- for an HA repair: its translated title and placeholders (the validation error text)
- for a device fault: device, its entities with state and last change, the config entry state
- every **automation that uses the faulty or missing entities**, as YAML, with its last trace error
- for each missing entity: up to 8 existing **candidate replacements** (same domain, similar id/name, with state
  and area), so renamed entities can be mapped
- for `service_not_found`: the services that exist in that domain

It never sees: tokens, `secrets.yaml` values, other automations, camera images, person locations, history.
Limit: 24 000 characters, cut with a note.

## 5. Model answer (JSON, one object)

```json
{"diagnosis": "plain text, 1-4 sentences", "confidence": "low|medium|high",
 "proposals": [{"kind": "automation_edit", "title": "...", "explanation": "...", "risk": "low|medium|high",
                "target": "automation.xyz", "config": {"alias": "...", "triggers": [], "actions": []}}]}
```

At most 3 proposals. Unparsable or invalid answers get one automatic retry with the error text. Every
`automation_edit` is validated with HA's own automation schema, must keep its `id`, must not introduce
entities that do not exist, and is shown as a unified diff against the current YAML.

## 5b. Hardening after an independent review

Found by a read-only review of the first version and fixed with a test each: protected check bypasses (case,
templates, device / area / label / group targets, blueprints); two simultaneous Apply calls could overwrite the
backup (now one lock per issue, unique backup names, the fingerprint is compared under the file lock); Undo could
overwrite a person's later edit (now refused); proposal ids could collide after a re-analysis; validation errors
could quote a secret (all stored / shown error text is masked); numeric, short and list secrets and header-like key
names (`X-Api-Key`) are masked; masking happens before clipping; a placeholder may only stay under a key where the
masked config had one, and every automation numbers its placeholders from its own block; a proposal whose diff
would be clipped is blocked (the admin must see the whole change); an automation whose YAML does not fit in the
text is not offered as a target; `dedupe_key` is only trusted on issues made by the scanner; `</context>` inside
text cannot end the data block; `homeboard.ai_analyze` is administrator-only for people; the analysis runs as a
background task; a record with an applied fix is never evicted. Secrets shorter than 4 characters are not masked.

## 6. Detector for broken automations (new, opt-in)

HA already raises repairs for automations that fail validation or call a missing service (the scanner picks
those up). It does **not** notice automations that silently point at deleted or renamed entities (in the
owner's HA a first read-only look found many). New detector `automations` (option `health_automations`,
default off, enabled automations only): one issue `health:automation:<automation entity id>` per automation
that references entities which no longer exist. Use `homeboard.scan_health` with `dry_run` first.

## 7. Options

`ai_fix_enabled` (off), `ai_fix_entity` (AI Task entity; empty = the preferred one, else the only one),
`ai_fix_allow_protected` (off), `ai_fix_daily_limit` (20), `health_automations` (off).

## 8. Out of scope for 0.3

Scripts and scenes, editing YAML-mode files, applying anything automatically, learning which fixes the
owner accepted (later: feed accepted/rejected proposals back as examples), voice (Assist) triggers.
