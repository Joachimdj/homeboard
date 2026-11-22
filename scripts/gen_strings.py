"""Generate services.yaml, strings.json, translations/{en,da}.json and icons.json from one spec.

Run after changing a service or a string: python scripts/gen_strings.py
(needs PyYAML, which comes with Home Assistant).
"""

import json
import sys
from pathlib import Path

import yaml

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
comp = root / "custom_components" / "homeboard"

TEXT = {"text": {}}
MULTI = {"text": {"multiline": True}}
PERSON = {"entity": {"domain": "person"}}


def sel_select(options, translation_key=None):
    cfg = {"options": options, "mode": "dropdown"}
    if translation_key:
        cfg["translation_key"] = translation_key
    return {"select": cfg}


TYPES = sel_select(["task", "bug", "story", "epic"], "issue_type")
PRIOS = sel_select(["highest", "high", "medium", "low", "lowest"], "priority")
CATS = sel_select(["todo", "in_progress", "done"], "category")
BOOL = {"boolean": {}}
NUM = lambda lo, hi: {"number": {"min": lo, "max": hi, "mode": "box"}}
LABELS = {"text": {"multiple": True}}
DATE = {"date": {}}
DUEANY = {"text": {}}

ISSUE_REF = [
    (
        "issue",
        "Issue",
        "Issue key (HOME-12) or id. Leave empty when you use project + dedupe key.",
        TEXT,
        False,
        "HOME-12",
    ),
    (
        "project",
        "Project",
        "Project key or id. Needed together with the dedupe key.",
        TEXT,
        False,
        "HOME",
    ),
    (
        "dedupe_key",
        "Dedupe key",
        "Find the issue by the dedupe key it was created with (newest open issue of the project).",
        TEXT,
        False,
        "battery_front_door",
    ),
]
ISSUE_FIELDS = [
    ("summary", "Summary", "Title of the issue.", TEXT, False, "Fix the gate latch"),
    ("description", "Description", "Longer description.", MULTI, False, None),
    ("type", "Type", "Issue type.", TYPES, False, "bug"),
    ("priority", "Priority", "Priority.", PRIOS, False, "high"),
    ("assignee", "Assignee", "Person to assign (empty = nobody).", PERSON, False, None),
    ("labels", "Labels", "Labels.", LABELS, False, ["garden"]),
    (
        "due",
        "Due",
        "Due date (2026-12-01) or date and time with offset.",
        DUEANY,
        False,
        "2026-12-01",
    ),
    (
        "parent",
        "Epic",
        "Key of the epic this issue belongs to (empty = none).",
        TEXT,
        False,
        "HOME-3",
    ),
]


def pick(fields, *names):
    return [f for f in fields if f[0] in names]


