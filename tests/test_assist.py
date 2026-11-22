"""Assist: the intent handlers, the sentence files, and the real conversation pipeline.

Everything runs in-process against Home Assistant's own default conversation agent. The config
directory is a private temporary one, so ``custom_sentences`` never touches anything shared.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from homeassistant.components import conversation
from homeassistant.core import Context, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.homeboard.assist import (
    HANDLERS,
    MARKER,
    SHIPPED_DIR,
    _enumerate,
    _find_person,
    _issues_by_title,
    _original_item,
    _spoken_due,
    async_setup_assist,
    async_unload_assist,
    sync_sentence_files,
)
from custom_components.homeboard.const import DOMAIN, EVENT_ISSUE_COMPLETED

INTENTS = {handler.intent_type for handler in HANDLERS}
MONDAY = "2026-11-23 10:00:00+01:00"


def entry_with(**options) -> MockConfigEntry:
    """A config entry that is only used to read the options (it is never added to hass)."""
    return MockConfigEntry(domain=DOMAIN, options=options)


def registered(hass) -> set[str]:
    """Return the Homeboard intent types that are registered right now."""
    return {h.intent_type for h in intent.async_get(hass) if h.intent_type.startswith("Homeboard")}


@pytest.fixture(autouse=True)
def config_dir(hass, tmp_path: Path) -> Path:
    """Use a private config directory (the default one is shared by every test)."""
    hass.config.config_dir = str(tmp_path)
    return tmp_path


@pytest.fixture
def reloads(hass) -> list[ServiceCall]:
    """Stand in for ``conversation.reload`` and record every call."""
    calls: list[ServiceCall] = []

    async def handler(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("conversation", "reload", handler)
    return calls


@pytest.fixture
async def voice(hass, manager):
    """Homeboard plus the real conversation component, with the sentence files installed."""
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    await hass.async_block_till_done()
    await async_setup_assist(hass, entry_with(assist_sentences=True))
    return manager


async def ask(hass, text: str, language: str = "en", user: str | None = "user-0"):
    """Say ``text`` to the default agent as the Home Assistant user ``user``."""
    result = await conversation.async_converse(hass, text, None, Context(user_id=user), language)
    return result.response


def speech(response) -> str:
    """Return the spoken text of a response."""
    return response.speech["plain"]["speech"]


def add(manager, summary: str, **fields):
    """Create an issue in HOME."""
    return manager.create_issue("HOME", summary, **fields)[0]


# ------------------------------------------------------------------------------- add (English)


async def test_add_to_the_board(hass, voice, freezer):
    freezer.move_to(MONDAY)
    response = await ask(hass, "add fix the gate due friday to the board")
    assert speech(response) == "Added HOME-1: Fix the gate, due Friday"
    assert response.response_type is intent.IntentResponseType.ACTION_DONE
    assert [t.name for t in response.success_results] == ["HOME-1"]
    issue = voice.resolve_issue("HOME-1")
    assert issue["summary"] == "Fix the gate"
    assert issue["due"] == "2026-11-27"
    assert issue["source"] == "assist"
    assert issue["reporter"] == "person.joachim"


async def test_add_reads_the_speaker_from_the_context(hass, voice):
    assert speech(await ask(hass, "add oil to the board", user="user-1")) == "Added HOME-1: Oil"
    assert voice.resolve_issue("HOME-1")["reporter"] == "person.padmaja"
    response = await ask(hass, "put cat food on the board", user=None)
    assert speech(response) == "Added HOME-2: Cat food"
    assert voice.resolve_issue("HOME-2")["reporter"] is None


async def test_add_speaks_the_due_date(hass, voice, freezer):
    freezer.move_to(MONDAY)
    assert speech(await ask(hass, "add bins due tomorrow to the board")).endswith("due tomorrow")
    expected = "due 24 December"
    assert speech(await ask(hass, "add rent due 2026-12-24 to the board")).endswith(expected)
    assert speech(await ask(hass, "add tax due 1/12 18:30 to the board")).endswith(
        "due 1 December at 18:30"
    )
    assert speech(await ask(hass, "add post due friday 18:30 to the board")).endswith(
        "due Friday at 18:30"
    )


async def test_typed_quick_add_tokens_survive(hass, voice):
    """The matcher drops ``:`` and ``!`` from the text; the typed wording is restored."""
    await ask(hass, "add bug: gate squeaks !high #garden @padmaja due 2026-12-24 to the board")
    issue = voice.resolve_issue("HOME-1")
    assert issue["type"] == "bug"
    assert issue["summary"] == "gate squeaks"
    assert issue["priority"] == "high"
    assert issue["labels"] == ["garden"]
    assert issue["assignee"] == "person.padmaja"
    assert issue["due"] == "2026-12-24"


async def test_add_to_a_named_project(hass, voice):
    voice.create_project(key="KIT", name="Kitchen")
    voice.create_project(key="GDN", name="Garden")
    voice.create_project(key="GRG", name="Garage")
    assert speech(await ask(hass, "add buy bulbs to the kitchen board")) == "Added KIT-1: Buy bulbs"
    assert speech(await ask(hass, "add oil to project KIT")) == "Added KIT-2: Oil"
    assert speech(await ask(hass, "add soap to the HOME project")) == "Added HOME-1: Soap"
    assert speech(await ask(hass, "add tape to the home board")) == "Added HOME-2: Tape"
    assert speech(await ask(hass, "put string on the garden board")) == "Added GDN-1: String"


async def test_add_to_an_unknown_or_unclear_project_creates_nothing(hass, voice):
    voice.create_project(key="GDN", name="Garden")
    voice.create_project(key="GRG", name="Garage")
    response = await ask(hass, "add rope to the shed board")
    assert speech(response) == "I don't know a board called shed"
    assert response.response_type is intent.IntentResponseType.ERROR
    response = await ask(hass, "add rope to the gar board")
    assert speech(response) == "Which board do you mean: Garden and Garage?"
    assert voice.issues == {}


async def test_native_todo_sentence_is_untouched(hass, voice):
    """ "Add X to the Home list" still goes to the todo entity, not to the Homeboard intent."""
    assert speech(await ask(hass, "add milk to the Home list")) == "Added milk"
    assert voice.resolve_issue("HOME-1")["source"] == "todo"
    assert speech(await ask(hass, "tilføj mælk til Home listen", "da")) == "Mælk lagt til"
    assert voice.resolve_issue("HOME-2")["source"] == "todo"


async def test_add_that_leaves_no_title_says_so(hass, voice):
    response = await ask(hass, "add due friday to the board")
    assert speech(response) == "Sorry, I couldn't add that"
    assert response.response_type is intent.IntentResponseType.ERROR
    assert voice.issues == {}


# ------------------------------------------------------------------------------- queries (English)


async def test_overdue(hass, voice, freezer):
    freezer.move_to(MONDAY)
    response = await ask(hass, "what is overdue")
    assert speech(response) == "Nothing is overdue"
    assert response.response_type is intent.IntentResponseType.QUERY_ANSWER
    add(voice, "Late one", due="2026-11-12")
    add(voice, "Future", due="2026-12-24")
    finished = add(voice, "Done and late", due="2026-11-01")
    voice.move_issue(finished["id"], "Done")
    assert speech(await ask(hass, "what's overdue")) == "1 issue is overdue: Late one"
    for name, due in (
        ("Late two", "2026-11-05"),
        ("Late three", "2026-11-10"),
        ("Late four", "2026-11-11"),
    ):
        add(voice, name, due=due)
    expected = "4 issues are overdue: Late two, Late three and Late four, and 1 more"
    assert speech(await ask(hass, "what is overdue")) == expected
    for text in (
        "is anything overdue",
        "are there any overdue issues",
        "show me the overdue tasks",
        "how many issues are overdue",
    ):
        assert speech(await ask(hass, text)) == expected, text


async def test_my_list_puts_in_progress_first(hass, voice):
    add(voice, "Pay bills", assignee="person.joachim", due="2026-12-24")
    add(voice, "Call plumber", assignee="person.joachim")
    add(voice, "Paint fence", assignee="person.joachim", status="In progress")
    add(voice, "Water plants", assignee="person.padmaja")
    finished = add(voice, "Old chore", assignee="person.joachim")
    voice.move_issue(finished["id"], "Done")
    expected = "You have 3 open issues: Paint fence (in progress), Pay bills and Call plumber"
    for text in ("what is on my list", "what am I working on", "what do I have to do"):
        response = await ask(hass, text)
        assert speech(response) == expected, text
        assert response.response_type is intent.IntentResponseType.QUERY_ANSWER
    response = await ask(hass, "what's on my list", user="user-1")
    assert speech(response) == "You have 1 open issue: Water plants"


async def test_my_list_when_there_is_nothing(hass, voice):
    assert speech(await ask(hass, "what is on my list")) == "You have nothing open"


@pytest.mark.parametrize("user", [None, "user-9"])
async def test_my_list_for_an_unknown_speaker(hass, voice, user):
    add(voice, "Pay bills", assignee="person.joachim")
    response = await ask(hass, "what is on my list", user=user)
    assert speech(response) == (
        "I don't know who you are. Link your Home Assistant user to a person to use this"
    )
    assert response.response_type is intent.IntentResponseType.ERROR
    # The questions that do not need to know who is asking still work.
    assert speech(await ask(hass, "what is overdue", user=user)) == "Nothing is overdue"


async def test_what_is_a_person_working_on(hass, voice):
    add(voice, "Water plants", assignee="person.padmaja")
    add(voice, "Mow lawn", assignee="person.padmaja", status="In progress")
    for text in (
        "what is Padmaja working on",
        "what's Padmaja working on",
        "what's on Padmaja's list",
        "what does Padmaja have to do",
        "which tasks are assigned to padmaja",
    ):
        expected = "Padmaja has 2 open issues: Mow lawn (in progress) and Water plants"
        assert speech(await ask(hass, text)) == expected, text
    assert speech(await ask(hass, "what is Joachim working on")) == "Joachim has nothing open"


async def test_what_is_an_unknown_or_unclear_person_working_on(hass, voice):
    hass.states.async_set(
        "person.padmini", "home", {"friendly_name": "Padmini", "user_id": "user-2"}
    )
    response = await ask(hass, "what is Bob working on")
    assert speech(response) == "I don't know anyone called Bob"
    assert response.response_type is intent.IntentResponseType.ERROR
    response = await ask(hass, "what is Padm working on")
    assert speech(response) == "Which one do you mean: Padmaja and Padmini?"


async def test_how_is_the_board_doing(hass, voice, freezer):
    freezer.move_to(MONDAY)
    assert speech(await ask(hass, "how is the board doing")) == "Nothing is open on the board"
    add(voice, "Late", due="2026-11-01")
    add(voice, "Soon", due="2026-11-24")
    add(voice, "Whenever")
    add(voice, "Front door camera offline", source="health")
    finished = add(voice, "Done", due="2026-11-02")
    voice.move_issue(finished["id"], "Done")
    expected = (
        "The board has 4 open issues, 1 overdue and 1 due soon. "
        "1 smart home problem needs attention"
    )
    for text in (
        "how is the board doing",
        "how's the board going",
        "board status",
        "what's on the board",
    ):
        assert speech(await ask(hass, text)) == expected, text


# ------------------------------------------------------------------------------- done (English)


async def test_mark_done_by_key(hass, voice):
    add(voice, "Fix the gate")
    events = async_capture_events(hass, EVENT_ISSUE_COMPLETED)
    response = await ask(hass, "mark HOME-1 as done")
    await hass.async_block_till_done()
    assert speech(response) == "Marked HOME-1 as done: Fix the gate"
    issue = voice.resolve_issue("HOME-1")
    assert voice.category(issue) == "done"
    assert issue["activity"][-1]["kind"] == "completed"
    assert issue["activity"][-1]["actor"] == "person.joachim"
    assert [(e.data["key"], e.data["source"], e.data["actor"]) for e in events] == [
        ("HOME-1", "assist", "person.joachim")
    ]


@pytest.mark.parametrize(
    "text",
    [
        "HOME-1 is done",
        "home 1 is done",
        "mark home 1 done",
        "mark issue HOME-1 as complete",
        "mark fix the gate as done",
        "mark gate as finished",
        "mark fix the gait as done",
        "I finished the gate",
        "I'm done with fix the gate",
    ],
)
async def test_mark_done_phrasings(hass, voice, text):
    add(voice, "Fix the gate")
    add(voice, "Pay the electricity bill")
    response = await ask(hass, text)
    assert speech(response) == "Marked HOME-1 as done: Fix the gate", text
    assert voice.category(voice.resolve_issue("HOME-1")) == "done"
    assert voice.category(voice.resolve_issue("HOME-2")) != "done"


async def test_mark_done_does_not_guess_between_several(hass, voice):
    add(voice, "Fix the gate")
    add(voice, "Fix the gate lock")
    response = await ask(hass, "mark gate as done")
    assert speech(response) == (
        "2 issues match gate: HOME-1 Fix the gate and HOME-2 Fix the gate lock. "
        "Say the issue number instead"
    )
    assert response.response_type is intent.IntentResponseType.ERROR
    assert {voice.category(i) for i in voice.issues.values()} == {"todo"}
    # The exact title still singles one out, and the key always does.
    assert speech(await ask(hass, "mark fix the gate as done")).startswith("Marked HOME-1")
    assert speech(await ask(hass, "mark HOME-2 as done")).startswith("Marked HOME-2")


async def test_mark_done_when_it_cannot_be_found_or_is_finished(hass, voice):
    add(voice, "Fix the gate")
    response = await ask(hass, "mark the moon as done")
    assert speech(response) == "I couldn't find an open issue matching the moon"
    assert response.response_type is intent.IntentResponseType.ERROR
    assert speech(await ask(hass, "mark HOME-99 as done")).startswith("I couldn't find")
    await ask(hass, "mark HOME-1 as done")
    events = async_capture_events(hass, EVENT_ISSUE_COMPLETED)
    again = await ask(hass, "mark HOME-1 as done")
    assert speech(again) == "HOME-1 is already done: Fix the gate"
    again = await ask(hass, "mark fix the gate as done")
    assert speech(again) == "HOME-1 is already done: Fix the gate"
    await hass.async_block_till_done()
    assert events == []
    voice.update_issue("HOME-1", archived=True)
    assert speech(await ask(hass, "mark HOME-1 as done")).startswith("I couldn't find")


async def test_mark_done_with_keys_that_start_alike(hass, voice):
    """ "ab12" fits AB-12 and AB1-2: the one that exists wins."""
    voice.create_project(key="AB", name="Alpha")
    voice.create_project(key="AB1", name="Alpha one")
    voice.create_issue("AB1", "Second thing")
    voice.create_issue("AB1", "Another")
    assert speech(await ask(hass, "mark ab12 as done")) == "Marked AB1-2 as done: Another"
    assert speech(await ask(hass, "AB1-1 is done")) == "Marked AB1-1 as done: Second thing"


async def test_mark_done_uses_the_done_column_of_the_issues_own_project(hass, voice):
    voice.create_project(key="KIT", name="Kitchen", template="software")
    issue, _ = voice.create_issue("KIT", "Descale kettle")
    assert speech(await ask(hass, "mark KIT-1 as done")) == "Marked KIT-1 as done: Descale kettle"
    done = next(
        s["id"] for s in voice.resolve_project("KIT")["statuses"] if s["category"] == "done"
    )
    assert voice.resolve_issue(issue["id"])["status"] == done


# ------------------------------------------------------------------------------- Danish


async def test_danish_conversation(hass, voice, freezer):
    freezer.move_to(MONDAY)

    async def ask_da(text: str, **kwargs) -> str:
        return speech(await ask(hass, text, "da", **kwargs))

    assert await ask_da("hvordan går det med tavlen") == "Der er ikke noget åbent på tavlen"
    assert await ask_da("tilføj køb pærer frist fredag til tavlen") == (
        "Tilføjede HOME-1: Køb pærer, frist fredag"
    )
    issue = voice.resolve_issue("HOME-1")
    assert (issue["due"], issue["source"], issue["reporter"]) == (
        "2026-11-27",
        "assist",
        "person.joachim",
    )
    voice.create_project(key="KOK", name="Køkken")
    assert await ask_da("tilføj olie til køkkentavlen") == "Tilføjede KOK-1: Olie"
    assert await ask_da("læg sæbe på køkken tavlen") == "Tilføjede KOK-2: Sæbe"
    assert await ask_da("tilføj tape til projektet HOME") == "Tilføjede HOME-2: Tape"
    assert await ask_da("tilføj snor til haven tavlen") == (
        "Jeg kender ikke en tavle der hedder haven"
    )

    add(voice, "Betal regning", assignee="person.joachim", due="2026-11-10")
    add(voice, "Vask bil", assignee="person.joachim", status="In progress")
    add(voice, "Slå græs", assignee="person.padmaja", status="In progress")
    add(voice, "Mal hegn", assignee="person.padmaja", due="2026-11-12")
    for text in ("hvad er forsinket", "hvilke opgaver er forsinkede", "er der noget forfaldent"):
        assert await ask_da(text) == "2 opgaver er forsinkede: Betal regning og Mal hegn", text
    expected = "Du har 2 åbne opgaver: Vask bil (i gang) og Betal regning"
    for text in ("hvad står der på min liste", "hvad arbejder jeg på", "hvad er mine opgaver"):
        assert await ask_da(text) == expected, text
    expected = "Padmaja har 2 åbne opgaver: Slå græs (i gang) og Mal hegn"
    for text in ("hvad arbejder Padmaja på", "hvad står der på Padmajas liste"):
        assert await ask_da(text) == expected, text
    assert await ask_da("hvad arbejder Bo på") == "Jeg kender ikke nogen der hedder Bo"

    assert await ask_da("marker HOME-1 som færdig") == "Markerede HOME-1 som færdig: Køb pærer"
    assert await ask_da("mal hegn er færdig") == "Markerede HOME-6 som færdig: Mal hegn"
    assert await ask_da("jeg er færdig med sæbe") == "Markerede KOK-2 som færdig: Sæbe"
    assert await ask_da("marker HOME-1 som færdig") == "HOME-1 er allerede færdig: Køb pærer"
    assert await ask_da("marker månen som færdig") == (
        "Jeg kunne ikke finde en åben opgave der passer på månen"
    )
    expected = "Tavlen har 5 åbne opgaver, 1 forsinket og 0 der forfalder snart"
    for text in ("hvordan ser tavlen ud", "hvad står der på tavlen"):
        assert await ask_da(text) == expected, text


async def test_danish_ambiguity_and_unknown_speaker(hass, voice):
    add(voice, "Fix hegnet")
    add(voice, "Fix hegnet igen")
    assert speech(await ask(hass, "marker hegnet som færdig", "da")) == (
        "2 opgaver passer på hegnet: HOME-1 Fix hegnet og HOME-2 Fix hegnet igen. "
        "Sig opgavenummeret i stedet"
    )
    response = await ask(hass, "hvad arbejder jeg på", "da", user=None)
    assert speech(response) == (
        "Jeg ved ikke hvem du er. Knyt din Home Assistant-bruger til en person for at bruge det"
    )
    assert response.response_type is intent.IntentResponseType.ERROR


@pytest.mark.parametrize(
    ("language", "text", "title"),
    [("en-GB", "add tea to the board", "Tea"), ("da-DK", "tilføj te til tavlen", "Te")],
)
async def test_regional_language_variants(hass, voice, language, text, title):
    assert speech(await ask(hass, text, language)).endswith(f": {title}")


async def test_other_languages_get_english_wording(hass, voice):
    """Without sentences of their own they cannot reach the intents, but a handler still answers."""
    response = await intent.async_handle(hass, "test", "HomeboardStatus", {}, None, Context(), "de")
    assert speech(response) == "Nothing is open on the board"


async def test_conversation_process_service_carries_the_user(hass, voice):
    result = await hass.services.async_call(
        "conversation",
        "process",
        {"text": "add oil to the board", "language": "en"},
        blocking=True,
        return_response=True,
        context=Context(user_id="user-1"),
    )
    assert result["response"]["speech"]["plain"]["speech"] == "Added HOME-1: Oil"
    assert voice.resolve_issue("HOME-1")["reporter"] == "person.padmaja"


async def test_intent_when_homeboard_is_not_running(hass, voice):
    manager = hass.data.pop(DOMAIN)
    try:
        response = await ask(hass, "how is the board doing")
        assert speech(response) == "Homeboard is not running"
        assert response.response_type is intent.IntentResponseType.ERROR
    finally:
        hass.data[DOMAIN] = manager


# ------------------------------------------------------------------------------- sentences go live and away


@pytest.mark.parametrize("with_config_yaml", [True, False])
async def test_sentences_work_without_a_restart(hass, manager, config_dir, with_config_yaml):
    if with_config_yaml:
        (config_dir / "configuration.yaml").write_text("", encoding="utf-8")
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    await hass.async_block_till_done()
    on = entry_with(assist_sentences=True)

    before = await ask(hass, "add fix the gate to the board")  # language data is cached from here
    assert before.response_type is intent.IntentResponseType.ERROR
    assert manager.issues == {}

    await async_setup_assist(hass, on)
    assert speech(await ask(hass, "add fix the gate to the board")) == "Added HOME-1: Fix the gate"
    assert speech(await ask(hass, "tilføj hegn til tavlen", "da")) == "Tilføjede HOME-2: Hegn"

    await async_unload_assist(hass, on)
    after = await ask(hass, "add paint to the board")
    assert after.response_type is intent.IntentResponseType.ERROR
    assert len(manager.issues) == 2


async def test_reload_falls_back_to_single_languages(hass, manager, config_dir):
    calls: list[dict] = []

    async def handler(call: ServiceCall) -> None:
        calls.append(dict(call.data))
        if not call.data:
            raise HomeAssistantError("configuration.yaml is broken")

    hass.services.async_register("conversation", "reload", handler)
    await async_setup_assist(hass, entry_with(assist_sentences=True))
    assert calls[0] == {}
    assert sorted(c["language"] for c in calls[1:]) == ["da", "en"]


# ------------------------------------------------------------------------------- files


async def test_handlers_are_registered_even_when_the_option_is_off(
    hass, manager, config_dir, reloads
):
    await async_setup_assist(hass, entry_with())
    assert registered(hass) == INTENTS
    assert not (config_dir / "custom_sentences").exists()
    assert reloads == []


async def test_option_on_writes_marked_files_once(hass, manager, config_dir, reloads):
    on = entry_with(assist_sentences=True)
    await async_setup_assist(hass, on)
    files = sorted(config_dir.glob("custom_sentences/*/homeboard.yaml"))
    assert [f.parent.name for f in files] == ["da", "en"]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert text.splitlines()[0] == MARKER
        document = yaml.safe_load(text)
        assert document["language"] == path.parent.name
        assert set(document["intents"]) == INTENTS
        assert text == (SHIPPED_DIR / f"{path.parent.name}.yaml").read_text(encoding="utf-8")
    assert len(reloads) == 1

    stamps = {f: f.stat().st_mtime_ns for f in files}
    await async_setup_assist(hass, on)  # nothing changed: nothing written, nothing reloaded
    assert {f: f.stat().st_mtime_ns for f in files} == stamps
    assert len(reloads) == 1
    assert registered(hass) == INTENTS


async def test_concurrent_setups_write_once(hass, manager, config_dir, reloads):
    on = entry_with(assist_sentences=True)
    await asyncio.gather(*(async_setup_assist(hass, on) for _ in range(4)))
    assert len(list(config_dir.glob("custom_sentences/*/homeboard.yaml"))) == 2
    assert len(reloads) == 1


async def test_an_older_managed_file_is_brought_up_to_date(hass, manager, config_dir, reloads):
    old = config_dir / "custom_sentences" / "en" / "homeboard.yaml"
    old.parent.mkdir(parents=True)
    old.write_text(f"{MARKER}\nlanguage: en\nintents: {{}}\n", encoding="utf-8")
    await async_setup_assist(hass, entry_with(assist_sentences=True))
    assert old.read_text(encoding="utf-8") == (SHIPPED_DIR / "en.yaml").read_text(encoding="utf-8")
    assert len(reloads) == 1


async def test_a_file_someone_else_wrote_is_never_touched(
    hass, manager, config_dir, reloads, caplog
):
    mine = config_dir / "custom_sentences" / "en" / "homeboard.yaml"
    mine.parent.mkdir(parents=True)
    mine.write_text("language: en\nintents: {}\n", encoding="utf-8")
    other = config_dir / "elsewhere.yaml"
    other.write_text(f"{MARKER}\nlanguage: da\nintents: {{}}\n", encoding="utf-8")
    link = config_dir / "custom_sentences" / "da" / "homeboard.yaml"
    link.parent.mkdir(parents=True)
    link.symlink_to(other)

    with caplog.at_level(logging.WARNING):
        await async_setup_assist(hass, entry_with(assist_sentences=True))
    assert mine.read_text(encoding="utf-8") == "language: en\nintents: {}\n"
    assert link.is_symlink()
    assert other.read_text(encoding="utf-8").endswith("intents: {}\n")
    assert "not managed by Homeboard" in caplog.text
    assert reloads == []

    await async_unload_assist(hass, entry_with())
    assert mine.exists()
    assert link.is_symlink()
    assert other.exists()
    assert reloads == []


async def test_unload_removes_only_what_homeboard_wrote(hass, manager, config_dir, reloads):
    on = entry_with(assist_sentences=True)
    await async_setup_assist(hass, on)
    own = config_dir / "custom_sentences" / "en" / "mine.yaml"
    own.write_text("language: en\nintents: {}\n", encoding="utf-8")
    assert len(reloads) == 1

    await async_unload_assist(hass, on)
    assert registered(hass) == set()
    assert own.exists()  # a user's own file, so its folder stays
    assert not (config_dir / "custom_sentences" / "en" / "homeboard.yaml").exists()
    assert not (config_dir / "custom_sentences" / "da").exists()  # emptied, so removed
    assert len(reloads) == 2

    await async_unload_assist(hass, on)  # safe to repeat, and quiet
    assert len(reloads) == 2
    assert registered(hass) == set()


async def test_reloading_the_entry_does_not_leak(hass, manager, config_dir, reloads):
    on = entry_with(assist_sentences=True)
    await async_setup_assist(hass, on)
    for _ in range(3):
        await async_unload_assist(hass, on)
        await async_setup_assist(hass, on)
    assert registered(hass) == INTENTS
    assert len([h for h in intent.async_get(hass) if h.intent_type.startswith("Homeboard")]) == 6
    assert len(list(config_dir.glob("custom_sentences/*/homeboard.yaml"))) == 2
    assert len(reloads) == 1 + 3 * 2  # one install, then a removal and an install per cycle


async def test_switching_the_option_off_removes_the_files(hass, manager, config_dir, reloads):
    await async_setup_assist(hass, entry_with(assist_sentences=True))
    await async_setup_assist(hass, entry_with(assist_sentences=False))
    assert list(config_dir.glob("custom_sentences/*/homeboard.yaml")) == []
    assert registered(hass) == INTENTS  # the handlers stay: only the sentences were optional
    assert len(reloads) == 2


async def test_unload_leaves_foreign_intent_handlers_alone(hass, manager, reloads):
    class Foreign(intent.IntentHandler):
        intent_type = "SomethingElse"

    intent.async_register(hass, Foreign())
    await async_setup_assist(hass, entry_with())
    await async_unload_assist(hass, entry_with())
    assert "SomethingElse" in {h.intent_type for h in intent.async_get(hass)}


async def test_setup_survives_an_unwritable_config_dir(hass, manager, config_dir, reloads, caplog):
    (config_dir / "custom_sentences").write_text("not a folder", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        await async_setup_assist(hass, entry_with(assist_sentences=True))
    assert "Could not update the Assist sentence files" in caplog.text
    assert registered(hass) == INTENTS
    assert reloads == []


def test_every_shipped_language_covers_every_intent():
    shipped = sorted(p.stem for p in SHIPPED_DIR.glob("*.yaml"))
    assert shipped == ["da", "en"]
    for language in shipped:
        text = (SHIPPED_DIR / f"{language}.yaml").read_text(encoding="utf-8")
        assert text.splitlines()[0] == MARKER
        document = yaml.safe_load(text)
        assert document["language"] == language
        assert set(document["intents"]) == INTENTS
        for name, definition in document["intents"].items():
            assert definition["data"][0]["sentences"], (language, name)
        # Names added to the language data must not collide with Home Assistant's own.
        for section in ("expansion_rules", "lists"):
            assert all(key.startswith("hb_") for key in document[section]), (language, section)


def test_sync_sentence_files_reports_a_blocked_folder(tmp_path):
    blocker = tmp_path / "custom_sentences"
    blocker.write_text("a file where the folder should be", encoding="utf-8")
    with pytest.raises(OSError):
        sync_sentence_files(blocker, True)


# ------------------------------------------------------------------------------- helpers


def test_original_item_restores_the_typed_wording():
    assert _original_item("add bug: gate !high to the board", "bug gate high") == "bug: gate !high"
    assert _original_item("Add Fix it, now to the board.", "Fix it now") == "Fix it, now"
    assert _original_item(None, "milk") == "milk"
    assert _original_item("something else entirely", "milk") == "milk"


@pytest.mark.parametrize(
    ("due", "english", "danish"),
    [
        ("2026-11-23", "today", "i dag"),
        ("2026-11-24", "tomorrow", "i morgen"),
        ("2026-11-27", "Friday", "fredag"),
        ("2026-11-30", "30 November", "30. november"),
        ("2026-11-24T18:30:00+01:00", "tomorrow at 18:30", "i morgen klokken 18:30"),
        ("not a date", "not a date", "not a date"),
    ],
)
async def test_spoken_due(hass, freezer, due, english, danish):
    freezer.move_to(MONDAY)
    assert _spoken_due("en", due) == english
    assert _spoken_due("da", due) == danish


def test_spoken_lists():
    assert _enumerate("en", ["A"]) == "A"
    assert _enumerate("en", ["A", "B"]) == "A and B"
    assert _enumerate("da", ["A", "B", "C", "D", "E"]) == "A, B og C, og 2 mere"
    assert _enumerate("en", ["A", "B", "C"], total=7) == "A, B and C, and 4 more"
    assert _enumerate("en", []) == ""


async def test_title_matching_tiers(hass, manager):
    issues = [add(manager, "Fix the gate"), add(manager, "Fix the gate lock")]
    issues.append(add(manager, "Pay the electricity bill"))

    def keys(text: str) -> list[str]:
        return [i["key"] for i in _issues_by_title(issues, text)]

    assert keys("Fix the gate") == ["HOME-1"]  # equal beats containing
    assert keys("gate") == ["HOME-1", "HOME-2"]
    assert keys("electricity") == ["HOME-3"]
    assert keys("pay the electricty bill") == ["HOME-3"]  # one typo
    assert keys("garden hose") == []
    assert keys("") == []


async def test_person_matching(hass, manager):
    def names(text: str, speaker: str | None = None) -> list[str]:
        return [p["name"] for p in _find_person(manager, text, speaker)]

    assert names("Padmaja") == ["Padmaja"]
    assert names("padmaja's") == ["Padmaja"]
    assert names("Padmajas") == ["Padmaja"]
    assert names("Padm") == ["Padmaja"]
    assert names("Padmaya") == ["Padmaja"]
    assert names("me", "person.joachim") == ["Joachim"]
    assert names("myself") == []
    assert names("nobody") == []
