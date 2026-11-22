# Assist notes (Homeboard 0.2)

Code: `custom_components/homeboard/assist.py`, sentences `custom_components/homeboard/assist_sentences/{en,da}.yaml`,
tests `tests/test_assist.py`. Written against Home Assistant 2026.10 (`homeassistant/components/conversation/`,
`helpers/intent.py`).

## Route for the sentences: files, and why

Intent **handlers** have a stable API (`homeassistant.helpers.intent.async_register` / `async_remove`), so they are
registered whenever Homeboard is loaded, option or not. The **sentences** that trigger them are the problem. The default
agent builds the sentence set of a language in `DefaultAgent._load_intents` from exactly three sources:

1. the `home_assistant_intents` package (built in, cannot be extended),
2. `<config>/custom_sentences/<language>/**/*.yaml`,
3. `conversation: intents:` in `configuration.yaml`.

No integration-facing API adds sentences. The two programmatic routes that exist are internal and were rejected:

* `get_agent_manager(hass).update_config_intents()` is language independent (no per-language wording, no wildcard lists),
  replaces the user's own `conversation: intents:` and is overwritten by every `conversation.reload`.
* `get_agent_manager(hass).register_trigger()` (what automation sentence triggers use) is language independent, always
  wins over both built-in and custom intents, bypasses the intent pipeline (nothing for the debug view or tool use), and is internal
  with no public contract.

So the route is **custom sentence files**, as in `DESIGN-0.2.md`: when the option `assist_sentences` (default false) is on,
`custom_sentences/en/homeboard.yaml` and `custom_sentences/da/homeboard.yaml` are written from the shipped templates.

* Only files whose first line is `# Managed by Homeboard, do not edit` are ever replaced or removed. A `homeboard.yaml`
  that someone else wrote (or a symlink) is left alone with a warning. A language folder is removed again only if it ends up
  empty.
* After a change the sentences are reloaded with the `conversation.reload` service (no restart). If that call fails (it also
  re-reads `configuration.yaml`) it falls back to reloading `en`, `da` and the configured language one by one. Nothing is
  reloaded when nothing changed on disk, so calling setup twice is quiet.
* `en` and `da` also serve `en-GB` and `da-DK` (the agent maps a language to its variant folder). Tested.
* All names a file adds to Home Assistant's own language data (expansion rules, slot lists) start with `hb_`, because custom
  files are merged into the built-in ones. Wildcard lists must be declared at the top level of the file (hassil only reads
  wildcards there).
* Custom sentences beat built-in ones when both match, which is why no sentence is a bare `add {item} to {name}`: the
  native "add milk to the Home list" would be hijacked. Tested: it still reaches the todo entity (`source: todo`).

## What you need to wire

1. `__init__.py`, `async_setup_entry`, after `hass.data[DOMAIN] = manager`:
   `await async_setup_assist(hass, entry)`; in `async_unload_entry`, inside `if unload_ok:` :
   `await async_unload_assist(hass, entry)`. Both are idempotent and concurrency safe (one lock per hass).
   Optional: an `async_remove_entry(hass, entry)` that also calls `async_unload_assist`, for an entry that was not loaded
   when the user deleted it (otherwise its files stay behind).
2. Option **`assist_sentences`** (bool, default false) in the options flow and `strings.json` (the flow already uses
   `OptionsFlowWithReload`, so toggling it unloads and sets up again, which installs or removes the files).
   `assist.CONF_ASSIST_SENTENCES` holds the name; move it to `const.py` if you prefer and import it in `assist.py`.
   Suggested label: "Install Assist sentences". Suggested description: "Writes `custom_sentences/en/homeboard.yaml` and
   `custom_sentences/da/homeboard.yaml` in your configuration folder (first line `# Managed by Homeboard, do not edit`).
   Nothing else is written. The files are removed again when this is switched off or Homeboard is removed."
3. `requirements-dev.txt`: the real conversation component needs `hassil==3.12.1`, `home-assistant-intents==2026.10.6` and
   `gazetteer-matcher==1.1.0` (pins from the installed Home Assistant's `components/conversation/manifest.json`; `unicode-rbnf`
   comes with them). They were **not** in the venv. I installed the four packages into `.venv` with `uv pip install` so
   `tests/test_assist.py` runs; please add the three lines so CI and a fresh checkout get them too.
4. README Assist section, CHANGELOG, DESIGN-0.2 (it names five intents; there are six, `HomeboardPerson` is the sixth).

No change was needed in `data.py`, `const.py` or the manifest (conversation is not a dependency: handlers do not import it,
and the reload step is skipped when the `conversation.reload` service does not exist yet).

## Intents and example sentences

