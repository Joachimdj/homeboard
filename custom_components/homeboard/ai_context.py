"""What the AI is told about a smart-home issue (read-only, bounded, with secrets masked).

``build_context`` turns a board issue into a text for the AI plus the list of things the AI may propose to
change (``automations``, ``entries``). Anything the model names that is not on those lists is rejected later.
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import slugify
from homeassistant.util.yaml import dump, load_yaml

from .automation_config import (
    AutomationInfo,
    async_get_automation,
    entity_refs,
    protected_hits,
)
from .const import AI_CONTEXT_CHARS

_LOGGER = logging.getLogger(__name__)

SENSITIVE_KEY = re.compile(
    r"(pass(word|wd)?|token|secret|api_?key|authorization|bearer|webhook_id|credential|private_key"
    r"|(^|_)(pin|code|otp)(_|$))",
    re.IGNORECASE,
)
TOKEN_RE = re.compile(r"__redacted_(\d+)__")
MASK_PREFIX = "masked"
RESTORE_PREFIX = "redacted"
MIN_SECRET_LENGTH = 4
MAX_AUTOMATIONS = 4
TOKEN_BLOCK = 100
MAX_CANDIDATES = 8
MAX_DEVICE_ENTITIES = 15
MAX_TEXT_ENTITIES = 10
TEXT_ENTITY_RE = re.compile(r"\b([a-z0-9_]+\.[a-z0-9_]+)\b")


class RedactionError(ValueError):
    """A placeholder in a model answer that was never sent."""


class Redactor:
    """Replace secrets by ``__redacted_N__`` and put them back later.

    Tokens are numbered by first appearance (from ``start``), so redacting the same config twice gives the
    same tokens. That is what lets Homeboard restore the real values when a proposal is applied, without ever
    storing them. Every automation in one question gets its own ``start``, so a token means one secret only.
    """

    def __init__(
        self,
        secret_values: list[str] | None = None,
        prefix: str = RESTORE_PREFIX,
        start: int = 0,
    ) -> None:
        self.prefix = prefix
        self.start = start
        self.secret_values = sorted(
            {v for v in (secret_values or []) if len(v) >= MIN_SECRET_LENGTH}, key=len, reverse=True
        )
        self._secret_set = set(self.secret_values)
        self.mapping: dict[str, Any] = {}
        self.token_keys: set[str] = set()
        """Keys under which a placeholder stood in the config that was masked (see ``check_placement``)."""
        self._by_value: dict[str, str] = {}

    @property
    def count(self) -> int:
        return len(self.mapping)

    def _token(self, original: Any) -> str:
        key = f"{type(original).__name__}:{original}"
        token = self._by_value.get(key)
        if token is None:
            token = f"__{self.prefix}_{self.start + len(self.mapping) + 1}__"
            self._by_value[key] = token
            self.mapping[token] = original
        return token

    def text(self, value: str) -> str:
        """Mask the known secret values inside a string."""
        for secret in self.secret_values:
            if secret in value:
                value = value.replace(secret, self._token(secret))
        return value

    def hide(self, value: str) -> str:
        """Replace every secret AND every restored value in a text by ``[hidden]`` (for errors and logs)."""
        values = set(self.secret_values) | {
            str(v) for v in self.mapping.values() if len(str(v)) >= 3
        }
        for secret in sorted(values, key=len, reverse=True):
            value = value.replace(secret, "[hidden]")
        return value

    def value(self, node: Any, sensitive: bool = False, key: str | None = None) -> Any:
        """Return a masked copy of a config."""
        if isinstance(node, dict):
            out: dict[Any, Any] = {}
            for name, item in node.items():
                masked_name = self.text(name) if isinstance(name, str) else name
                is_sensitive = isinstance(name, str) and bool(
                    SENSITIVE_KEY.search(name.replace("-", "_"))
                )
                out[masked_name] = self.value(
                    item, is_sensitive, name if isinstance(name, str) else None
                )
            return out
        if isinstance(node, list):
            return [self.value(item, sensitive, key) for item in node]
        if isinstance(node, bool):
            return node
        if isinstance(node, str):
            result = self._token(node) if sensitive else self.text(node)
        elif isinstance(node, (int, float)):
            result = self._token(node) if sensitive or str(node) in self._secret_set else node
        else:
            return node
        if key is not None and isinstance(result, str) and TOKEN_RE.search(result):
            self.token_keys.add(key)
        return result

    def check_placement(self, node: Any, key: str | None = None) -> None:
        """Refuse placeholders in places where the masked config had none (a secret may not be moved)."""
        if isinstance(node, dict):
            for name, item in node.items():
                if isinstance(name, str) and TOKEN_RE.search(name):
                    raise RedactionError("A placeholder cannot be used as a key")
                self.check_placement(item, name if isinstance(name, str) else None)
        elif isinstance(node, list):
            for item in node:
                self.check_placement(item, key)
        elif isinstance(node, str) and TOKEN_RE.search(node) and key not in self.token_keys:
            raise RedactionError(f"The placeholder under {key!r} was not there before")

    def restore(self, node: Any) -> Any:
        """Put the real values back into a model answer (raises ``RedactionError`` for unknown tokens)."""
        if isinstance(node, dict):
            return {self.restore(k): self.restore(v) for k, v in node.items()}
        if isinstance(node, list):
            return [self.restore(item) for item in node]
        if isinstance(node, str):
            whole = TOKEN_RE.fullmatch(node)
            if whole:
                if node not in self.mapping:
                    raise RedactionError(f"Unknown placeholder {node}")
                return self.mapping[node]

            def swap(match: re.Match[str]) -> str:
                token = match.group(0)
                if token not in self.mapping:
                    raise RedactionError(f"Unknown placeholder {token}")
                return str(self.mapping[token])

            return TOKEN_RE.sub(swap, node)
        return node


def _load_secrets(path: str) -> list[str]:
    try:
        data = load_yaml(path)
    except Exception:
        return []
    if not isinstance(data, dict):
        return []
    return [
        str(v)
        for v in data.values()
        if isinstance(v, (str, int, float)) and not isinstance(v, bool)
    ]


async def async_secret_values(hass: HomeAssistant) -> list[str]:
    """Return the values in ``secrets.yaml`` (used only to mask them)."""
    return await hass.async_add_executor_job(_load_secrets, hass.config.path("secrets.yaml"))


@dataclass
class FixContext:
    """Everything the AI is shown, and everything it may touch."""

    text: str
    automations: dict[str, AutomationInfo] = field(default_factory=dict)
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    redactor: Redactor = field(default_factory=lambda: Redactor(prefix=MASK_PREFIX))
    """Masks the text around the automations (issue, facts); never restored."""
    config_redactors: dict[str, Redactor] = field(default_factory=dict)
    """One per automation: its tokens are put back when a proposal for it is applied."""
    dropped_automations: list[str] = field(default_factory=list)
    """Automations that did not fit into the text: they are not offered as targets."""
    entities: int = 0
    subject: str = "general"

    @property
    def stats(self) -> dict[str, int]:
        return {
            "chars": len(self.text),
            "entities": self.entities,
            "automations": len(self.automations),
            "redactions": self.redactor.count
            + sum(r.count for r in self.config_redactors.values()),
        }


# ------------------------------------------------------------------ small helpers


def known_domains(hass: HomeAssistant) -> set[str]:
    """Domains that have at least one entity (so ``foo.bar`` in a template is only an entity if ``foo`` is)."""
    domains = {state.entity_id.split(".", 1)[0] for state in hass.states.async_all()}
    domains |= {entry.domain for entry in er.async_get(hass).entities.values()}
    return domains


def service_checker(hass: HomeAssistant) -> Any:
    """Return ``is_service(domain, name)`` for ``entity_refs``."""
    return hass.services.has_service


def registry_resolver(hass: HomeAssistant) -> Any:
    registry = er.async_get(hass)

    def resolve(registry_id: str) -> str | None:
        entry = registry.async_get(registry_id)
        return entry.entity_id if entry else None

    return resolve


def _friendly(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    if state and state.attributes.get("friendly_name"):
        return str(state.attributes["friendly_name"])
    entry = er.async_get(hass).async_get(entity_id)
    return str(
        (entry.name or entry.original_name)
        if entry and (entry.name or entry.original_name)
        else entity_id
    )


def _area_of(hass: HomeAssistant, entity_id: str) -> str | None:
    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return None
    area_id = entry.area_id
    if area_id is None and entry.device_id:
        device = dr.async_get(hass).async_get(entry.device_id)
        area_id = device.area_id if device else None
    area = ar.async_get(hass).async_get_area(area_id) if area_id else None
    return area.name if area else None


def entity_line(hass: HomeAssistant, entity_id: str) -> str:
    """One line: id, name, state, area, and how long it has been in that state."""
    state = hass.states.get(entity_id)
    entry = er.async_get(hass).async_get(entity_id)
    bits = [entity_id, f'"{_friendly(hass, entity_id)}"']
    if state is None:
        bits.append("state: MISSING (no such entity right now)")
        if entry is not None:
            bits.append(
                f"registry: disabled_by={entry.disabled_by}"
                if entry.disabled_by
                else "registry: present"
            )
    else:
        bits.append(f"state: {state.state[:40]}")
        bits.append(f"since {state.last_changed.isoformat(timespec='minutes')}")
    area = _area_of(hass, entity_id)
    if area:
        bits.append(f"area: {area}")
    return " | ".join(bits)


def candidates_for(hass: HomeAssistant, missing: str, limit: int = MAX_CANDIDATES) -> list[str]:
    """Existing entities of the same domain whose id or name resembles a missing one."""
    domain, _, object_id = missing.partition(".")
    scored: list[tuple[float, str]] = []
    for state in hass.states.async_all(domain):
        other = state.entity_id.split(".", 1)[1]
        name = slugify(str(state.attributes.get("friendly_name") or ""))
        score = max(
            difflib.SequenceMatcher(None, object_id, other).ratio(),
            difflib.SequenceMatcher(None, object_id, name).ratio() if name else 0.0,
        )
        if score >= 0.45:
            scored.append((score, state.entity_id))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [entity_id for _, entity_id in scored[:limit]]


def _raw_config(hass: HomeAssistant, entity_id: str) -> dict[str, Any] | None:
    """Config of an automation that is not in automations.yaml (YAML mode), if Home Assistant has it."""
    try:
        component = hass.data.get("automation")
        entity = component.get_entity(entity_id) if component is not None else None
        raw = getattr(entity, "raw_config", None)
    except Exception:
        return None
    return dict(raw) if isinstance(raw, dict) else None


def touches_protected(hass: HomeAssistant, info: AutomationInfo) -> bool:
    """True when an automation touches the alarm, sirens, locks or valves, or when that cannot be told."""
    configs = [c for c in (info.config, _raw_config(hass, info.entity_id)) if c]
    if not configs:
        return True  # no config to look at: not proven harmless
    return any(protected_hits(hass, config) for config in configs)


def _trace_errors(hass: HomeAssistant, auto_id: str | None, redactor: Redactor) -> list[str]:
    """Errors of the last runs of an automation (best effort; the trace integration may be absent)."""
    if not auto_id:
        return []
    try:
        from homeassistant.components.trace.const import DATA_TRACE

        bucket = hass.data[DATA_TRACE].get(f"automation.{auto_id}")
        runs = getattr(bucket, "runs", None)  # runs first: not-triggered traces never fail
        source = runs.values() if runs is not None else (bucket.all_traces() if bucket else [])
        traces = [t.as_short_dict() for t in source]
    except Exception:
        return []
    lines = []
    for trace in traces[-5:]:
        error = trace.get("error")
        if error:
            start = trace.get("timestamp", {}).get("start", "?")
            lines.append(
                f"{start}: {redactor.text(str(error))[:300]} (last step: {trace.get('last_step')})"
            )
    return lines[-3:]


# ------------------------------------------------------------------ the subject of an issue


@dataclass
class _Subject:
    kind: str = "general"
    facts: list[str] = field(default_factory=list)
    entity_ids: set[str] = field(default_factory=set)
    automation_ids: set[str] = field(default_factory=set)
    entries: dict[str, ConfigEntry] = field(default_factory=dict)


def _entry_facts(entry: ConfigEntry) -> str:
    reason = f", reason: {entry.reason}" if getattr(entry, "reason", None) else ""
    return f"Integration {entry.domain} ({entry.title!r}), config entry {entry.entry_id}, state: {entry.state.value}{reason}"


def _device_subject(hass: HomeAssistant, subject: _Subject, device_id: str) -> bool:
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return False
    name = device.name_by_user or device.name or device.id
    area = ar.async_get(hass).async_get_area(device.area_id) if device.area_id else None
    subject.facts.append(
        f"Device: {name} ({device.manufacturer or '?'} {device.model or ''}), area: {area.name if area else '-'}"
    )
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None:
            subject.entries[entry.entry_id] = entry
            subject.facts.append(_entry_facts(entry))
    registry = er.async_get(hass)
    for entry in er.async_entries_for_device(registry, device_id, include_disabled_entities=False)[
        :MAX_DEVICE_ENTITIES
    ]:
        subject.entity_ids.add(entry.entity_id)
    return True


async def _repair_subject(
    hass: HomeAssistant, subject: _Subject, domain: str, issue_id: str
) -> None:
    issue = ir.async_get(hass).async_get_issue(domain, issue_id)
    if issue is None:
        subject.facts.append(f"The Home Assistant repair {domain}/{issue_id} is no longer open.")
        return
    placeholders = {k: str(v)[:4000] for k, v in (issue.translation_placeholders or {}).items()}
    subject.facts.append(
        f"Home Assistant repair: integration {domain}, id {issue_id}, key {issue.translation_key}, "
        f"severity {issue.severity}, fixable: {issue.is_fixable}"
    )
    for name, value in placeholders.items():
        subject.facts.append(f"  {name}: {value}")  # masked first, clipped later (build_context)
    if domain == "automation" and placeholders.get("entity_id", "").startswith("automation."):
        subject.automation_ids.add(placeholders["entity_id"])
    service = placeholders.get("service")
    if service and "." in service:
        service_domain = service.split(".", 1)[0]
        names = sorted(hass.services.async_services_for_domain(service_domain))
        subject.facts.append(
            f"Services that exist in {service_domain!r}: {', '.join(names) if names else '(none: the integration is not loaded)'}"
        )


async def _subject_for(hass: HomeAssistant, issue: dict[str, Any]) -> _Subject:
    subject = _Subject()
    parts = (issue.get("dedupe_key") or "").split(":")
    # The key is only trusted on issues the scanner made: anyone can type a dedupe key into a new issue.
    if issue.get("source") != "health" or len(parts) < 3 or parts[0] != "health":
        return subject
    detector, rest = parts[1], ":".join(parts[2:])
    subject.kind = detector
    if detector == "repair" and len(parts) >= 4:
        await _repair_subject(hass, subject, parts[2], ":".join(parts[3:]))
    elif detector in ("offline", "battery", "silent"):
        if not _device_subject(hass, subject, rest) and hass.states.get(rest):
            subject.entity_ids.add(rest)
    elif detector in ("entry", "reauth", "offline_entry"):
        entry = hass.config_entries.async_get_entry(rest)
        if entry is not None:
            subject.entries[entry.entry_id] = entry
            subject.facts.append(_entry_facts(entry))
            device_registry = dr.async_get(hass)
            for device in dr.async_entries_for_config_entry(device_registry, entry.entry_id)[:6]:
                _device_subject(hass, subject, device.id)
    elif detector == "automation" and rest.startswith("automation."):
        subject.automation_ids.add(rest)
    return subject


# ------------------------------------------------------------------ build


def _issue_block(issue: dict[str, Any], note: str, redactor: Redactor) -> str:
    lines = [
        f"Key: {issue.get('key')}  type: {issue.get('type')}  priority: {issue.get('priority')}  "
        f"labels: {', '.join(issue.get('labels') or []) or '-'}",
        f"Title: {issue.get('summary', '')}",
    ]
    description = redactor.text((issue.get("description") or "").strip())[:1500]
    if description:
        lines.append("Description:\n" + description)
    for comment in (issue.get("comments") or [])[-3:]:
        lines.append(f"Comment: {redactor.text(str(comment.get('text', '')))[:300]}")
    if note:
        lines.append(f"The owner's hint: {note}")
    return redactor.text("\n".join(lines))


def _entities_in_text(hass: HomeAssistant, issue: dict[str, Any], note: str) -> set[str]:
    blob = " ".join(
        [issue.get("summary", ""), issue.get("description", ""), note]
        + [str(c.get("text", "")) for c in (issue.get("comments") or [])[-3:]]
    )
    found = []
    for candidate in TEXT_ENTITY_RE.findall(blob):
        if hass.states.get(candidate) is not None and candidate not in found:
            found.append(candidate)
    return set(found[:MAX_TEXT_ENTITIES])


@dataclass
class _Section:
    priority: int
    text: str
    automation: str | None = None
    """Set on the section that holds an automation's YAML: it is shown completely or not at all."""


