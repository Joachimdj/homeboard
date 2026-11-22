"""Checklists (subtasks) on issues. Mixed into ``HomeboardData``."""

from __future__ import annotations

from typing import Any

from .const import (
    CHECKLIST_MAX_ITEMS,
    CHECKLIST_TEXT_MAX,
    CONF_CHECKLIST_AUTODONE,
    EVENT_ISSUE_UPDATED,
)
from .model import (
    ConflictError,
    InvalidError,
    NotFoundError,
    clean_text,
    first_with_category,
    new_id,
)


def checklist_counts(issue: dict[str, Any]) -> tuple[int, int]:
    """Return ``(done, total)`` for an issue's checklist."""
    items = issue.get("checklist", [])
    return sum(1 for item in items if item["done"]), len(items)


def _progress(issue: dict[str, Any]) -> str:
    done, total = checklist_counts(issue)
    return f"{done}/{total}"


class ChecklistMixin:
    """Checklist operations. Relies on the host class's helpers (``resolve_issue``, ``_commit`` ...)."""

    def _find_item(self, issue: dict[str, Any], ref: str) -> dict[str, Any]:
        """Return an item by id, or by (case-insensitive) text when that is unambiguous."""
        ref = str(ref).strip()
        for item in issue["checklist"]:
            if item["id"] == ref:
                return item
        matches = [i for i in issue["checklist"] if i["text"].lower() == ref.lower()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ConflictError(f"More than one checklist item is called {ref!r}: use its id")
        raise NotFoundError(f"Unknown checklist item {ref!r}")

    def _checklist_changed(
        self, issue: dict[str, Any], before: str, actor: str | None, source: str, detail: str | None
    ) -> None:
        """Record the change, fire the update event, handle auto-done and save."""
        self._touch(issue)  # type: ignore[attr-defined]
        after = _progress(issue)
        self._activity(issue, actor, "updated", "checklist", before, after)  # type: ignore[attr-defined]
        data = self._issue_event(issue, actor, source)  # type: ignore[attr-defined]
        changes: dict[str, Any] = {"checklist": {"from": before, "to": after}}
        if detail:
            changes["item"] = detail
        self._commit([(EVENT_ISSUE_UPDATED, {**data, "changes": changes})])  # type: ignore[attr-defined]
        done, total = checklist_counts(issue)
        if (
            total
            and done == total
            and self.options.get(CONF_CHECKLIST_AUTODONE)  # type: ignore[attr-defined]
            and self.category(issue) != "done"  # type: ignore[attr-defined]
        ):
            project = self.projects[issue["project_id"]]  # type: ignore[attr-defined]
            self.move_issue(  # type: ignore[attr-defined]
                issue["id"], first_with_category(project, "done")["id"], actor=actor, source=source
            )

    def add_checklist_item(
        self, ref: str, text: str, *, actor: str | None = None, source: str = "service"
    ) -> dict[str, Any]:
        """Append an item."""
        issue = self.resolve_issue(ref)  # type: ignore[attr-defined]
        if len(issue["checklist"]) >= CHECKLIST_MAX_ITEMS:
            raise InvalidError(f"A checklist holds at most {CHECKLIST_MAX_ITEMS} items")
        before = _progress(issue)
        item = {
            "id": new_id(),
            "text": clean_text(
                text, "text", max_len=CHECKLIST_TEXT_MAX, required=True, single_line=True
            ),
            "done": False,
        }
        issue["checklist"].append(item)
        self._checklist_changed(issue, before, actor, source, item["text"])
        return item

    def update_checklist_item(
        self,
        ref: str,
        item_ref: str,
        *,
        text: str | None = None,
        done: bool | None = None,
        actor: str | None = None,
        source: str = "service",
    ) -> dict[str, Any]:
        """Rename an item and / or tick it."""
        issue = self.resolve_issue(ref)  # type: ignore[attr-defined]
        item = self._find_item(issue, item_ref)
        before = _progress(issue)
        changed = False
        if text is not None:
            new_text = clean_text(
                text, "text", max_len=CHECKLIST_TEXT_MAX, required=True, single_line=True
            )
            changed |= new_text != item["text"]
            item["text"] = new_text
        if done is not None and bool(done) != item["done"]:
            item["done"] = bool(done)
            changed = True
        if changed:
            self._checklist_changed(issue, before, actor, source, item["text"])
        return item

    def remove_checklist_item(
        self, ref: str, item_ref: str, *, actor: str | None = None, source: str = "service"
    ) -> None:
        """Remove an item."""
        issue = self.resolve_issue(ref)  # type: ignore[attr-defined]
        item = self._find_item(issue, item_ref)
        before = _progress(issue)
        issue["checklist"].remove(item)
        self._checklist_changed(issue, before, actor, source, item["text"])

    def reorder_checklist(self, ref: str, item_ids: list[str]) -> None:
        """Reorder the items; ``item_ids`` must list every item exactly once."""
        issue = self.resolve_issue(ref)  # type: ignore[attr-defined]
        current = {item["id"]: item for item in issue["checklist"]}
        if sorted(item_ids) != sorted(current) or len(set(item_ids)) != len(item_ids):
            raise InvalidError("item_ids must list every checklist item exactly once")
        issue["checklist"] = [current[i] for i in item_ids]
        self._commit()  # type: ignore[attr-defined]
