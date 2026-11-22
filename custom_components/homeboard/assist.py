"""Assist (voice and text conversation) for Homeboard, in English and Danish.

Two halves:

* **Intent handlers** (``HomeboardAdd`` ... ``HomeboardStatus``) are registered with Home Assistant's intent
  helper whenever the integration is loaded. They answer in the language of the request.
* **Sentences** that trigger the handlers ship in ``assist_sentences/<language>.yaml``. Home Assistant has no
  stable API for an integration to add sentences, so they are copied to
  ``<config>/custom_sentences/<language>/homeboard.yaml`` when the option "Install Assist sentences"
  is on, and removed again (only files that start with ``MARKER``) when it is off or the integration unloads.

See ``docs/ASSIST_NOTES.md`` for the reasoning and for what the integration setup has to call.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent
from homeassistant.util import dt as dt_util
from homeassistant.util.file import write_utf8_file_atomic
from homeassistant.util.hass_dict import HassKey

from .const import CONF_ASSIST_SENTENCES, DOMAIN
from .data import HomeboardData
from .model import HomeboardError, first_with_category

_LOGGER = logging.getLogger(__name__)

"""Option: write the sentence files into ``<config>/custom_sentences`` (default off)."""

MARKER: Final = "# Managed by Homeboard, do not edit"
"""First line of every sentence file Homeboard wrote; only such files are ever replaced or removed."""

SENTENCE_FILE: Final = "homeboard.yaml"
CUSTOM_SENTENCES_DIR: Final = "custom_sentences"
SHIPPED_DIR: Final = Path(__file__).parent / "assist_sentences"
SHIPPED_LANGUAGES: Final = tuple(sorted(path.stem for path in SHIPPED_DIR.glob("*.yaml")))
"""Languages that have sentence templates (read once at import, which happens off the event loop)."""

INTENT_ADD: Final = "HomeboardAdd"
INTENT_OVERDUE: Final = "HomeboardOverdue"
INTENT_MINE: Final = "HomeboardMine"
INTENT_PERSON: Final = "HomeboardPerson"
INTENT_DONE: Final = "HomeboardDone"
INTENT_STATUS: Final = "HomeboardStatus"

LIST_LIMIT: Final = 3
"""How many titles a spoken list names before saying "and N more"."""

DATA_LOCK: HassKey[asyncio.Lock] = HassKey("homeboard_assist_lock")

# ---------------------------------------------------------------------------------------------- speech

WEEKDAYS: Final = {
    "en": ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
    "da": ("mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"),
}
MONTHS: Final = {
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    "da": (
        "januar",
        "februar",
        "marts",
        "april",
        "maj",
        "juni",
        "juli",
        "august",
        "september",
        "oktober",
        "november",
        "december",
    ),
}

# A tuple is (singular, plural), picked by the count passed to ``_say``.
TEXT: Final[dict[str, dict[str, str | tuple[str, str]]]] = {
    "en": {
        "and": "and",
        "more": "and {n} more",
        "in_progress": "in progress",
        "today": "today",
        "tomorrow": "tomorrow",
        "at": "at {time}",
        "date": "{day} {month}",
        "due": ", due {when}",
        "open_issues": ("{n} open issue", "{n} open issues"),
        "added": "Added {key}: {summary}{due}",
        "done": "Marked {key} as done: {summary}",
        "already_done": "{key} is already done: {summary}",
        "done_not_found": "I couldn't find an open issue matching {item}",
        "done_ambiguous": "{n} issues match {item}: {options}. Say the issue number instead",
        "overdue_none": "Nothing is overdue",
        "overdue": ("{n} issue is overdue: {titles}", "{n} issues are overdue: {titles}"),
        "mine_none": "You have nothing open",
        "mine": ("You have {n} open issue: {titles}", "You have {n} open issues: {titles}"),
        "person_none": "{name} has nothing open",
        "person": ("{name} has {n} open issue: {titles}", "{name} has {n} open issues: {titles}"),
        "person_unknown": "I don't know anyone called {name}",
        "person_ambiguous": "Which one do you mean: {options}?",
        "speaker_unknown": (
            "I don't know who you are. Link your Home Assistant user to a person to use this"
        ),
        "project_unknown": "I don't know a board called {project}",
        "project_ambiguous": "Which board do you mean: {options}?",
        "status_empty": "Nothing is open on the board",
        "overdue_word": ("overdue", "overdue"),
        "status": "The board has {open_issues}, {overdue} {overdue_word} and {due_soon} due soon",
        "health": (
            "{n} smart home problem needs attention",
            "{n} smart home problems need attention",
        ),
        "failed": "Sorry, I couldn't do that",
        "failed_add": "Sorry, I couldn't add that",
        "not_running": "Homeboard is not running",
    },
    "da": {
        "and": "og",
        "more": "og {n} mere",
        "in_progress": "i gang",
        "today": "i dag",
        "tomorrow": "i morgen",
        "at": "klokken {time}",
        "date": "{day}. {month}",
        "due": ", frist {when}",
        "open_issues": ("{n} åben opgave", "{n} åbne opgaver"),
        "added": "Tilføjede {key}: {summary}{due}",
        "done": "Markerede {key} som færdig: {summary}",
        "already_done": "{key} er allerede færdig: {summary}",
        "done_not_found": "Jeg kunne ikke finde en åben opgave der passer på {item}",
        "done_ambiguous": "{n} opgaver passer på {item}: {options}. Sig opgavenummeret i stedet",
        "overdue_none": "Der er intet forsinket",
        "overdue": ("{n} opgave er forsinket: {titles}", "{n} opgaver er forsinkede: {titles}"),
        "mine_none": "Du har ikke noget åbent",
        "mine": ("Du har {n} åben opgave: {titles}", "Du har {n} åbne opgaver: {titles}"),
        "person_none": "{name} har ikke noget åbent",
        "person": ("{name} har {n} åben opgave: {titles}", "{name} har {n} åbne opgaver: {titles}"),
        "person_unknown": "Jeg kender ikke nogen der hedder {name}",
        "person_ambiguous": "Hvem mener du: {options}?",
        "speaker_unknown": (
            "Jeg ved ikke hvem du er. Knyt din Home Assistant-bruger til en person for at bruge det"
        ),
        "project_unknown": "Jeg kender ikke en tavle der hedder {project}",
        "project_ambiguous": "Hvilken tavle mener du: {options}?",
        "status_empty": "Der er ikke noget åbent på tavlen",
        "status": "Tavlen har {open_issues}, {overdue} {overdue_word} og {due_soon} der forfalder snart",
        "overdue_word": ("forsinket", "forsinkede"),
        "health": (
            "{n} fejl i smart home skal løses",
            "{n} fejl i smart home skal løses",
        ),
        "failed": "Beklager, det kunne jeg ikke",
        "failed_add": "Beklager, det kunne jeg ikke tilføje",
        "not_running": "Homeboard kører ikke",
    },
}


def _say(lang: str, phrase: str, count: int | None = None, /, **fields: Any) -> str:
    """Return ``phrase`` in ``lang`` (English when the language is not translated)."""
    value = TEXT.get(lang, TEXT["en"])[phrase]
    if isinstance(value, tuple):
        value = value[0] if count == 1 else value[1]
    return value.format(n=count, **fields)


def _language(intent_obj: intent.Intent) -> str:
    """Return the translation to use for the language of the request."""
    base = (intent_obj.language or "en").replace("_", "-").split("-")[0].lower()
    return base if base in TEXT else "en"


def _enumerate(lang: str, items: list[str], total: int | None = None) -> str:
    """Join ``items`` as "A, B and C" and add "and N more" when ``total`` is larger."""
    shown = items[:LIST_LIMIT]
    if not shown:
        return ""
    word = _say(lang, "and")
    text = shown[0] if len(shown) == 1 else f"{', '.join(shown[:-1])} {word} {shown[-1]}"
    extra = (total if total is not None else len(items)) - len(shown)
    if extra > 0:
        text = f"{text}, {_say(lang, 'more', extra)}"
    return text


def _spoken_due(lang: str, due: str) -> str:
    """Turn a due date or datetime into something a voice can say ("tomorrow", "Friday")."""
    try:
        if len(due) == 10:
            day, clock = date.fromisoformat(due), None
        else:
            moment = dt_util.as_local(datetime.fromisoformat(due))
            day, clock = moment.date(), moment.strftime("%H:%M")
    except ValueError:
        return due
    delta = (day - dt_util.now().date()).days
    if delta == 0:
        when = _say(lang, "today")
    elif delta == 1:
        when = _say(lang, "tomorrow")
    elif 1 < delta < 7:
        when = WEEKDAYS.get(lang, WEEKDAYS["en"])[day.weekday()]
    else:
        when = _say(lang, "date", day=day.day, month=MONTHS.get(lang, MONTHS["en"])[day.month - 1])
    if clock:
        when = f"{when} {_say(lang, 'at', time=clock)}"
    return when


# ---------------------------------------------------------------------------------------------- matching

_WORD = re.compile(r"[^\W_]+")
_ARTICLES: Final = frozenset(
    {"the", "a", "an", "my", "our", "den", "det", "en", "et", "min", "mit"}
)
_SPEAKER_WORDS: Final = frozenset({"me", "myself", "i", "my", "mig", "jeg", "min", "mine"})
_KEY_PREFIXES: Final = "issue|task|ticket|opgave|sag"
DUE_WORDS: Final = frozenset({"due", "deadline", "frist", "senest"})
_STRIP: Final = ".,;:!?\u00a1\u00bf\u2026\u2014\u2013\u2015\u2019"
"""What the sentence matcher removes from the ends of words (so typed "bug:" arrives as "bug")."""


def _tokens(text: str) -> list[str]:
    """Return lower-cased words without punctuation or leading articles."""
    words = _WORD.findall(text.casefold())
    while len(words) > 1 and words[0] in _ARTICLES:
        words.pop(0)
    return words


def _norm(text: str) -> str:
    return " ".join(_tokens(text))


def _original_item(text_input: str | None, item: str) -> str:
    """Recover the typed wording of ``item`` (the matcher drops ``:`` and ``!`` from typed text).

    This keeps quick-add tokens such as ``bug:`` and ``!high`` working when the sentence was typed.
    """
    if not text_input:
        return item
    wanted = [word.strip(_STRIP).casefold() for word in item.split()]
    tokens = text_input.split()
    plain = [token.strip(_STRIP).casefold() for token in tokens]
    for start in range(len(tokens) - len(wanted) + 1):
        if plain[start : start + len(wanted)] == wanted:
            return " ".join(tokens[start : start + len(wanted)])
    return item


def _capitalise(text: str) -> str:
    """Capitalise the first letter, unless the line starts with a quick-add token (``bug:``, ``due ...``)."""
    first = text.split(None, 1)[0] if text.strip() else ""
    if not first[:1].isalpha() or first.endswith(":") or first.casefold() in DUE_WORDS:
        return text
    return text[:1].upper() + text[1:]


def _find_project(manager: HomeboardData, text: str) -> list[dict[str, Any]]:
    """Return the active projects a spoken name could mean (key or name)."""
    wanted = _norm(text)
    projects = [p for p in manager.projects.values() if not p["archived"]]
    exact = [p for p in projects if wanted in (p["key"].casefold(), _norm(p["name"]))]
    if exact:
        return exact
    names = {p["id"]: _norm(p["name"]) for p in projects}
    if len(wanted) >= 3:
        loose = [
            p
            for p in projects
            if names[p["id"]]
            and (names[p["id"]].startswith(wanted) or wanted.startswith(names[p["id"]]))
        ]
        if loose:
            return loose
    close = difflib.get_close_matches(wanted, list(names.values()), n=3, cutoff=0.8)
    return [p for p in projects if names[p["id"]] in close]


def _find_person(manager: HomeboardData, text: str, speaker: str | None) -> list[dict[str, Any]]:
    """Return the people a spoken name could mean (the speaker for "me")."""
    people = manager.people()
    cleaned = re.sub(r"['\u2019]s$", "", text.strip(), flags=re.IGNORECASE)
    wanted = _norm(cleaned)
    if wanted in _SPEAKER_WORDS:
        return [p for p in people if p["entity_id"] == speaker]
    names = {p["entity_id"]: _norm(p["name"]) for p in people}
    ids = {p["entity_id"]: p["entity_id"].split(".", 1)[1].replace("_", " ") for p in people}
    # Danish genitive without apostrophe ("Padmajas"): also try the word without its last "s".
    for candidate in (wanted, wanted[:-1] if wanted.endswith("s") else ""):
        if not candidate:
            continue
        exact = [p for p in people if candidate in (names[p["entity_id"]], ids[p["entity_id"]])]
        if exact:
            return exact
        prefix = [
            p
            for p in people
            if names[p["entity_id"]].startswith(candidate)
            or ids[p["entity_id"]].startswith(candidate)
        ]
        if prefix:
            return prefix
    close = difflib.get_close_matches(wanted, list(names.values()), n=3, cutoff=0.75)
    return [p for p in people if names[p["entity_id"]] in close]


def _issue_by_key(manager: HomeboardData, text: str) -> dict[str, Any] | None:
    """Return the issue a spoken key names ("HOME-12", "home 12", "issue home 12"), or None."""
    compact = "".join(_WORD.findall(text.casefold()))
    for project in manager.projects.values():
        key = project["key"].casefold()
        match = re.fullmatch(rf"(?:{_KEY_PREFIXES})?{re.escape(key)}(\d{{1,6}})", compact)
        if match:
            wanted = f"{project['key']}-{int(match.group(1))}"
            if found := next((i for i in manager.issues.values() if i["key"] == wanted), None):
                return (
                    found  # keys such as AB and AB1 can both fit "ab12": take the one that exists
                )
    return None


def _issues_by_title(candidates: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Return the issues whose title best matches ``text``: equal, then containing all words, then close."""
    wanted = _norm(text)
    words = set(wanted.split())
    if not words:
        return []
    titles = {i["id"]: _norm(i["summary"]) for i in candidates}
    equal = [i for i in candidates if titles[i["id"]] == wanted]
    if equal:
        return equal
    containing = [i for i in candidates if words <= set(titles[i["id"]].split())]
    if containing:
        return containing
    close = difflib.get_close_matches(wanted, list(titles.values()), n=5, cutoff=0.8)
    return [i for i in candidates if titles[i["id"]] in close]