| Intent | English | Danish |
|--------|---------|--------|
| `HomeboardAdd` (`item`, `project?`) | "add fix the gate due friday to the board", "put bulbs on the kitchen board", "add oil to the HOME project", "add oil to project KIT" | "tilføj køb pærer frist fredag til tavlen", "tilføj olie til køkkentavlen", "læg sæbe på køkken tavlen", "tilføj tape til projektet HOME" |
| `HomeboardOverdue` | "what is overdue", "is anything overdue", "how many issues are overdue" | "hvad er forsinket", "hvilke opgaver er forsinkede", "er der noget forfaldent" |
| `HomeboardMine` | "what is on my list", "what am I working on", "what do I have to do" | "hvad står der på min liste", "hvad arbejder jeg på", "hvad er mine opgaver" |
| `HomeboardPerson` (`person`) | "what is Padmaja working on", "what's on Padmaja's list" | "hvad arbejder Padmaja på", "hvad står der på Padmajas liste" |
| `HomeboardDone` (`item`) | "mark HOME-12 as done", "HOME-12 is done", "mark the gate as done", "I finished the gate" | "marker HOME-12 som færdig", "hegnet er færdig", "jeg er færdig med hegnet" |
| `HomeboardStatus` | "how is the board doing", "board status", "what's on the board" | "hvordan går det med tavlen", "status på tavlen", "hvad står der på tavlen" |

Spoken answers (English / Danish), no trailing full stop, as Home Assistant's own:
"Added HOME-12: Fix the gate, due Friday" / "Tilføjede HOME-12: Køb pærer, frist fredag";
"3 issues are overdue: A, B and C, and 2 more" / "3 opgaver er forsinkede: A, B og C, og 2 mere";
"The board has 12 open issues, 2 overdue and 3 due soon. 1 smart home problem needs attention".
A language other than `en` / `da` cannot reach the handlers (no sentences) but would get English wording.

## Behaviour decisions

* **Speaker**: `intent_obj.context.user_id` -> `manager.person_for_user`. Used as `actor` (so the issue's reporter and the
  activity log) for add and done, and as the owner for "my list". Unknown speaker: "my list" says so politely and is an
  error response; the other intents do not need to know who is asking. Adding does **not** assign the issue to the speaker
  (type `@me` in the text for that).
* **Add** goes through `manager.quick_add(..., source="assist")`, so `due friday` / `frist fredag`, `#label`, `!high`,
  `@name`, `bug:` all work. The hassil matcher strips `:` and `!` from typed text; the handler restores the typed wording from
  `intent_obj.text_input` so `bug:` and `!high` survive when typed (voice never produces them). The first letter is
  capitalised unless the line starts with a token (`bug:`, `due ...`). Project: key or (prefix of) name, spoken or typed;
  unknown or unclear projects create nothing and say so.
* **Done** matches by key ("HOME-12", "home 12", "issue home 12"), otherwise by title among open issues in three tiers
  (equal, contains all spoken words, close spelling for transcription slips). Several matches: nothing is moved, it names up to
  three with their keys and asks for the number. An already finished issue says so (no event, no activity). The issue moves to
  the first `done` status of its own project.
* **Lists**: "mine" and "person" list open issues, in progress first, then by due date; overdue is oldest first; at most
  three titles, then "and N more". Person names are matched by name or entity id, unique prefix, possessive (`'s`, Danish `s`),
  or close spelling; "me / myself / mig" means the speaker.

## Known limits, not verified

* **Real voice hardware** (satellites, Whisper / cloud STT, TTS) was not tried; everything ran through
  `conversation.async_converse` and the `conversation.process` service in-process. Open questions: how a transcriber writes
  "HOME-12" (digits are handled, spelled-out numbers such as "twelve" / "tolv" are not), and Danish compounds
  ("køkkentavlen" and "køkken tavlen" both work in tests).
* **Voice satellites have no Home Assistant user**, so "what is on my list" can only answer in the Assist dialog, the app
  and `conversation.process` calls made by a user. A satellite-to-person mapping would be the follow-up (option).
* **Danish word order collision**: Home Assistant's own sentence "marker X på listen som færdig" (marker ... på ... som
  færdig) is claimed by `HomeboardDone` while the option is on, because a custom match wins. "marker X som færdig på listen"
  and "fuldfør X på listen" are unaffected.
* **LLM agents**: Home Assistant 2026.10 offers an integration's tools to LLM based assistants through an `llm.py` platform
  (`async_get_tools(hass, llm_context, api_id) -> LLMTools | None` returning `helpers.llm.IntentTool`s). The six handlers
  would fit (slot schemas are plain keys, so every slot is optional there); not added, not tested.
* The files install into the config folder of the running Home Assistant; a stale file can only be left behind if the integration
  folder is deleted while the option is on and HA is stopped (the first line says what wrote it).
