"""To-do list entity: one per project, so Assist can 'add X to the Home list'."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import HomeboardConfigEntry
from .data import UNSET, HomeboardData
from .entity import HomeboardEntity, async_setup_synced_entities
from .model import HomeboardError, default_status, first_with_category

PARALLEL_UPDATES = 0

DONE_VISIBLE_DAYS = 7


def _due_value(due: str | None) -> date | datetime | None:
    if not due:
        return None
    if len(due) == 10:
        return date.fromisoformat(due)
    return dt_util.as_local(datetime.fromisoformat(due))


def _due_string(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (
            dt_util.as_local(value).isoformat()
            if value.tzinfo
            else value.replace(tzinfo=dt_util.get_default_time_zone()).isoformat()
        )
    return value.isoformat()


class HomeboardTodoList(HomeboardEntity, TodoListEntity):
    """The open issues (and recently done ones) of a project as a to-do list."""

    _attr_name = None
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.SET_DUE_DATE_ON_ITEM
        | TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM
        | TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM
    )

    def __init__(self, manager: HomeboardData, project_id: str) -> None:
        """Initialise the list."""
        super().__init__(manager, project_id)
        self._attr_unique_id = f"{project_id}_todo"

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Return the items: open ones in board order, then recently done ones."""
        project = self.project
        if project is None:
            return None
        order = {s["id"]: n for n, s in enumerate(project["statuses"])}
        cutoff = (dt_util.utcnow() - timedelta(days=DONE_VISIBLE_DAYS)).isoformat(
            timespec="seconds"
        )
        rows = []
        for issue in self.manager.project_issues(project["id"]):
            done = self.manager.category(issue) == "done"
            if done and (issue["resolved"] or "") < cutoff:
                continue
            rows.append((done, order[issue["status"]], issue["rank"], issue))
        rows.sort(key=lambda r: r[:3])
        return [
            TodoItem(
                uid=issue["id"],
                summary=issue["summary"],
                status=TodoItemStatus.COMPLETED if done else TodoItemStatus.NEEDS_ACTION,
                due=_due_value(issue["due"]),
                description=issue["description"] or None,
            )
            for done, _pos, _rank, issue in rows
        ]

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create an issue from a to-do item."""
        try:
            issue, _ = self.manager.create_issue(
                self._project_id,
                item.summary or "",
                due=_due_string(item.due),
                description=item.description or "",
                source="todo",
            )
            if item.status == TodoItemStatus.COMPLETED:
                self._set_done(issue["id"], True)
        except HomeboardError as err:
            raise ServiceValidationError(str(err)) from err

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Update summary / description / due and the done state."""
        try:
            issue = self.manager.resolve_issue(item.uid)
            self.manager.update_issue(
                issue["id"],
                source="todo",
                summary=item.summary if item.summary is not None else UNSET,
                description=item.description or "",
                due=_due_string(item.due),
            )
            done = self.manager.category(issue) == "done"
            wanted_done = item.status == TodoItemStatus.COMPLETED
            if wanted_done != done:
                self._set_done(issue["id"], wanted_done)
        except HomeboardError as err:
            raise ServiceValidationError(str(err)) from err

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete issues."""
        try:
            for uid in uids:
                self.manager.delete_issue(uid, source="todo")
        except HomeboardError as err:
            raise ServiceValidationError(str(err)) from err

    @property
    def _project_id(self) -> str:
        assert self.project_id is not None
        return self.project_id

    def _set_done(self, issue_id: str, done: bool) -> None:
        project = self.manager.projects[self._project_id]
        target = first_with_category(project, "done") if done else default_status(project)
        self.manager.move_issue(issue_id, target["id"], source="todo")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeboardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one to-do list per project."""
    manager = entry.runtime_data

    def desired() -> dict[str, Callable[[], Entity]]:
        return {
            f"{pid}_todo": lambda p=pid: HomeboardTodoList(manager, p) for pid in manager.projects
        }

    async_setup_synced_entities(
        hass, manager, "todo", async_add_entities, desired, entry.async_on_unload
    )