def _open_issues(manager: HomeboardData, person: str | None = None) -> list[dict[str, Any]]:
    """Return open, unarchived issues (of one person when given), in-progress first, then by due date."""
    found = [
        issue
        for issue in manager.issues.values()
        if not issue["archived"]
        and manager.category(issue) != "done"
        and (person is None or issue["assignee"] == person)
    ]
    return sorted(
        found,
        key=lambda i: (manager.category(i) != "in_progress", i["due"] or "9999", i["number"]),
    )


def _titles(manager: HomeboardData, lang: str, issues: list[dict[str, Any]]) -> str:
    """Name the first issues, marking those in progress."""
    names = [
        f"{i['summary']} ({_say(lang, 'in_progress')})"
        if manager.category(i) == "in_progress"
        else i["summary"]
        for i in issues[:LIST_LIMIT]
    ]
    return _enumerate(lang, names, len(issues))


# ---------------------------------------------------------------------------------------------- handlers


@dataclass
class Reply:
    """What an intent wants to say, and whether it worked."""

    speech: str
    ok: bool = True
    query: bool = False
    targets: list[tuple[str, str]] = field(default_factory=list)
    """``(key, issue id)`` of the issues the intent touched."""
    code: intent.IntentResponseErrorCode = intent.IntentResponseErrorCode.NO_VALID_TARGETS