S = {}
S["create_issue"] = (
    "Create issue",
    "Create an issue on a board. Returns the key. With a dedupe key it never creates the same open issue twice, so it is safe to call from a sensor trigger.",
    [
        ("project", "Project", "Project key or id.", TEXT, True, "HOME"),
        (
            "summary",
            "Summary",
            "Title of the issue.",
            TEXT,
            True,
            "Battery low in the front door sensor",
        ),
        *pick(
            ISSUE_FIELDS, "description", "type", "priority", "assignee", "labels", "due", "parent"
        ),
        (
            "status",
            "Status",
            "Status (column) name or id. Default: the first To do status.",
            TEXT,
            False,
            "To do",
        ),
        (
            "dedupe_key",
            "Dedupe key",
            "Stable key such as battery_front_door. An open issue with the same key is not created again.",
            TEXT,
            False,
            "battery_front_door",
        ),
        (
            "on_duplicate",
            "On duplicate",
            "What to do when an open issue with the dedupe key exists (reopen also revives a done one).",
            sel_select(["skip", "comment", "reopen"], "on_duplicate"),
            False,
            "skip",
        ),
        (
            "source",
            "Source",
            "Where the issue comes from.",
            sel_select(["service", "assist", "siri", "automation", "sensor"], "source"),
            False,
            "sensor",
        ),
    ],
)
S["update_issue"] = (
    "Update issue",
    "Change fields of an issue.",
    ISSUE_REF
    + ISSUE_FIELDS
    + [("status", "Status", "Move to this status (name or id).", TEXT, False, "In progress")],
)
S["move_issue"] = (
    "Move issue",
    "Move an issue to another status (column).",
    ISSUE_REF
    + [
        ("status", "Status", "Target status name or id.", TEXT, True, "Done"),
        (
            "position",
            "Position",
            "Place at the top or the bottom of the column.",
            sel_select(["top", "bottom"], "position"),
            False,
            "bottom",
        ),
    ],
)
S["assign_issue"] = (
    "Assign issue",
    "Assign an issue to a person, or unassign it.",
    ISSUE_REF + pick(ISSUE_FIELDS, "assignee"),
)
S["add_comment"] = (
    "Add comment",
    "Add a comment to an issue.",
    ISSUE_REF
    + [("text", "Comment", "The comment.", MULTI, True, "Checked on site, needs a new part")],
)
S["delete_issue"] = ("Delete issue", "Delete an issue for good.", ISSUE_REF)
S["quick_add"] = (
    "Quick add",
    "Create an issue from one line of text, for example 'bug: gate squeaks @joachim !high #garden due friday'. For Assist, Siri / Shortcuts and text boxes.",
    [
        ("text", "Text", "The line to parse.", TEXT, True, "Buy light bulbs @padmaja due tomorrow"),
        (
            "project",
            "Project",
            "Project key or id (default: the first project).",
            TEXT,
            False,
            "HOME",
        ),
        (
            "source",
            "Source",
            "Where the text comes from.",
            sel_select(["service", "assist", "siri", "automation", "sensor"], "source"),
            False,
            "siri",
        ),
    ],
)
S["create_project"] = (
    "Create project",
    "Create a project (one board).",
    [
        (
            "key",
            "Key",
            "2-6 letters / digits, starts with a letter. Used in issue keys such as HOME-12.",
            TEXT,
            True,
            "HOME",
        ),
        ("name", "Name", "Project name.", TEXT, True, "Home"),
        ("description", "Description", "Description.", MULTI, False, None),
        ("color", "Color", "Colour as hex.", TEXT, False, "#2f80ed"),
        ("icon", "Icon", "mdi icon.", {"icon": {}}, False, "mdi:home"),
        ("lead", "Lead", "Project lead.", PERSON, False, None),
        (
            "template",
            "Template",
            "Starting set of statuses.",
            sel_select(["household", "software", "blank"], "template"),
            False,
            "household",
        ),
    ],
)
S["update_project"] = (
    "Update project",
    "Change a project.",
    [
        ("project", "Project", "Project key or id.", TEXT, True, "HOME"),
        ("name", "Name", "Project name.", TEXT, False, None),
        ("description", "Description", "Description.", MULTI, False, None),
        ("color", "Color", "Colour as hex.", TEXT, False, None),
        ("icon", "Icon", "mdi icon.", {"icon": {}}, False, None),
        ("lead", "Lead", "Project lead.", PERSON, False, None),
        (
            "default_assignee",
            "Default assignee",
            "Assignee for new issues without one.",
            PERSON,
            False,
            None,
        ),
        ("archived", "Archived", "Archive the project.", BOOL, False, None),
    ],
)
S["add_status"] = (
    "Add status",
    "Add a status (board column) to a project.",
    [
        ("project", "Project", "Project key or id.", TEXT, True, "HOME"),
        ("name", "Name", "Status name.", TEXT, True, "Waiting"),
        (
            "category",
            "Category",
            "Decides what counts as open, in progress and done.",
            CATS,
            True,
            "in_progress",
        ),
        (
            "backlog",
            "Backlog",
            "Keep this status off the board (backlog list only).",
            BOOL,
            False,
            None,
        ),
        (
            "wip",
            "WIP limit",
            "Soft limit of issues in this status (empty = none).",
            NUM(1, 999),
            False,
            None,
        ),
        ("position", "Position", "Index to insert at (default: last).", NUM(0, 50), False, None),
    ],
)
S["update_status"] = (
    "Update status",
    "Rename or change a status.",
    [
        ("project", "Project", "Project key or id.", TEXT, True, "HOME"),
        ("status", "Status", "Status name or id.", TEXT, True, "In progress"),
        ("name", "Name", "New name.", TEXT, False, None),
        ("category", "Category", "New category.", CATS, False, None),
        ("backlog", "Backlog", "Backlog flag.", BOOL, False, None),
        ("wip", "WIP limit", "Soft limit (0 / empty = none).", NUM(0, 999), False, None),
    ],
)
S["remove_status"] = (
    "Remove status",
    "Remove a status. Its issues move to another status.",
    [
        ("project", "Project", "Project key or id.", TEXT, True, "HOME"),
        ("status", "Status", "Status to remove (name or id).", TEXT, True, "Waiting"),
        (
            "move_to",
            "Move issues to",
            "Required when the status still has issues.",
            TEXT,
            False,
            "To do",
        ),
    ],
)
REC = [
    ("description", "Description", "Description of the created issues.", MULTI, False, None),
    ("type", "Type", "Issue type.", TYPES, False, "task"),
    ("priority", "Priority", "Priority.", PRIOS, False, None),
    ("assignee", "Assignee", "Person to assign.", PERSON, False, None),
    ("labels", "Labels", "Labels.", LABELS, False, None),
    ("status", "Status", "Status for new issues (default: first To do).", TEXT, False, None),
    (
        "create_days_before",
        "Create days before",
        "Create the issue this many days before it is due.",
        NUM(0, 365),
        False,
        0,
    ),
    (
        "skip_if_open",
        "Skip if open",
        "Do not create a new issue while the previous one is still open.",
        BOOL,
        False,
        None,
    ),
    ("enabled", "Enabled", "Switch the chore on or off.", BOOL, False, None),
]
REPEAT_F = (
    "repeat",
    "Repeat",
    "Rule: {unit: day|week|month|year, every: 1, weekdays: [0-6] (Mon=0), day_of_month: 1-31 or -1}.",
    {"object": {}},
    True,
    {"unit": "week", "every": 1, "weekdays": [2]},
)
S["create_recurring"] = (
    "Create recurring chore",
    "Create an issue on a schedule, for example the bins every Wednesday.",
    [
        ("project", "Project", "Project key or id.", TEXT, True, "HOME"),
        ("summary", "Summary", "Title.", TEXT, True, "Put out the bins"),
        REPEAT_F,
        ("next_due", "Next due", "Due date of the next issue.", DATE, True, "2026-11-25"),
        *REC,
    ],
)
S["update_recurring"] = (
    "Update recurring chore",
    "Change a recurring chore.",
    [
        ("recurring_id", "Recurring id", "Id returned when it was created.", TEXT, True, None),
        ("summary", "Summary", "Title.", TEXT, False, None),
        ("repeat", "Repeat", REPEAT_F[2], {"object": {}}, False, None),
        ("next_due", "Next due", "Due date of the next issue.", DATE, False, None),
        *REC,
    ],
)
S["delete_recurring"] = (
    "Delete recurring chore",
    "Delete a recurring chore (issues it made stay).",
    [("recurring_id", "Recurring id", "Id of the chore.", TEXT, True, None)],
)
S["run_recurring"] = (
    "Run recurring chore now",
    "Create the issue of a recurring chore right now.",
    [("recurring_id", "Recurring id", "Id of the chore.", TEXT, True, None)],
)
S["scan_health"] = (
    "Scan smart home health",
    "Look for faults (offline devices, low batteries, repairs, integration problems) and create, update or close issues. A manual scan acts immediately; with dry run it only reports.",
    [
        ("dry_run", "Dry run", "Only report what would happen, change nothing.", BOOL, False, True),
    ],
)