def _fit(sections: list[_Section], max_chars: int) -> tuple[list[_Section], list[str]]:
    """Drop the least important sections until the text fits; never show half an automation."""
    sections = list(sections)
    while sum(len(sec.text) + 2 for sec in sections) > max_chars and any(
        sec.priority > 0 for sec in sections
    ):
        worst = max(sec.priority for sec in sections)
        for index in range(len(sections) - 1, -1, -1):
            if sections[index].priority == worst:
                del sections[index]
                break
    kept: list[_Section] = []
    dropped: list[str] = []
    used = 0
    for sec in sections:
        size = len(sec.text) + 2
        if used + size <= max_chars:
            kept.append(sec)
            used += size
        elif sec.automation:
            dropped.append(sec.automation)
        else:
            room = max_chars - used - 40
            if room > 200:
                kept.append(_Section(sec.priority, sec.text[:room] + "\n(cut: too long)"))
                used = max_chars
    return kept, dropped


async def build_context(
    hass: HomeAssistant,
    issue: dict[str, Any],
    *,
    note: str = "",
    max_chars: int = AI_CONTEXT_CHARS,
) -> FixContext:
    """Collect and render what the AI may see about an issue."""
    secrets = await async_secret_values(hass)
    redactor = Redactor(secrets, prefix=MASK_PREFIX)
    config_redactors: dict[str, Redactor] = {}
    subject = await _subject_for(hass, issue)
    subject.entity_ids |= _entities_in_text(hass, issue, note)
    subject.automation_ids |= {e for e in subject.entity_ids if e.startswith("automation.")}
    domains = known_domains(hass)
    resolve = registry_resolver(hass)

    # automations: the explicit ones, then the ones that use the entities in question
    from homeassistant.components.automation import automations_with_entity

    automation_ids = sorted(subject.automation_ids)
    for entity_id in sorted(subject.entity_ids):
        for found in automations_with_entity(hass, entity_id):
            if found not in automation_ids:
                automation_ids.append(found)
    automations: dict[str, AutomationInfo] = {}
    for entity_id in automation_ids[:MAX_AUTOMATIONS]:
        info = await async_get_automation(hass, entity_id)
        if info is not None:
            automations[entity_id] = info

    sections: list[_Section] = [
        _Section(0, "## The issue on the board\n" + _issue_block(issue, note, redactor))
    ]
    if subject.facts:
        facts = [redactor.text(fact)[:400] for fact in subject.facts]
        sections.append(_Section(1, "## Facts from Home Assistant\n" + "\n".join(facts)))
    if subject.entity_ids:
        lines = [entity_line(hass, e) for e in sorted(subject.entity_ids)[:MAX_DEVICE_ENTITIES]]
        sections.append(_Section(1, "## Entities involved\n" + "\n".join(lines)))

    mentioned: set[str] = set(subject.entity_ids)
    for entity_id, info in automations.items():
        raw = _raw_config(hass, entity_id)
        config = info.config or raw
        header = f"## Automation {entity_id} ({info.name!r}), state: {info.state}"
        if info.config is None:
            info.reasons = info.reasons or ["its config is not available"]
        if config is None:
            sections.append(_Section(0, header + "\nIts config is not available."))
            continue
        refs = entity_refs(config, domains, resolve, service_checker(hass))
        mentioned |= refs
        missing = sorted(r for r in refs if hass.states.get(r) is None)
        protected = sorted(
            {hit for cfg in (info.config, raw) if cfg for hit in protected_hits(hass, cfg)}
        )
        body = [
            header,
            f"Editable by Homeboard: {'yes' if info.editable else 'no (' + '; '.join(info.reasons) + ')'}",
        ]
        if protected:
            body.append(
                f"Touches protected things (alarm, siren, lock, valve): {', '.join(protected)}"
            )
        # numbering starts at a different place per automation, so a token never means two secrets
        config_redactor = config_redactors[entity_id] = Redactor(
            secrets, start=TOKEN_BLOCK * len(config_redactors)
        )
        body.append("```yaml\n" + dump(config_redactor.value(config)).rstrip() + "\n```")
        sections.append(_Section(0, "\n".join(body), automation=entity_id))
        if missing:
            sections.append(
                _Section(
                    2,
                    f"## Entities that automation {entity_id} uses but that do not exist\n"
                    + "\n".join(
                        f"- {m}: possible replacements: {', '.join(candidates_for(hass, m)) or 'none found'}"
                        for m in missing[:10]
                    ),
                )
            )
        errors = _trace_errors(hass, info.auto_id, redactor)
        if errors:
            sections.append(_Section(2, f"## Latest errors of {entity_id}\n" + "\n".join(errors)))

    replacements = sorted(
        {c for m in mentioned if hass.states.get(m) is None for c in candidates_for(hass, m)}
    )
    if replacements:
        sections.append(
            _Section(
                3,
                "## Existing entities that could replace missing ones\n"
                + "\n".join(entity_line(hass, c) for c in replacements[:20]),
            )
        )

    # everything that is not YAML (names, reasons, errors ...) goes through the masking once more
    for sec in sections:
        sec.text = redactor.text(sec.text)
    kept, dropped = _fit(sections, max_chars)
    text = "\n\n".join(sec.text for sec in kept)
    text = text.replace("</context", "<\\/context")  # a name or comment cannot close the data block
    return FixContext(
        text=text,
        automations={k: v for k, v in automations.items() if k not in dropped},
        entries={
            e.entry_id: {"domain": e.domain, "title": e.title, "state": e.state.value}
            for e in subject.entries.values()
        },
        redactor=redactor,
        config_redactors={k: v for k, v in config_redactors.items() if k not in dropped},
        dropped_automations=dropped,
        entities=len(mentioned | subject.entity_ids),
        subject=subject.kind,
    )