class HomeboardIntent(intent.IntentHandler):
    """Common plumbing: manager lookup, speaker, error handling and the response."""

    failure_key = "failed"
    """Phrase spoken when the manager refuses (``HomeboardError``)."""

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Run the intent and turn its ``Reply`` into an intent response."""
        lang = _language(intent_obj)
        manager: HomeboardData | None = intent_obj.hass.data.get(DOMAIN)
        if manager is None:
            reply = Reply(
                _say(lang, "not_running"), ok=False, code=intent.IntentResponseErrorCode.UNKNOWN
            )
        else:
            slots = {
                name: str(slot["value"]).strip()
                for name, slot in self.async_validate_slots(intent_obj.slots).items()
                if isinstance(slot, dict) and "value" in slot
            }
            speaker = manager.person_for_user(intent_obj.context.user_id)
            try:
                reply = self.reply(manager, lang, speaker, slots, intent_obj.text_input)
            except HomeboardError as err:
                _LOGGER.debug("%s could not be handled: %s", self.intent_type, err)
                reply = Reply(
                    _say(lang, self.failure_key),
                    ok=False,
                    code=intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
                )

        response = intent_obj.create_response()
        if not reply.ok:
            response.async_set_error(reply.code, reply.speech)
            return response
        response.async_set_speech(reply.speech)
        if reply.query:
            response.response_type = intent.IntentResponseType.QUERY_ANSWER
        if reply.targets:
            response.async_set_results(
                [
                    intent.IntentResponseTarget(
                        name=key, type=intent.IntentResponseTargetType.CUSTOM, id=issue_id
                    )
                    for key, issue_id in reply.targets
                ]
            )
        return response

    def reply(
        self,
        manager: HomeboardData,
        lang: str,
        speaker: str | None,
        slots: dict[str, str],
        text_input: str | None,
    ) -> Reply:
        """Return the answer (implemented by each intent)."""
        raise NotImplementedError


class AddIntent(HomeboardIntent):
    """ "Add {item} to the board": quick-add, so ``due friday`` and friends work."""

    intent_type = INTENT_ADD
    description = "Add an issue to the Homeboard kanban board, optionally in a named project"
    slot_schema = {"item": intent.non_empty_string, "project": intent.non_empty_string}
    failure_key = "failed_add"

    def reply(
        self,
        manager: HomeboardData,
        lang: str,
        speaker: str | None,
        slots: dict[str, str],
        text_input: str | None,
    ) -> Reply:
        """Return the spoken answer."""
        project_key: str | None = None
        if wanted := slots.get("project"):
            matches = _find_project(manager, wanted)
            if not matches:
                return Reply(_say(lang, "project_unknown", project=wanted), ok=False)
            if len(matches) > 1:
                options = _enumerate(lang, [p["name"] for p in matches])
                return Reply(_say(lang, "project_ambiguous", options=options), ok=False)
            project_key = matches[0]["key"]
        item = _capitalise(_original_item(text_input, slots["item"]))
        issue, _parsed = manager.quick_add(
            item, project=project_key, actor=speaker, source="assist"
        )
        due = _say(lang, "due", when=_spoken_due(lang, issue["due"])) if issue["due"] else ""
        return Reply(
            _say(lang, "added", key=issue["key"], summary=issue["summary"], due=due),
            targets=[(issue["key"], issue["id"])],
        )


class OverdueIntent(HomeboardIntent):
    """ "What is overdue": the count and the first three titles."""

    intent_type = INTENT_OVERDUE
    description = "List the overdue issues on the Homeboard kanban board"

    def reply(
        self,
        manager: HomeboardData,
        lang: str,
        speaker: str | None,
        slots: dict[str, str],
        text_input: str | None,
    ) -> Reply:
        """Return the spoken answer."""
        overdue = manager.top_issues("overdue", limit=len(manager.issues) + 1)
        if not overdue:
            return Reply(_say(lang, "overdue_none"), query=True)
        names = _enumerate(lang, [i["summary"] for i in overdue])
        return Reply(_say(lang, "overdue", len(overdue), titles=names), query=True)


class MineIntent(HomeboardIntent):
    """ "What is on my list": open issues of the speaker, in progress first."""

    intent_type = INTENT_MINE
    description = "List the open Homeboard issues assigned to the person speaking"

    def reply(
        self,
        manager: HomeboardData,
        lang: str,
        speaker: str | None,
        slots: dict[str, str],
        text_input: str | None,
    ) -> Reply:
        """Return the spoken answer."""
        if speaker is None:
            return Reply(_say(lang, "speaker_unknown"), ok=False)
        issues = _open_issues(manager, speaker)
        if not issues:
            return Reply(_say(lang, "mine_none"), query=True)
        return Reply(
            _say(lang, "mine", len(issues), titles=_titles(manager, lang, issues)), query=True
        )


class PersonIntent(HomeboardIntent):
    """ "What is {person} working on": the open issues of a named person."""

    intent_type = INTENT_PERSON
    description = "List the open Homeboard issues assigned to a named person"
    slot_schema = {"person": intent.non_empty_string}

    def reply(
        self,
        manager: HomeboardData,
        lang: str,
        speaker: str | None,
        slots: dict[str, str],
        text_input: str | None,
    ) -> Reply:
        """Return the spoken answer."""
        wanted = slots["person"]
        matches = _find_person(manager, wanted, speaker)
        if not matches:
            if _norm(wanted) in _SPEAKER_WORDS:
                return Reply(_say(lang, "speaker_unknown"), ok=False)
            return Reply(_say(lang, "person_unknown", name=wanted), ok=False)
        if len(matches) > 1:
            options = _enumerate(lang, [p["name"] for p in matches])
            return Reply(_say(lang, "person_ambiguous", options=options), ok=False)
        person = matches[0]
        issues = _open_issues(manager, person["entity_id"])
        if not issues:
            return Reply(_say(lang, "person_none", name=person["name"]), query=True)
        speech = _say(
            lang, "person", len(issues), name=person["name"], titles=_titles(manager, lang, issues)
        )
        return Reply(speech, query=True)


class DoneIntent(HomeboardIntent):
    """ "Mark {item} as done": by key or by title, never by guessing between several."""

    intent_type = INTENT_DONE
    description = "Mark a Homeboard issue as done, by issue key (HOME-12) or by title"
    slot_schema = {"item": intent.non_empty_string}

    def reply(
        self,
        manager: HomeboardData,
        lang: str,
        speaker: str | None,
        slots: dict[str, str],
        text_input: str | None,
    ) -> Reply:
        """Return the spoken answer."""
        wanted = slots["item"]
        found = _issue_by_key(manager, wanted)
        if found is not None:
            candidates = [found] if not found["archived"] else []
        else:
            live = [i for i in manager.issues.values() if not i["archived"]]
            candidates = _issues_by_title(
                [i for i in live if manager.category(i) != "done"], wanted
            )
            if not candidates:  # maybe it was finished already
                candidates = _issues_by_title(
                    [i for i in live if manager.category(i) == "done"], wanted
                )
        if len(candidates) > 1:
            options = _enumerate(
                lang, [f"{i['key']} {i['summary']}" for i in sorted(candidates, key=_number)]
            )
            speech = _say(lang, "done_ambiguous", len(candidates), item=wanted, options=options)
            return Reply(speech, ok=False)
        if not candidates:
            return Reply(_say(lang, "done_not_found", item=wanted), ok=False)
        issue = candidates[0]
        targets = [(issue["key"], issue["id"])]
        if manager.category(issue) == "done":
            speech = _say(lang, "already_done", key=issue["key"], summary=issue["summary"])
            return Reply(speech, targets=targets)
        project = manager.projects[issue["project_id"]]
        manager.move_issue(
            issue["id"], first_with_category(project, "done")["id"], actor=speaker, source="assist"
        )
        speech = _say(lang, "done", key=issue["key"], summary=issue["summary"])
        return Reply(speech, targets=targets)


def _number(issue: dict[str, Any]) -> tuple[str, int]:
    return issue["key"].rsplit("-", 1)[0], issue["number"]


class StatusIntent(HomeboardIntent):
    """ "How is the board doing": open / overdue / due soon, plus the home-health count."""

    intent_type = INTENT_STATUS
    description = "Summarise the Homeboard kanban board: open, overdue and due-soon issues"

    def reply(
        self,
        manager: HomeboardData,
        lang: str,
        speaker: str | None,
        slots: dict[str, str],
        text_input: str | None,
    ) -> Reply:
        """Return the spoken answer."""
        total = manager.stats()["total"]
        if not total["open"]:
            return Reply(_say(lang, "status_empty"), query=True)
        overdue = total["overdue"]
        speech = _say(
            lang,
            "status",
            open_issues=_say(lang, "open_issues", total["open"]),
            overdue=overdue,
            overdue_word=_say(lang, "overdue_word", overdue),
            due_soon=total["due_soon"],
        )
        if total["health_open"]:
            speech = f"{speech}. {_say(lang, 'health', total['health_open'])}"
        return Reply(speech, query=True)


HANDLERS: Final[tuple[type[HomeboardIntent], ...]] = (
    AddIntent,
    OverdueIntent,
    MineIntent,
    PersonIntent,
    DoneIntent,
    StatusIntent,
)


def _register_handlers(hass: HomeAssistant) -> None:
    """Register the handlers that are not ours yet (safe to call again)."""
    registered = {handler.intent_type: handler for handler in intent.async_get(hass)}
    for handler_class in HANDLERS:
        if not isinstance(registered.get(handler_class.intent_type), handler_class):
            intent.async_register(hass, handler_class())


def _unregister_handlers(hass: HomeAssistant) -> None:
    """Remove our handlers, and only ours."""
    registered = {handler.intent_type: handler for handler in intent.async_get(hass)}
    for handler_class in HANDLERS:
        if isinstance(registered.get(handler_class.intent_type), handler_class):
            intent.async_remove(hass, handler_class.intent_type)


# ---------------------------------------------------------------------------------------------- files


def _is_managed(path: Path) -> bool:
    """Return whether ``path`` is a regular file Homeboard wrote (first line is the marker)."""
    if path.is_symlink() or not path.is_file():
        return False
    try:
        with path.open(encoding="utf-8-sig") as handle:
            return handle.readline().strip() == MARKER
    except (OSError, UnicodeDecodeError):
        return False


def _shipped_sentences() -> dict[str, str]:
    """Return ``language -> file text`` of the sentence templates shipped with the integration."""
    shipped = {}
    for path in sorted(SHIPPED_DIR.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        shipped[path.stem] = text if text.startswith(MARKER) else f"{MARKER}\n{text}"
    return shipped


def sync_sentence_files(sentences_dir: Path, install: bool) -> bool:
    """Install (or, with ``install`` False, remove) the managed sentence files.

    Only ``<language>/homeboard.yaml`` files whose first line is ``MARKER`` are replaced or removed; a file
    of the same name that someone else wrote is left alone. Returns whether anything changed on disk.
    """
    wanted = _shipped_sentences() if install else {}
    changed = False
    if sentences_dir.is_dir():
        for target in sorted(sentences_dir.glob(f"*/{SENTENCE_FILE}")):
            if target.parent.name not in wanted and _is_managed(target):
                target.unlink()
                changed = True
                try:
                    target.parent.rmdir()
                except OSError:
                    pass  # other files in there, leave the folder
    for language, text in wanted.items():
        target = sentences_dir / language / SENTENCE_FILE
        if target.exists() or target.is_symlink():
            if not _is_managed(target):
                _LOGGER.warning(
                    "%s exists and is not managed by Homeboard, leaving it alone", target
                )
                continue
            if target.read_text(encoding="utf-8-sig") == text:
                continue
        target.parent.mkdir(parents=True, exist_ok=True)
        write_utf8_file_atomic(str(target), text)
        changed = True
    return changed


async def _async_reload_sentences(hass: HomeAssistant) -> None:
    """Tell the conversation default agent to read the sentence files again."""
    if not hass.services.has_service("conversation", "reload"):
        return  # not loaded yet: it reads the files the first time it needs a language
    try:
        await hass.services.async_call("conversation", "reload", {}, blocking=True)
        return
    except (HomeAssistantError, OSError) as err:
        # The full reload also re-reads configuration.yaml; fall back to clearing languages one by one.
        _LOGGER.debug("conversation.reload failed (%s), reloading single languages", err)
    for language in {hass.config.language, *SHIPPED_LANGUAGES}:
        try:
            await hass.services.async_call(
                "conversation", "reload", {"language": language}, blocking=True
            )
        except (HomeAssistantError, OSError) as err:
            _LOGGER.warning("Could not reload Assist sentences for %s: %s", language, err)


async def _async_sync_files(hass: HomeAssistant, install: bool) -> None:
    """Make ``custom_sentences`` match the option, then reload the sentences if anything changed."""
    lock = hass.data.setdefault(DATA_LOCK, asyncio.Lock())
    sentences_dir = Path(hass.config.path(CUSTOM_SENTENCES_DIR))
    async with lock:
        try:
            changed = await hass.async_add_executor_job(sync_sentence_files, sentences_dir, install)
        except (OSError, HomeAssistantError) as err:
            _LOGGER.warning(
                "Could not update the Assist sentence files in %s: %s", sentences_dir, err
            )
            return
        if changed:
            _LOGGER.debug("Assist sentence files %s", "installed" if install else "removed")
            await _async_reload_sentences(hass)


# ---------------------------------------------------------------------------------------------- setup


async def async_setup_assist(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the intent handlers and make the sentence files match the option (safe to repeat)."""
    _register_handlers(hass)
    await _async_sync_files(hass, bool(entry.options.get(CONF_ASSIST_SENTENCES, False)))


async def async_unload_assist(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unregister the intent handlers and remove the sentence files Homeboard wrote (safe to repeat)."""
    _unregister_handlers(hass)
    await _async_sync_files(hass, False)