# ---- services.yaml
out = {}
for name, (_n, _d, fields) in S.items():
    entry = {}
    fl = {}
    for fname, _fn, _fd, selector, required, example in fields:
        f = {}
        if required:
            f["required"] = True
        if example is not None:
            f["example"] = example
        f["selector"] = selector
        fl[fname] = f
    entry["fields"] = fl
    out[name] = entry
header = "# Homeboard services. Generated by scripts/gen_strings.py; names and descriptions live in strings.json.\n"


class NoAlias(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


(comp / "services.yaml").write_text(
    header + yaml.dump(out, Dumper=NoAlias, sort_keys=False, allow_unicode=True, width=100)
)

# ---- strings.json
services = {}
for name, (n, d, fields) in S.items():
    services[name] = {
        "name": n,
        "description": d,
        "fields": {f[0]: {"name": f[1], "description": f[2]} for f in fields},
    }


def labels(*pairs):
    return {k: v for k, v in pairs}


strings = {
    "config": {
        "step": {
            "user": {
                "title": "Set up Homeboard",
                "description": "Homeboard adds a kanban board with projects, issues and an automatic smart-home health check. Everything is managed from the Board panel in the sidebar.",
                "data": {"starter_project": "Create a starter project (HOME)"},
            }
        },
        "abort": {"single_instance_allowed": "Homeboard is already set up."},
    },
    "options": {
        "step": {
            "init": {
                "title": "Homeboard: general",
                "data": {
                    "due_soon_hours": "Due soon window (hours)",
                    "auto_archive_done_days": "Archive done issues after (days, 0 = never)",
                    "panel_title": "Sidebar title",
                    "panel_icon": "Sidebar icon",
                    "panel_admin_only": "Only show the panel to administrators",
                    "tracked_people": "People with their own sensors (empty = everyone)",
                },
            },
            "notifications": {
                "title": "Homeboard: notifications",
                "description": "Push notifications go to the notify services you pick, for example notify.mobile_app_your_phone. Anything fancier is a normal automation on the homeboard_* events.",
                "data": {
                    "notify_services": "Notify services",
                    "notify_done": "Tell me when an issue is done",
                    "notify_overdue": "Tell me when an issue is overdue",
                    "notify_due_soon": "Tell me when an issue is due soon",
                    "notify_health": "Tell me about new high-priority auto issues",
                },
            },
            "health": {
                "title": "Homeboard: smart home health",
                "description": "Homeboard creates issues by itself for things that need fixing and closes them when the fault is gone. Use the scan_health service with dry run to see what it would do before you switch it on.",
                "data": {
                    "health_enabled": "Create issues automatically",
                    "health_unavailable": "Offline devices",
                    "health_battery": "Low batteries",
                    "health_integrations": "Integration problems and re-authentication",
                    "health_repairs": "Home Assistant repairs",
                    "health_updates": "Available updates (one grouped issue)",
                    "health_unavailable_minutes": "Offline for at least (minutes)",
                    "health_battery_threshold": "Battery warning below (%)",
                    "health_project": "Project key for auto issues (empty = FIX, created on demand)",
                    "health_assignee": "Assign auto issues to",
                    "health_snooze_days": "Snooze days when you close an auto issue",
                    "health_max_open": "Maximum open auto issues",
                    "health_exclude_entities": "Never report these entities",
                    "health_exclude_integrations": "Never report these integrations",
                },
            },
        }
    },
    "entity": {
        "sensor": {
            "open_issues": {"name": "Open issues"},
            "overdue": {"name": "Overdue"},
            "due_soon": {"name": "Due soon"},
            "unassigned": {"name": "Unassigned"},
            "last_activity": {"name": "Last activity"},
            "total_open": {"name": "Open issues"},
            "total_overdue": {"name": "Overdue issues"},
            "total_due_soon": {"name": "Issues due soon"},
            "auto_issues": {"name": "Auto-generated issues"},
            "total_last_activity": {"name": "Last activity"},
        },
        "binary_sensor": {"has_overdue": {"name": "Has overdue"}},
        "calendar": {"due_dates": {"name": "Due dates"}},
    },
    "selector": {
        "issue_type": {"options": {"task": "Task", "bug": "Bug", "story": "Story", "epic": "Epic"}},
        "priority": {
            "options": {
                "highest": "Highest",
                "high": "High",
                "medium": "Medium",
                "low": "Low",
                "lowest": "Lowest",
            }
        },
        "category": {"options": {"todo": "To do", "in_progress": "In progress", "done": "Done"}},
        "on_duplicate": {
            "options": {"skip": "Skip", "comment": "Add a comment", "reopen": "Reopen"}
        },
        "source": {
            "options": {
                "service": "Service",
                "assist": "Assist",
                "siri": "Siri / Shortcuts",
                "automation": "Automation",
                "sensor": "Sensor",
            }
        },
        "position": {"options": {"top": "Top", "bottom": "Bottom"}},
        "template": {
            "options": {"household": "Household", "software": "Software", "blank": "Blank"}
        },
    },
    "services": services,
}
text = json.dumps(strings, indent=2, ensure_ascii=False) + "\n"
(comp / "strings.json").write_text(text)
(comp / "translations").mkdir(exist_ok=True)
(comp / "translations" / "en.json").write_text(text)

# ---- icons.json
icons = {
    "services": {
        n: {"service": ic}
        for n, ic in {
            "create_issue": "mdi:plus-box",
            "update_issue": "mdi:pencil",
            "move_issue": "mdi:arrow-right-bold-box",
            "assign_issue": "mdi:account-arrow-right",
            "add_comment": "mdi:comment-plus",
            "delete_issue": "mdi:delete",
            "quick_add": "mdi:flash",
            "create_project": "mdi:folder-plus",
            "update_project": "mdi:folder-edit",
            "add_status": "mdi:view-column",
            "update_status": "mdi:table-column",
            "remove_status": "mdi:table-column-remove",
            "create_recurring": "mdi:calendar-sync",
            "update_recurring": "mdi:calendar-edit",
            "delete_recurring": "mdi:calendar-remove",
            "run_recurring": "mdi:calendar-check",
            "scan_health": "mdi:stethoscope",
        }.items()
    },
    "entity": {
        "sensor": {
            "overdue": {"default": "mdi:alert-circle-outline"},
            "due_soon": {"default": "mdi:clock-alert-outline"},
            "open_issues": {"default": "mdi:format-list-checks"},
            "unassigned": {"default": "mdi:account-question"},
            "auto_issues": {"default": "mdi:robot-outline"},
            "total_overdue": {"default": "mdi:alert-circle-outline"},
            "total_due_soon": {"default": "mdi:clock-alert-outline"},
            "total_open": {"default": "mdi:format-list-checks"},
        },
        "binary_sensor": {
            "has_overdue": {
                "default": "mdi:check-circle-outline",
                "state": {"on": "mdi:alert-circle"},
            }
        },
        "calendar": {"due_dates": {"default": "mdi:calendar-clock"}},
    },
}
(comp / "icons.json").write_text(json.dumps(icons, indent=2) + "\n")
print("generated", len(S), "services")

# ---- Danish translation (translations/da.json)
FN = {  # field name -> (name, description) in Danish, shared by the services
    "issue": (
        "Opgave",
        "Nøgle (HOME-12) eller id. Lad den stå tom, hvis du bruger projekt + dedupe-nøgle.",
    ),
    "project": ("Projekt", "Projektnøgle eller id."),
    "dedupe_key": (
        "Dedupe-nøgle",
        "Stabil nøgle, fx battery_front_door. En åben opgave med samme nøgle oprettes ikke igen.",
    ),
    "summary": ("Titel", "Opgavens titel."),
    "description": ("Beskrivelse", "Længere beskrivelse."),
    "type": ("Type", "Opgavetype."),
    "priority": ("Prioritet", "Prioritet."),
    "assignee": ("Ansvarlig", "Person der får opgaven (tom = ingen)."),
    "labels": ("Etiketter", "Etiketter."),
    "due": ("Frist", "Frist som dato (2026-12-01) eller dato og tid med tidszone."),
    "parent": ("Epic", "Nøglen på den epic opgaven hører til (tom = ingen)."),
    "status": ("Status", "Status (kolonne) som navn eller id."),
    "on_duplicate": (
        "Ved dublet",
        "Hvad der sker, hvis en åben opgave med samme dedupe-nøgle findes (reopen genåbner også en færdig).",
    ),
    "source": ("Kilde", "Hvor opgaven kommer fra."),
    "position": ("Placering", "Øverst eller nederst i kolonnen."),
    "text": ("Tekst", "Teksten der skal fortolkes."),
    "key": ("Nøgle", "2-6 bogstaver/cifre, begynder med bogstav. Bruges i nøgler som HOME-12."),
    "name": ("Navn", "Navn."),
    "color": ("Farve", "Farve som hex."),
    "icon": ("Ikon", "mdi-ikon."),
    "lead": ("Leder", "Projektleder."),
    "template": ("Skabelon", "Startsæt af statusser."),
    "default_assignee": ("Standardansvarlig", "Ansvarlig for nye opgaver uden en."),
    "archived": ("Arkiveret", "Arkivér projektet."),
    "category": ("Kategori", "Afgør hvad der tæller som åben, i gang og færdig."),
    "backlog": ("Backlog", "Hold statussen væk fra tavlen (kun backlog-listen)."),
    "wip": ("WIP-grænse", "Blød grænse for antal opgaver i statussen (tom = ingen)."),
    "move_to": ("Flyt opgaver til", "Kræves hvis statussen stadig har opgaver."),
    "repeat": (
        "Gentagelse",
        "Regel: {unit: day|week|month|year, every: 1, weekdays: [0-6] (man=0), day_of_month: 1-31 eller -1}.",
    ),
    "next_due": ("Næste frist", "Fristen på den næste opgave."),
    "create_days_before": ("Opret dage før", "Opret opgaven så mange dage før fristen."),
    "skip_if_open": ("Spring over hvis åben", "Opret ikke en ny, mens den forrige stadig er åben."),
    "enabled": ("Aktiv", "Slå opgaven til eller fra."),
    "recurring_id": ("Gentagelses-id", "Id'et fra da den blev oprettet."),
    "dry_run": ("Tørløb", "Rapportér kun hvad der ville ske, uden at ændre noget."),
}
SVC_DA = {
    "create_issue": (
        "Opret opgave",
        "Opretter en opgave på en tavle og returnerer nøglen. Med en dedupe-nøgle oprettes aldrig samme åbne opgave to gange, så den er sikker at kalde fra en sensor.",
    ),
    "update_issue": ("Opdater opgave", "Ændrer felter på en opgave."),
    "move_issue": ("Flyt opgave", "Flytter en opgave til en anden status (kolonne)."),
    "assign_issue": (
        "Tildel opgave",
        "Tildeler en opgave til en person eller fjerner tildelingen.",
    ),
    "add_comment": ("Tilføj kommentar", "Tilføjer en kommentar til en opgave."),
    "delete_issue": ("Slet opgave", "Sletter en opgave for altid."),
    "quick_add": (
        "Hurtig tilføjelse",
        "Opretter en opgave ud fra én linje tekst, fx 'bug: låge knirker @joachim !high #have due fredag'. Til Assist, Siri/Genveje og tekstfelter.",
    ),
    "create_project": ("Opret projekt", "Opretter et projekt (en tavle)."),
    "update_project": ("Opdater projekt", "Ændrer et projekt."),
    "add_status": ("Tilføj status", "Tilføjer en status (kolonne) til et projekt."),
    "update_status": ("Opdater status", "Omdøber eller ændrer en status."),
    "remove_status": (
        "Fjern status",
        "Fjerner en status. Dens opgaver flyttes til en anden status.",
    ),
    "create_recurring": (
        "Opret tilbagevendende opgave",
        "Opretter en opgave efter en plan, fx skraldespandene hver onsdag.",
    ),
    "update_recurring": ("Opdater tilbagevendende opgave", "Ændrer en tilbagevendende opgave."),
    "delete_recurring": (
        "Slet tilbagevendende opgave",
        "Sletter en tilbagevendende opgave (opgaver den har lavet bliver).",
    ),
    "run_recurring": (
        "Kør tilbagevendende opgave nu",
        "Opretter opgaven for en tilbagevendende opgave med det samme.",
    ),
    "scan_health": (
        "Scan smart home-sundhed",
        "Leder efter fejl (offline enheder, svage batterier, reparationer, integrationsproblemer) og opretter, opdaterer eller lukker opgaver. En manuel scanning virker med det samme; med tørløb rapporterer den kun.",
    ),
}
da = json.loads(json.dumps(strings))  # deep copy
da["config"] = {
    "step": {
        "user": {
            "title": "Opsæt Homeboard",
            "description": "Homeboard giver en kanban-tavle med projekter, opgaver og et automatisk smart home-sundhedstjek. Alt styres fra panelet Tavle i sidebjælken.",
            "data": {"starter_project": "Opret et startprojekt (HOME)"},
        }
    },
    "abort": {"single_instance_allowed": "Homeboard er allerede sat op."},
}
da["options"]["step"]["init"] = {
    "title": "Homeboard: generelt",
    "data": {
        "due_soon_hours": "Snart forfalden-vindue (timer)",
        "auto_archive_done_days": "Arkivér færdige opgaver efter (dage, 0 = aldrig)",
        "panel_title": "Titel i sidebjælken",
        "panel_icon": "Ikon i sidebjælken",
        "panel_admin_only": "Vis kun panelet for administratorer",
        "tracked_people": "Personer med egne sensorer (tom = alle)",
    },
}
da["options"]["step"]["notifications"] = {
    "title": "Homeboard: notifikationer",
    "description": "Push-beskeder sendes til de notify-tjenester du vælger, fx notify.mobile_app_din_telefon. Alt mere avanceret er en almindelig automatisering på homeboard_*-hændelserne.",
    "data": {
        "notify_services": "Notify-tjenester",
        "notify_done": "Giv besked når en opgave er færdig",
        "notify_overdue": "Giv besked når en opgave er forfalden",
        "notify_due_soon": "Giv besked når en opgave snart forfalder",
        "notify_health": "Giv besked om nye automatiske opgaver med høj prioritet",
    },
}
da["options"]["step"]["health"] = {
    "title": "Homeboard: smart home-sundhed",
    "description": "Homeboard opretter selv opgaver for ting der skal ordnes og lukker dem igen når fejlen er væk. Kør tjenesten scan_health med tørløb for at se hvad den ville gøre, før du slår det til.",
    "data": {
        "health_enabled": "Opret opgaver automatisk",
        "health_unavailable": "Offline enheder",
        "health_battery": "Svage batterier",
        "health_integrations": "Integrationsproblemer og ny login",
        "health_repairs": "Home Assistant-reparationer",
        "health_updates": "Tilgængelige opdateringer (én samlet opgave)",
        "health_unavailable_minutes": "Offline i mindst (minutter)",
        "health_battery_threshold": "Batteriadvarsel under (%)",
        "health_project": "Projektnøgle til automatiske opgaver (tom = FIX, oprettes ved behov)",
        "health_assignee": "Tildel automatiske opgaver til",
        "health_snooze_days": "Udsæt i dage når du lukker en automatisk opgave",
        "health_max_open": "Maks. åbne automatiske opgaver",
        "health_exclude_entities": "Rapportér aldrig disse entiteter",
        "health_exclude_integrations": "Rapportér aldrig disse integrationer",
    },
}
da["entity"] = {
    "sensor": {
        "open_issues": {"name": "Åbne opgaver"},
        "overdue": {"name": "Forfaldne"},
        "due_soon": {"name": "Forfalder snart"},
        "unassigned": {"name": "Uden ansvarlig"},
        "last_activity": {"name": "Seneste aktivitet"},
        "total_open": {"name": "Åbne opgaver"},
        "total_overdue": {"name": "Forfaldne opgaver"},
        "total_due_soon": {"name": "Opgaver der forfalder snart"},
        "auto_issues": {"name": "Automatisk oprettede opgaver"},
        "total_last_activity": {"name": "Seneste aktivitet"},
    },
    "binary_sensor": {"has_overdue": {"name": "Har forfaldne"}},
    "calendar": {"due_dates": {"name": "Frister"}},
}
da["selector"] = {
    "issue_type": {
        "options": {"task": "Opgave", "bug": "Fejl", "story": "Historie", "epic": "Epic"}
    },
    "priority": {
        "options": {
            "highest": "Højeste",
            "high": "Høj",
            "medium": "Mellem",
            "low": "Lav",
            "lowest": "Laveste",
        }
    },
    "category": {"options": {"todo": "Skal laves", "in_progress": "I gang", "done": "Færdig"}},
    "on_duplicate": {
        "options": {"skip": "Spring over", "comment": "Tilføj en kommentar", "reopen": "Genåbn"}
    },
    "source": {
        "options": {
            "service": "Tjeneste",
            "assist": "Assist",
            "siri": "Siri / Genveje",
            "automation": "Automatisering",
            "sensor": "Sensor",
        }
    },
    "position": {"options": {"top": "Øverst", "bottom": "Nederst"}},
    "template": {"options": {"household": "Husholdning", "software": "Software", "blank": "Tom"}},
}
da["services"] = {}
for name, (n, d, fields) in S.items():
    da["services"][name] = {
        "name": SVC_DA[name][0],
        "description": SVC_DA[name][1],
        "fields": {f[0]: {"name": FN[f[0]][0], "description": FN[f[0]][1]} for f in fields},
    }
(comp / "translations" / "da.json").write_text(json.dumps(da, indent=2, ensure_ascii=False) + "\n")
print("wrote da.json")
