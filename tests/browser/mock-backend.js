// In-memory implementation of every websocket command in docs/PROTOCOL.md
// sections 5 and 10 (plus home health scan), with demo data. DOM free: the
// browser harness and the node tests both use it.

import { FileStore, MINIMAL_PDF, demoPicture } from "./mock-files.js";
import { HEALTH_LEARNED, defaultsFrom, onlyMissing, rhythmGrid, suggestFor, workloadFrom } from "./mock-insights.js";

const PRIORITIES = ["highest", "high", "medium", "low", "lowest"];
const TYPES = ["task", "bug", "story", "epic"];
const CATEGORIES = ["todo", "in_progress", "done"];
const GAP = 1000;
const ADMIN_ONLY = /^(project\/(create|update|delete)|status\/|health\/scan|insights\/forget)/;
const ALLOWED_MIME = ["image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"];
const FEATURES = ["defaults", "patterns", "workload", "health", "rhythm"];
const SUGGESTION_FEATURE = { recurring: "patterns", health_ignore: "health", digest_time: "rhythm" };

const TEMPLATES = {
  household: [["Backlog", "todo", true, null], ["To do", "todo", false, null], ["In progress", "in_progress", false, 3], ["Done", "done", false, null]],
  software: [["Backlog", "todo", true, null], ["To do", "todo", false, null], ["In progress", "in_progress", false, 3], ["Review", "in_progress", false, null], ["Done", "done", false, null]],
  blank: [["To do", "todo", false, null]],
};

const WEEKDAY_WORDS = [
  ["mon", "monday", "man", "mandag"], ["tue", "tuesday", "tir", "tirsdag"], ["wed", "wednesday", "ons", "onsdag"],
  ["thu", "thursday", "tor", "torsdag"], ["fri", "friday", "fre", "fredag"], ["sat", "saturday", "loer", "lørdag", "loerdag"],
  ["sun", "sunday", "søn", "søndag", "soendag"],
];
const PRIORITY_WORDS = { highest: "highest", high: "high", medium: "medium", low: "low", lowest: "lowest", 1: "highest", 2: "high", 3: "medium", 4: "low", 5: "lowest", vigtig: "high", haster: "highest", høj: "high", lav: "low" };

const pad = (n) => String(n).padStart(2, "0");
const dateString = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (date, days) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
const parseDate = (s) => new Date(Number(s.slice(0, 4)), Number(s.slice(5, 7)) - 1, Number(s.slice(8, 10)));

function fail(code, message) {
  const error = new Error(message);
  error.code = code;
  throw error;
}

function offsetString(date) {
  const offset = -date.getTimezoneOffset();
  const abs = Math.abs(offset);
  return `${offset >= 0 ? "+" : "-"}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

function isoNow(date) {
  return `${dateString(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}${offsetString(date)}`;
}

// ---- quick add grammar (basic version of PROTOCOL section 3) ------------------

function resolveWhen(when, today) {
  const text = when.toLowerCase().replace(/\s+/g, " ");
  if (text === "today" || text === "i dag") return today;
  if (text === "tomorrow" || text === "i morgen") return addDays(today, 1);
  if (text === "next week" || text === "næste uge") return addDays(today, 7 - ((today.getDay() + 6) % 7));
  let m = text.match(/^(?:in|om) (\d+) (\w+)$/);
  if (m) return addDays(today, Number(m[1]) * (/^(week|uge)/.test(m[2]) ? 7 : 1));
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return parseDate(text);
  m = text.match(/^(\d{1,2})[./](\d{1,2})$/);
  if (m) {
    const date = new Date(today.getFullYear(), Number(m[2]) - 1, Number(m[1]));
    return date < today ? new Date(today.getFullYear() + 1, Number(m[2]) - 1, Number(m[1])) : date;
  }
  const weekday = WEEKDAY_WORDS.findIndex((names) => names.includes(text));
  if (weekday >= 0) return addDays(today, ((weekday - ((today.getDay() + 6) % 7) + 7) % 7) || 7);
  return null;
}

export function parseQuickAdd(text, { people, projectKeys, today, me }) {
  const parsed = { summary: "", project: null, type: null, priority: null, assignee: null, labels: [], due: null, unresolved: [] };
  let rest = String(text || "");
  for (let i = 0; i < 2; i++) {
    const m = rest.match(/^\s*([A-Za-z][A-Za-z0-9]{1,5})\s*:\s*/);
    if (!m) break;
    if (!parsed.project && projectKeys.includes(m[1].toUpperCase())) parsed.project = m[1].toUpperCase();
    else if (!parsed.type && TYPES.includes(m[1].toLowerCase())) parsed.type = m[1].toLowerCase();
    else break;
    rest = rest.slice(m[0].length);
  }
  const dueRe = /(?<!\S)(?:due|frist|senest)\s+(today|tomorrow|next\s+week|in\s+\d+\s+(?:days?|weeks?)|i\s+dag|i\s+morgen|om\s+\d+\s+(?:dage?|uger?)|\d{4}-\d{2}-\d{2}|\d{1,2}[./]\d{1,2}|[a-zæøå]{3,9})(?:\s+(?:kl\.?\s*)?(\d{1,2}[:.]\d{2}))?(?!\S)/i;
  const dm = rest.match(dueRe);
  if (dm) {
    const when = resolveWhen(dm[1], today);
    if (when) {
      parsed.due = dateString(when);
      if (dm[2]) {
        const [hh, mm] = dm[2].split(/[:.]/).map(Number);
        const dt = new Date(when.getFullYear(), when.getMonth(), when.getDate(), hh, mm);
        parsed.due = `${dateString(dt)}T${pad(hh)}:${pad(mm)}:00${offsetString(dt)}`;
      }
      rest = `${rest.slice(0, dm.index)} ${rest.slice(dm.index + dm[0].length)}`;
    }
  }
  const take = (regex, handler) => {
    rest = rest.replace(regex, (match, token) => (handler(token) ? " " : match));
  };
  take(/(?<!\S)@([\w.-]+)/g, (token) => {
    const wanted = token.toLowerCase();
    let person = wanted === "me" ? me : null;
    if (wanted !== "me") {
      const exact = people.filter((p) => [p.entity_id.split(".")[1].toLowerCase(), p.name.toLowerCase()].includes(wanted));
      const prefix = people.filter((p) => p.entity_id.split(".")[1].toLowerCase().startsWith(wanted) || p.name.toLowerCase().startsWith(wanted));
      person = exact.length === 1 ? exact[0].entity_id : prefix.length === 1 ? prefix[0].entity_id : null;
    }
    if (!person) parsed.unresolved.push(`@${token}`);
    else parsed.assignee = person;
    return Boolean(person);
  });
  take(/(?<!\S)!(\w+)/g, (token) => {
    const priority = PRIORITY_WORDS[token.toLowerCase()];
    if (!priority) parsed.unresolved.push(`!${token}`);
    else parsed.priority = priority;
    return Boolean(priority);
  });
  take(/(?<!\S)#([\w-]+)/g, (token) => {
    parsed.labels.push(token.toLowerCase());
    return true;
  });
  parsed.labels = [...new Set(parsed.labels)];
  parsed.summary = rest.replace(/\s+/g, " ").trim();
  if (!parsed.summary) fail("invalid_format", "Nothing left to use as a title");
  return parsed;
}

// ---- recurrence -----------------------------------------------------------------

function nextOccurrence(dueString, repeat) {
  const due = parseDate(dueString);
  const every = Math.max(1, repeat.every || 1);
  if (repeat.unit === "day") return dateString(addDays(due, every));
  if (repeat.unit === "week") {
    const days = repeat.weekdays?.length ? [...repeat.weekdays].sort() : [(due.getDay() + 6) % 7];
    const current = (due.getDay() + 6) % 7;
    const later = days.find((d) => d > current);
    if (later !== undefined) return dateString(addDays(due, later - current));
    return dateString(addDays(due, 7 * every - current + days[0]));
  }
  if (repeat.unit === "month") {
    const target = new Date(due.getFullYear(), due.getMonth() + every, 1);
    const last = new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate();
    const wanted = repeat.day_of_month === -1 ? last : Math.min(repeat.day_of_month || due.getDate(), last);
    return dateString(new Date(target.getFullYear(), target.getMonth(), wanted));
  }
  const year = due.getFullYear() + every;
  const last = new Date(year, due.getMonth() + 1, 0).getDate();
  return dateString(new Date(year, due.getMonth(), Math.min(due.getDate(), last)));
}

// ---- backend -----------------------------------------------------------------------

export class MockBackend {
  constructor({ seed = true, now = () => new Date() } = {}) {
    this.now = now;
    this.counter = 0;
    this.listeners = new Set();
    this.settings = {
      due_soon_hours: 72,
      panel_title: "Board",
      auto_archive_done_days: 30,
      health_enabled: true,
      learning: { defaults: true, patterns: true, workload: true, health: true, rhythm: false },
      attachments: { enabled: true, max_mb: 10 },
    };
    this.cameras = [
      { entity_id: "camera.front_door", name: "Front door" },
      { entity_id: "camera.garden", name: "Garden" },
    ];
    this.files = new FileStore();
    this.suggestions = [];
    this.handled = new Set(); // accepted or dismissed suggestion ids
    this.forgotten = new Set();
    this.people = [
      { entity_id: "person.joachim", name: "Joachim", picture: null, user_id: "u-joachim" },
      {
        entity_id: "person.padmaja",
        name: "Padmaja",
        user_id: "u-padmaja",
        picture: `data:image/svg+xml;utf8,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" fill="#c2185b"/><circle cx="32" cy="25" r="11" fill="#ffd9c2"/><path d="M10 64c2-18 12-24 22-24s20 6 22 24z" fill="#ffd9c2"/><path d="M19 24c0-10 7-16 13-16s13 6 13 16c-4-6-8-8-13-8s-9 2-13 8z" fill="#2b1b17"/></svg>')}`,
      },
    ];
    this.user = { person: "person.joachim", is_admin: true };
    this.projects = new Map();
    this.issues = new Map();
    this.recurring = new Map();
    if (seed) seedDemo(this);
  }

  /** Harness switches: merges into settings (learning / attachments one level deep) and pushes. */
  setSettings(patch) {
    for (const [key, value] of Object.entries(patch)) {
      this.settings[key] = value && typeof value === "object" ? { ...this.settings[key], ...value } : value;
    }
    this.changed();
  }

  setUser(patch) {
    Object.assign(this.user, patch);
    this.changed();
  }

  id(prefix) {
    return `${prefix}${(++this.counter).toString(36)}`;
  }

  subscribe(callback) {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }

  changed() {
    const payload = this.payload();
    for (const listener of [...this.listeners]) listener(payload);
  }

  // ---- lookups -------------------------------------------------------------------

  project(id) {
    return this.projects.get(id) || fail("not_found", `Project ${id} not found`);
  }

  issue(id) {
    return this.issues.get(id) || fail("not_found", `Issue ${id} not found`);
  }

  statusById(issue) {
    return this.project(issue.project_id).statuses.find((s) => s.id === issue.status);
  }

  isOpen(issue) {
    return this.statusById(issue)?.category !== "done";
  }

  person(entityId) {
    if (entityId && !this.people.some((p) => p.entity_id === entityId)) fail("invalid_format", `Unknown person ${entityId}`);
    return entityId || null;
  }

  // ---- ranks (gap 1000, `before` insertion) ----------------------------------------

  column(projectId, statusId, excludeId = null) {
    return [...this.issues.values()]
      .filter((i) => i.project_id === projectId && i.status === statusId && i.id !== excludeId)
      .sort((a, b) => a.rank - b.rank || a.number - b.number);
  }

  rebalance(list) {
    list.forEach((issue, i) => {
      issue.rank = (i + 1) * GAP;
    });
  }

  rankFor(projectId, statusId, before, excludeId) {
    const list = this.column(projectId, statusId, excludeId);
    if (!list.length) return GAP;
    const index = before == null ? -1 : list.findIndex((i) => i.id === before);
    if (before != null && index === -1) fail("not_found", `Issue ${before} is not in this status`);
    if (index === -1) return list[list.length - 1].rank + GAP;
    const next = list[index];
    const prev = list[index - 1];
    const low = prev ? prev.rank : 0;
    if (next.rank - low < 2) {
      this.rebalance(list);
      return this.rankFor(projectId, statusId, before, excludeId);
    }
    return low + Math.floor((next.rank - low) / 2);
  }

  // ---- activity ---------------------------------------------------------------------

  log(issue, kind, field = null, from = null, to = null) {
    issue.activity.push({ ts: isoNow(this.now()), actor: this.user.person, kind, field, from, to });
    if (issue.activity.length > 100) issue.activity.shift();
    issue.updated = isoNow(this.now());
  }

  // ---- payload ------------------------------------------------------------------------

  flags(issue) {
    if (!issue.due || !this.isOpen(issue)) return { overdue: false, due_soon: false };
    const now = this.now();
    const end = issue.due.length === 10 ? new Date(parseDate(issue.due).getTime() + 86400000 - 1) : new Date(issue.due);
    const overdue = now > end;
    return { overdue, due_soon: !overdue && end - now <= this.settings.due_soon_hours * 3600000 };
  }

  progress(issue) {
    return `${issue.checklist.filter((i) => i.done).length}/${issue.checklist.length}`;
  }

  publicIssue(issue) {
    const { comments, activity, archived, overdue_notified, due_soon_notified, checklist, attachments, ...rest } = issue;
    const result = {
      ...rest,
      ...this.flags(issue),
      comment_count: comments.length,
      checklist_total: checklist.length,
      checklist_done: checklist.filter((i) => i.done).length,
      attachment_count: attachments.length,
    };
    if (issue.type === "epic") {
      const children = [...this.issues.values()].filter((i) => i.parent === issue.id && !i.archived);
      result.epic_total = children.length;
      result.epic_done = children.filter((i) => !this.isOpen(i)).length;
    }
    return result;
  }

  stats(visible) {
    const now = this.now().getTime();
    const empty = () => ({ open: 0, overdue: 0, due_soon: 0, unassigned: 0, done_7d: 0, last_activity: null, health_open: 0 });
    const total = empty();
    const projects = {};
    const people = {};
    const person = (key) => (people[key] ||= { open: 0, overdue: 0, in_progress: 0, done_7d: 0 });
    for (const p of this.projects.values()) projects[p.id] = { ...empty(), by_status: Object.fromEntries(p.statuses.map((s) => [s.id, 0])), by_priority: {}, by_type: {} };
    for (const issue of visible) {
      const status = this.statusById(issue);
      const flags = this.flags(issue);
      const key = issue.assignee || "unassigned";
      const bucket = projects[issue.project_id];
      bucket.by_status[issue.status] += 1;
      for (const target of [total, bucket]) {
        if (!target.last_activity || issue.updated > target.last_activity) target.last_activity = issue.updated;
        if (status.category === "done") {
          if (issue.resolved && now - new Date(issue.resolved).getTime() <= 7 * 86400000) target.done_7d += 1;
          continue;
        }
        target.open += 1;
        if (flags.overdue) target.overdue += 1;
        if (flags.due_soon) target.due_soon += 1;
        if (!issue.assignee) target.unassigned += 1;
        if (issue.source === "health") target.health_open += 1;
      }
      if (status.category === "done") {
        if (issue.resolved && now - new Date(issue.resolved).getTime() <= 7 * 86400000) person(key).done_7d += 1;
      } else {
        bucket.by_priority[issue.priority] = (bucket.by_priority[issue.priority] || 0) + 1;
        bucket.by_type[issue.type] = (bucket.by_type[issue.type] || 0) + 1;
        person(key).open += 1;
        if (flags.overdue) person(key).overdue += 1;
        if (status.category === "in_progress") person(key).in_progress += 1;
      }
    }
    return { total, projects, people };
  }

  payload() {
    const visible = [...this.issues.values()].filter((i) => !i.archived);
    return {
      version: "0.1.0",
      settings: { ...structuredClone(this.settings), insights_open: this.openSuggestions().length },
      me: this.user.person,
      is_admin: this.user.is_admin,
      people: this.people.map((p) => ({ ...p })),
      projects: [...this.projects.values()].map((p) => structuredClone(p)),
      issues: visible.map((i) => this.publicIssue(i)),
      recurring: [...this.recurring.values()].map((r) => structuredClone(r)),
      stats: this.stats(visible),
    };
  }

  // ---- entry point ----------------------------------------------------------------------

  handle(message) {
    const { type, ...params } = message;
    const name = String(type || "").replace(/^homeboard\//, "");
    if (ADMIN_ONLY.test(name) && !this.user.is_admin) fail("unauthorized", "Only administrators can do that");
    const command = this.commands[name];
    if (!command) fail("not_found", `Unknown command ${type}`);
    return command.call(this, params);
  }

  get commands() {
    return COMMANDS;
  }

  // ---- helpers used by commands --------------------------------------------------------------

  cleanLabels(labels) {
    return [...new Set((labels || []).map((l) => String(l).trim().replace(/^#/, "").toLowerCase()).filter(Boolean))];
  }

  enumValue(value, allowed, field) {
    if (!allowed.includes(value)) fail("invalid_format", `${field} must be one of ${allowed.join(", ")}`);
    return value;
  }

  growLabels(project, labels) {
    for (const label of labels) if (!project.labels.includes(label)) project.labels.push(label);
  }

  defaultStatus(project) {
    return (project.statuses.find((s) => s.category === "todo" && !s.backlog) || project.statuses.find((s) => !s.backlog) || project.statuses[0]).id;
  }

  newIssue(project, fields, source = "ui") {
    const summary = String(fields.summary || "").trim();
    if (!summary) fail("invalid_format", "summary is required");
    const status = fields.status || this.defaultStatus(project);
    if (!project.statuses.some((s) => s.id === status)) fail("not_found", `Status ${status} not found`);
    if (fields.parent) {
      const parent = this.issue(fields.parent);
      if (parent.type !== "epic" || parent.project_id !== project.id) fail("invalid_format", "parent must be an epic of the same project");
    }
    const now = isoNow(this.now());
    const labels = this.cleanLabels(fields.labels);
    this.growLabels(project, labels);
    project.issue_seq += 1;
    const id = this.id("iss");
    const issue = {
      id, project_id: project.id, number: project.issue_seq, key: `${project.key}-${project.issue_seq}`,
      type: this.enumValue(fields.issue_type || fields.type || "task", TYPES, "issue_type"), summary, description: fields.description || "",
      status, priority: this.enumValue(fields.priority || "medium", PRIORITIES, "priority"),
      assignee: this.person(fields.assignee ?? null), reporter: this.user.person, labels, parent: fields.parent || null,
      due: fields.due || null, rank: this.rankFor(project.id, status, null, null), dedupe_key: fields.dedupe_key || null,
      recurring_id: fields.recurring_id || null, source, created: now, updated: now, resolved: null, archived: false,
      overdue_notified: false, due_soon_notified: false, comments: [], activity: [], checklist: [], attachments: [],
    };
    if (this.projectStatus(project, status).category === "done") issue.resolved = now;
    this.issues.set(id, issue);
    this.log(issue, "created");
    return issue;
  }

  projectStatus(project, statusId) {
    return project.statuses.find((s) => s.id === statusId);
  }

  fullIssue(issue) {
    return {
      ...this.publicIssue(issue),
      comments: structuredClone(issue.comments),
      activity: structuredClone(issue.activity),
      checklist: structuredClone(issue.checklist),
      attachments: issue.attachments.map((a) => this.publicAttachment(a)),
    };
  }

  // ---- files ---------------------------------------------------------------------------

  publicAttachment(attachment) {
    return { ...attachment, url: this.files.url(attachment.id), thumb_url: this.files.url(attachment.id, true) };
  }

  addAttachment(issue, { name, mime, bytes, thumb = null, source = "upload" }) {
    const attachment = { id: this.id("att"), name, mime, size: bytes.length, ts: isoNow(this.now()), author: this.user.person, source };
    this.files.add(attachment.id, { mime, bytes, thumb });
    issue.attachments.push(attachment);
    this.log(issue, "updated", "attachments", String(issue.attachments.length - 1), String(issue.attachments.length));
    return attachment;
  }

  /** What POST /api/homeboard/upload answers: { status, body }. */
  upload({ issue_id, name, mime, bytes }) {
    if (!this.settings.attachments.enabled) return { status: 403, body: { message: "Attachments are switched off" } };
    const issue = this.issues.get(issue_id);
    if (!issue) return { status: 404, body: { message: "Issue not found" } };
    if (!ALLOWED_MIME.includes(mime)) return { status: 415, body: { message: "Unsupported file type" } };
    if (bytes.length > this.settings.attachments.max_mb * 1024 * 1024) return { status: 413, body: { message: "File too large" } };
    const attachment = this.addAttachment(issue, { name, mime, bytes });
    this.changed();
    return { status: 200, body: this.publicAttachment(attachment) };
  }

  // ---- learning -------------------------------------------------------------------------

  openSuggestions() {
    return this.suggestions.filter((s) => !this.handled.has(s.id) && this.settings.learning[SUGGESTION_FEATURE[s.kind]] && !this.forgotten.has(SUGGESTION_FEATURE[s.kind]));
  }

  suggestionCandidates() {
    return [...this.issues.values()]
      .filter((i) => !i.archived)
      .map((i) => ({ key: i.key, summary: i.summary, status: this.statusById(i)?.name, assignee: i.assignee, labels: i.labels, priority: i.priority, due: i.due, created: i.created }));
  }

  suggest(text) {
    return this.settings.learning.defaults && !this.forgotten.has("defaults") ? suggestFor(text, this.suggestionCandidates()) : null;
  }

  learnedData() {
    const learning = this.settings.learning;
    const live = [...this.issues.values()].filter((i) => !i.archived);
    const learned = {};
    const gone = (feature) => this.forgotten.has(feature);
    if (learning.defaults) learned.defaults = gone("defaults") ? { issues_analysed: 0, top_labels: [], people: [] } : defaultsFrom(live);
    if (learning.workload) {
      learned.workload = gone("workload") ? { people: {}, types: {}, labels: {} } : workloadFrom(live, (i) => !this.isOpen(i), this.people, this.now().getTime());
    }
    if (learning.rhythm) {
      learned.rhythm = {
        people: Object.fromEntries(this.people.map((p, n) => [p.entity_id, gone("rhythm") ? { samples: 0, grid: Array.from({ length: 7 }, () => Array(24).fill(0)) } : { samples: 2016, grid: rhythmGrid(n) }])),
      };
    }
    if (learning.health) learned.health = gone("health") ? { tracked_sensors: 0, silent: [], flapping: [] } : structuredClone(HEALTH_LEARNED);
    return learned;
  }
}

const COMMANDS = {
  get() {
    return this.payload();
  },

  "project/create"({ key, name, description = "", color = "#2f80ed", icon = "mdi:folder-outline", lead = null, template = "household" }) {
    if (!/^[A-Z0-9]{2,6}$/.test(String(key))) fail("invalid_format", "key must be 2-6 characters A-Z0-9");
    if (!String(name || "").trim()) fail("invalid_format", "name is required");
    if (!TEMPLATES[template]) fail("invalid_format", `Unknown template ${template}`);
    if ([...this.projects.values()].some((p) => p.key === key)) fail("conflict", `Project key ${key} already exists`);
    const project = {
      id: this.id("prj"), key, name: name.trim(), description, color, icon, lead: this.person(lead), default_assignee: null, archived: false,
      created: isoNow(this.now()), labels: [], issue_seq: 0,
      statuses: TEMPLATES[template].map(([statusName, category, backlog, wip]) => ({ id: this.id("st"), name: statusName, category, backlog, wip })),
    };
    this.projects.set(project.id, project);
    this.changed();
    return structuredClone(project);
  },

  "project/update"({ project_id, ...fields }) {
    const project = this.project(project_id);
    for (const field of ["name", "description", "color", "icon", "archived"]) if (field in fields) project[field] = fields[field];
    if ("lead" in fields) project.lead = this.person(fields.lead);
    if ("default_assignee" in fields) project.default_assignee = this.person(fields.default_assignee);
    if ("labels" in fields) project.labels = this.cleanLabels(fields.labels);
    if (!project.name.trim()) fail("invalid_format", "name is required");
    this.changed();
    return structuredClone(project);
  },

  "project/delete"({ project_id, confirm }) {
    const project = this.project(project_id);
    if (confirm !== true) fail("invalid_format", "confirm must be true");
    for (const [id, issue] of this.issues) if (issue.project_id === project.id) this.issues.delete(id);
    for (const [id, rec] of this.recurring) if (rec.project_id === project.id) this.recurring.delete(id);
    this.projects.delete(project.id);
    this.changed();
    return { deleted: project.id };
  },

  "status/create"({ project_id, name, category, backlog = false, wip = null, position = null }) {
    const project = this.project(project_id);
    if (!String(name || "").trim()) fail("invalid_format", "name is required");
    const status = { id: this.id("st"), name: name.trim(), category: this.enumValue(category, CATEGORIES, "category"), backlog: Boolean(backlog), wip: wip ?? null };
    project.statuses.splice(position == null ? project.statuses.length : Math.max(0, Math.min(position, project.statuses.length)), 0, status);
    this.changed();
    return { ...status };
  },

  "status/update"({ project_id, status_id, ...fields }) {
    const project = this.project(project_id);
    const status = this.projectStatus(project, status_id) || fail("not_found", `Status ${status_id} not found`);
    if ("name" in fields) {
      if (!String(fields.name).trim()) fail("invalid_format", "name is required");
      status.name = fields.name.trim();
    }
    if ("category" in fields) {
      const before = status.category;
      status.category = this.enumValue(fields.category, CATEGORIES, "category");
      if (before !== "done" && status.category === "done") for (const i of this.column(project.id, status.id)) i.resolved ||= isoNow(this.now());
    }
    if ("backlog" in fields) status.backlog = Boolean(fields.backlog);
    if ("wip" in fields) status.wip = fields.wip == null ? null : Math.max(1, Number(fields.wip) || 1);
    this.changed();
    return { ...status };
  },

  "status/reorder"({ project_id, status_ids }) {
    const project = this.project(project_id);
    const current = project.statuses.map((s) => s.id).sort().join(",");
    if (!Array.isArray(status_ids) || [...status_ids].sort().join(",") !== current) fail("invalid_format", "status_ids must list every status exactly once");
    project.statuses = status_ids.map((id) => this.projectStatus(project, id));
    this.changed();
    return { ok: true };
  },

  "status/delete"({ project_id, status_id, move_to = null }) {
    const project = this.project(project_id);
    this.projectStatus(project, status_id) || fail("not_found", `Status ${status_id} not found`);
    if (project.statuses.length <= 1) fail("invalid_format", "A project needs at least one status");
    const affected = this.column(project.id, status_id);
    if (affected.length) {
      if (!move_to || move_to === status_id || !this.projectStatus(project, move_to)) fail("invalid_format", "move_to is required while issues use this status");
      for (const issue of affected) {
        issue.status = move_to;
        issue.rank = this.rankFor(project.id, move_to, null, issue.id);
        this.log(issue, "moved", "status", this.projectStatus(project, status_id).name, this.projectStatus(project, move_to).name);
      }
    }
    project.statuses = project.statuses.filter((s) => s.id !== status_id);
    this.changed();
    return { deleted: status_id };
  },

  "issue/create"(params) {
    const project = this.project(params.project_id);
    const issue = this.newIssue(project, params);
    this.changed();
    return this.publicIssue(issue);
  },

  "issue/get"({ issue_id }) {
    return this.fullIssue(this.issue(issue_id));
  },

  "issue/update"({ issue_id, ...fields }) {
    const issue = this.issue(issue_id);
    const project = this.project(issue.project_id);
    const setField = (field, value, kind = "updated") => {
      if (JSON.stringify(issue[field]) === JSON.stringify(value)) return;
      this.log(issue, kind, field, issue[field], value);
      issue[field] = value;
    };
    if ("summary" in fields) {
      if (!String(fields.summary).trim()) fail("invalid_format", "summary is required");
      setField("summary", fields.summary.trim());
    }
    if ("description" in fields) setField("description", fields.description || "");
    if ("issue_type" in fields) setField("type", this.enumValue(fields.issue_type, TYPES, "issue_type"));
    if ("priority" in fields) setField("priority", this.enumValue(fields.priority, PRIORITIES, "priority"));
    if ("assignee" in fields) setField("assignee", this.person(fields.assignee), "assigned");
    if ("labels" in fields) {
      const labels = this.cleanLabels(fields.labels);
      this.growLabels(project, labels);
      setField("labels", labels);
    }
    if ("due" in fields) setField("due", fields.due || null);
    if ("parent" in fields) {
      if (fields.parent) {
        const parent = this.issue(fields.parent);
        if (parent.type !== "epic" || parent.project_id !== issue.project_id || parent.id === issue.id) fail("invalid_format", "parent must be an epic of the same project");
      }
      setField("parent", fields.parent || null);
    }
    if ("archived" in fields && Boolean(fields.archived) !== issue.archived) {
      issue.archived = Boolean(fields.archived);
      this.log(issue, "archived");
    }
    this.changed();
    return this.publicIssue(issue);
  },

  "issue/move"({ issue_id, status, before = null }) {
    const issue = this.issue(issue_id);
    const project = this.project(issue.project_id);
    const target = this.projectStatus(project, status) || fail("not_found", `Status ${status} not found`);
    if (before === issue.id) fail("invalid_format", "An issue cannot be moved before itself");
    const previous = this.projectStatus(project, issue.status);
    issue.rank = this.rankFor(project.id, status, before, issue.id);
    if (previous.id !== target.id) {
      issue.status = target.id;
      this.log(issue, "moved", "status", previous.name, target.name);
      if (target.category === "done" && previous.category !== "done") {
        issue.resolved = isoNow(this.now());
        this.log(issue, "completed");
      } else if (target.category !== "done" && previous.category === "done") {
        issue.resolved = null;
        this.log(issue, "reopened");
      }
    } else {
      issue.updated = isoNow(this.now());
    }
    this.changed();
    return this.publicIssue(issue);
  },

  "issue/delete"({ issue_id }) {
    const issue = this.issue(issue_id);
    for (const attachment of issue.attachments) this.files.remove(attachment.id);
    this.issues.delete(issue.id);
    for (const other of this.issues.values()) if (other.parent === issue.id) other.parent = null;
    this.changed();
    return { deleted: issue.id };
  },

  "issue/comment"({ issue_id, text }) {
    const issue = this.issue(issue_id);
    if (!String(text || "").trim()) fail("invalid_format", "text is required");
    const comment = { id: this.id("com"), author: this.user.person, ts: isoNow(this.now()), text: text.trim() };
    issue.comments.push(comment);
    this.log(issue, "commented");
    this.changed();
    return { ...comment };
  },

  "issue/list"({ project_id = null, archived = false, query = "", limit = 100, offset = 0 }) {
    const needle = String(query).toLowerCase();
    const matches = [...this.issues.values()].filter(
      (i) => (!project_id || i.project_id === project_id) && i.archived === Boolean(archived) && (!needle || `${i.key} ${i.summary} ${i.description}`.toLowerCase().includes(needle)),
    );
    return { issues: matches.slice(offset, offset + limit).map((i) => this.publicIssue(i)), total: matches.length };
  },

  "quick_add/preview"({ text, project = null }) {
    const parsed = parseQuickAdd(text, {
      people: this.people,
      projectKeys: [...this.projects.values()].map((p) => p.key),
      today: parseDate(dateString(this.now())),
      me: this.user.person,
    });
    const target = this.findProject(project, parsed.project);
    return { ...parsed, project: target.key, suggestion: onlyMissing(this.suggest(parsed.summary), parsed) };
  },

  "quick_add"({ text, project = null, suggest = false }) {
    const { suggestion, ...parsed } = COMMANDS["quick_add/preview"].call(this, { text, project });
    const target = [...this.projects.values()].find((p) => p.key === parsed.project);
    const fields = { ...parsed, issue_type: parsed.type || "task", assignee: parsed.assignee, priority: parsed.priority || "medium" };
    if (suggest && suggestion) {
      if (suggestion.assignee) fields.assignee = suggestion.assignee;
      if (suggestion.labels.length) fields.labels = suggestion.labels;
      if (suggestion.priority) fields.priority = suggestion.priority;
      if (suggestion.due_in_days != null) fields.due = dateString(addDays(parseDate(dateString(this.now())), suggestion.due_in_days));
    }
    const issue = this.newIssue(target, fields, "ui");
    this.changed();
    return { issue: this.publicIssue(issue), parsed };
  },

  suggest({ text }) {
    if (!String(text || "").trim()) fail("invalid_format", "text is required");
    return this.suggest(text);
  },

  "checklist/add"({ issue_id, text }) {
    const issue = this.issue(issue_id);
    const clean = String(text || "").trim();
    if (!clean || clean.includes("\n")) fail("invalid_format", "text must be one non-empty line");
    if (clean.length > 200) fail("invalid_format", "text is too long");
    if (issue.checklist.length >= 100) fail("invalid_format", "A checklist holds at most 100 items");
    const before = this.progress(issue);
    const item = { id: this.id("chk"), text: clean, done: false };
    issue.checklist.push(item);
    this.log(issue, "updated", "checklist", before, this.progress(issue));
    this.changed();
    return { ...item };
  },

  "checklist/update"({ issue_id, item_id, ...fields }) {
    const issue = this.issue(issue_id);
    const item = issue.checklist.find((i) => i.id === item_id) || fail("not_found", `Checklist item ${item_id} not found`);
    const before = this.progress(issue);
    if ("text" in fields) {
      if (!String(fields.text).trim()) fail("invalid_format", "text is required");
      item.text = String(fields.text).trim().slice(0, 200);
    }
    if ("done" in fields) item.done = Boolean(fields.done);
    this.log(issue, "updated", "checklist", before, this.progress(issue));
    this.changed();
    return { ...item };
  },

  "checklist/remove"({ issue_id, item_id }) {
    const issue = this.issue(issue_id);
    if (!issue.checklist.some((i) => i.id === item_id)) fail("not_found", `Checklist item ${item_id} not found`);
    const before = this.progress(issue);
    issue.checklist = issue.checklist.filter((i) => i.id !== item_id);
    this.log(issue, "updated", "checklist", before, this.progress(issue));
    this.changed();
    return { deleted: item_id };
  },

  "checklist/reorder"({ issue_id, item_ids }) {
    const issue = this.issue(issue_id);
    const current = issue.checklist.map((i) => i.id).sort().join(",");
    if (!Array.isArray(item_ids) || [...item_ids].sort().join(",") !== current) fail("invalid_format", "item_ids must list every item exactly once");
    issue.checklist = item_ids.map((id) => issue.checklist.find((i) => i.id === id));
    issue.updated = isoNow(this.now());
    this.changed();
    return { ok: true };
  },

  "attachment/remove"({ issue_id, attachment_id }) {
    const issue = this.issue(issue_id);
    if (!issue.attachments.some((a) => a.id === attachment_id)) fail("not_found", `Attachment ${attachment_id} not found`);
    issue.attachments = issue.attachments.filter((a) => a.id !== attachment_id);
    this.files.remove(attachment_id);
    this.log(issue, "updated", "attachments", String(issue.attachments.length + 1), String(issue.attachments.length));
    this.changed();
    return { deleted: attachment_id };
  },

  "attachment/snapshot"({ issue_id, entity_id }) {
    if (!this.settings.attachments.enabled) fail("invalid_format", "Attachments are switched off");
    const issue = this.issue(issue_id);
    const camera = this.cameras.find((c) => c.entity_id === entity_id) || fail("not_found", `Camera ${entity_id} not found`);
    const stamp = isoNow(this.now()).slice(0, 16).replace(/[-:]/g, "").replace("T", "-");
    const bytes = demoPicture(camera.entity_id.length * 7 + issue.number);
    const attachment = this.addAttachment(issue, { name: `${entity_id.slice(7)}-${stamp}.png`, mime: "image/png", bytes, source: "camera" });
    this.changed();
    return this.publicAttachment(attachment);
  },

  "insights/get"() {
    return { features: { ...this.settings.learning }, suggestions: structuredClone(this.openSuggestions()), learned: this.learnedData() };
  },

  "insights/accept"({ suggestion_id }) {
    const suggestion = this.openSuggestions().find((s) => s.id === suggestion_id) || fail("not_found", `Suggestion ${suggestion_id} not found`);
    const result = { applied: true };
    if (suggestion.kind === "recurring") {
      const { project_id, ...fields } = suggestion.proposal;
      const record = this.recurringRecord(this.project(project_id), { ...fields, summary: fields.summary });
      record.id = this.id("rec");
      this.recurring.set(record.id, record);
      result.recurring_id = record.id;
    } else if (suggestion.kind === "health_ignore") {
      const issue = [...this.issues.values()].find((i) => i.dedupe_key === suggestion.proposal.key);
      if (issue && !issue.labels.includes("ignore")) {
        issue.labels.push("ignore");
        this.log(issue, "updated", "labels", null, issue.labels.join(", "));
      }
    }
    this.handled.add(suggestion.id);
    this.changed();
    return result;
  },

  "insights/dismiss"({ suggestion_id }) {
    const suggestion = this.openSuggestions().find((s) => s.id === suggestion_id) || fail("not_found", `Suggestion ${suggestion_id} not found`);
    this.handled.add(suggestion.id);
    this.changed();
    return { dismissed: suggestion.id };
  },

  "insights/forget"({ feature = null }) {
    if (feature !== null && !FEATURES.includes(feature)) fail("invalid_format", `Unknown feature ${feature}`);
    const forgotten = feature ? [feature] : [...FEATURES];
    for (const name of forgotten) this.forgotten.add(name);
    this.changed();
    return { forgotten };
  },

  "recurring/create"({ project_id, ...fields }) {
    const project = this.project(project_id);
    const record = this.recurringRecord(project, fields);
    record.id = this.id("rec");
    this.recurring.set(record.id, record);
    this.changed();
    return structuredClone(record);
  },

  "recurring/update"({ recurring_id, ...fields }) {
    const existing = this.recurring.get(recurring_id) || fail("not_found", `Recurring ${recurring_id} not found`);
    const merged = this.recurringRecord(this.project(existing.project_id), { ...existing, issue_type: existing.type, ...fields });
    Object.assign(existing, merged, { id: existing.id, last_issue_id: existing.last_issue_id, last_created: existing.last_created });
    this.changed();
    return structuredClone(existing);
  },

  "recurring/delete"({ recurring_id }) {
    if (!this.recurring.delete(recurring_id)) fail("not_found", `Recurring ${recurring_id} not found`);
    this.changed();
    return { deleted: recurring_id };
  },

  "recurring/run_now"({ recurring_id }) {
    const rec = this.recurring.get(recurring_id) || fail("not_found", `Recurring ${recurring_id} not found`);
    const last = rec.last_issue_id && this.issues.get(rec.last_issue_id);
    if (rec.skip_if_open && last && !last.archived && this.isOpen(last)) return { issue: null };
    const project = this.project(rec.project_id);
    const issue = this.newIssue(
      project,
      { summary: rec.summary, description: rec.description, issue_type: rec.type, priority: rec.priority, assignee: rec.assignee, labels: rec.labels, status: rec.status || undefined, due: rec.next_due, recurring_id: rec.id },
      "recurring",
    );
    rec.last_issue_id = issue.id;
    rec.last_created = isoNow(this.now());
    rec.next_due = nextOccurrence(rec.next_due, rec.repeat);
    this.changed();
    return { issue: this.publicIssue(issue) };
  },

  "health/scan"({ dry_run = false }) {
    const findings = [...this.issues.values()].filter((i) => i.source === "health" && this.isOpen(i)).map((i) => ({ key: i.key, summary: i.summary, priority: i.priority, detector: i.dedupe_key.split(":")[1] }));
    return { created: 0, reopened: 0, closed: 0, suppressed: 0, findings: dry_run ? findings : [] };
  },
};

Object.assign(MockBackend.prototype, {
  findProject(projectArg, keyFromText) {
    const all = [...this.projects.values()].filter((p) => !p.archived);
    const wanted = keyFromText || projectArg;
    const project = wanted ? all.find((p) => p.id === wanted || p.key === String(wanted).toUpperCase()) : all[0];
    return project || fail("not_found", "Project not found");
  },

  recurringRecord(project, fields) {
    const summary = String(fields.summary || "").trim();
    if (!summary) fail("invalid_format", "summary is required");
    const repeat = fields.repeat || {};
    if (!["day", "week", "month", "year"].includes(repeat.unit) || !(repeat.every >= 1)) fail("invalid_format", "repeat needs unit and every >= 1");
    if (!fields.next_due) fail("invalid_format", "next_due is required");
    return {
      id: fields.id || null, project_id: project.id, enabled: fields.enabled !== false, summary, description: fields.description || "",
      type: this.enumValue(fields.issue_type || fields.type || "task", TYPES, "issue_type"), priority: this.enumValue(fields.priority || "medium", PRIORITIES, "priority"),
      assignee: this.person(fields.assignee ?? null), labels: this.cleanLabels(fields.labels), status: fields.status || null, repeat: { ...repeat },
      next_due: fields.next_due, create_days_before: fields.create_days_before || 0, skip_if_open: fields.skip_if_open !== false,
      last_issue_id: fields.last_issue_id || null, last_created: fields.last_created || null,
    };
  },
});

// ---- demo data -------------------------------------------------------------------------------

function seedDemo(backend) {
  const today = parseDate(dateString(backend.now()));
  const due = (offset) => dateString(addDays(today, offset));
  const ago = (days, hours = 0) => isoNow(new Date(backend.now().getTime() - days * 86400000 - hours * 3600000));
  const me = "person.joachim";
  const pad2 = "person.padmaja";

  const create = (key, name, template, color, icon, extra = {}) => {
    const project = COMMANDS["project/create"].call(backend, { key, name, template, color, icon });
    return Object.assign(backend.projects.get(project.id), extra);
  };
  const home = create("HOME", "Home", "household", "#2f80ed", "mdi:home", { lead: me });
  const fix = create("FIX", "Smart home fixes", "household", "#8e24aa", "mdi:robot-outline", { default_assignee: me });
  const statusId = (project, name) => project.statuses.find((s) => s.name === name).id;

  const add = (project, statusName, fields) => {
    const issue = backend.newIssue(project, { ...fields, status: statusId(project, statusName), issue_type: fields.type }, fields.source || "ui");
    issue.created = ago(fields.age ?? 9);
    issue.updated = ago(fields.touched ?? 1, fields.hours ?? 0);
    if (fields.resolvedAgo != null) issue.resolved = ago(fields.resolvedAgo);
    issue.reporter = "reporter" in fields ? fields.reporter : fields.assignee === me ? pad2 : me;
    issue.activity = [{ ts: issue.created, actor: issue.reporter, kind: "created", field: null, from: null, to: null }];
    return issue;
  };

  const epic = add(home, "In progress", { type: "epic", summary: "Garden makeover", priority: "medium", assignee: me, labels: ["garden"], description: "Everything for the new look of the back garden before summer.", age: 30, touched: 0, hours: 2 });
  add(home, "Backlog", { summary: "Repaint the hallway", priority: "low", labels: ["kitchen"], age: 40 });
  add(home, "Backlog", { summary: "Replace the shed roof", priority: "medium", assignee: me, labels: ["garden"], age: 25 });
  add(home, "Backlog", { summary: "Sort and clear the loft", priority: "low", age: 60 });
  add(home, "Backlog", { type: "story", summary: "Research a robot lawn mower", priority: "low", labels: ["garden"], age: 18 });
  add(home, "Backlog", { summary: "Lay the new garden path", priority: "medium", labels: ["garden"], parent: epic.id, age: 12 });
  add(home, "To do", { summary: "Pay the electricity bill", priority: "high", assignee: pad2, labels: ["bills"], due: due(-3), age: 14, touched: 3 });
  add(home, "To do", { summary: "Book the car service", priority: "medium", assignee: me, labels: ["car"], due: due(1), age: 5 });
  const latch = add(home, "To do", { type: "bug", summary: "Fix the gate latch", priority: "high", labels: ["garden"], due: due(2), description: "The latch sticks when it is cold and the gate swings open in the wind.\nMaybe just needs new screws.", age: 4, touched: 0, hours: 5 });
  add(home, "To do", { summary: "Order new bin bags", priority: "lowest", age: 3 });
  add(home, "To do", { type: "story", summary: "Plan the weekend dinner party", priority: "medium", assignee: pad2, labels: ["kitchen"], due: due(6), age: 6 });
  add(home, "To do", { type: "bug", summary: "Bathroom light flickers", priority: "medium", assignee: me, age: 2 });
  add(home, "To do", { summary: "Plant the beech hedge", priority: "medium", labels: ["garden"], parent: epic.id, age: 8 });
  add(home, "In progress", { summary: "Build the raised vegetable beds", priority: "medium", assignee: me, labels: ["garden"], parent: epic.id, age: 10, touched: 0, hours: 1 });
  add(home, "In progress", { summary: "Clean the gutters", priority: "medium", assignee: pad2, labels: ["garden"], due: due(-1), age: 7 });
  add(home, "In progress", { summary: "Renew the home insurance", priority: "high", assignee: me, labels: ["bills"], due: due(4), age: 9 });
  add(home, "In progress", { summary: "Declutter the kitchen drawers", priority: "low", assignee: pad2, labels: ["kitchen"], age: 3 });
  add(home, "Done", { summary: "Service the boiler", priority: "high", assignee: me, age: 20, resolvedAgo: 2, touched: 2 });
  add(home, "Done", { summary: "Wash the windows", priority: "low", assignee: pad2, age: 15, resolvedAgo: 5, touched: 5 });
  add(home, "Done", { summary: "Buy compost", priority: "lowest", assignee: me, labels: ["garden"], parent: epic.id, age: 6, resolvedAgo: 1, touched: 1 });
  add(home, "Done", { summary: "Cancel the old gym membership", priority: "medium", assignee: pad2, age: 30, resolvedAgo: 12, touched: 12 });
  add(home, "Done", { summary: "Sharpen the lawnmower blades", priority: "low", assignee: me, labels: ["garden"], age: 11, resolvedAgo: 3, touched: 3 });
  // History the learning features can draw on (all resolved within the last 30 days).
  add(home, "Done", { summary: "Pay the water bill", priority: "high", assignee: pad2, labels: ["bills"], due: due(-14), age: 28, resolvedAgo: 15, touched: 15 });
  add(home, "Done", { summary: "Pay the gas bill", priority: "high", assignee: pad2, labels: ["bills"], due: due(-10), age: 24, resolvedAgo: 11, touched: 11 });
  add(home, "Done", { summary: "Order new bin bags", priority: "lowest", labels: ["chores"], age: 29, resolvedAgo: 26, touched: 26 });
  add(home, "Done", { summary: "Order bin bags", priority: "lowest", labels: ["chores"], age: 14, resolvedAgo: 12, touched: 12 });

  latch.comments.push(
    { id: backend.id("com"), author: pad2, ts: ago(3), text: "It was fine last summer, so I think it is the cold." },
    { id: backend.id("com"), author: me, ts: ago(0, 6), text: "I will pick up new screws on Saturday." },
  );
  latch.activity.push(
    { ts: ago(3), actor: pad2, kind: "commented", field: null, from: null, to: null },
    { ts: ago(1), actor: me, kind: "updated", field: "priority", from: "medium", to: "high" },
    { ts: ago(0, 6), actor: me, kind: "commented", field: null, from: null, to: null },
  );

  // Checklists and files.
  const checklist = (issue, items) => {
    issue.checklist = items.map(([text, done]) => ({ id: backend.id("chk"), text, done }));
  };
  const issueByKey = (key) => [...backend.issues.values()].find((i) => i.key === key);
  checklist(issueByKey("HOME-14"), [["Buy timber", true], ["Cut the boards", true], ["Assemble the frames", true], ["Fill with soil", false], ["Plant the seeds", false]]);
  checklist(latch, [["Buy new screws", false], ["Oil the hinge", false]]);
  checklist(issueByKey("HOME-11"), [["Write the guest list", true], ["Choose the menu", false], ["Order the wine", false], ["Set the table", false]]);
  const picture = (issue, name, seed, source = "upload") => backend.addAttachment(issue, { name, mime: "image/png", bytes: demoPicture(seed), thumb: demoPicture(seed, 120, 75), source });
  picture(latch, "latch-closeup.png", 3);
  picture(latch, "gate-from-the-street.png", 8);
  backend.addAttachment(latch, { name: "latch-manual.pdf", mime: "application/pdf", bytes: MINIMAL_PDF });
  backend.addAttachment(issueByKey("HOME-7"), { name: "invoice-november.pdf", mime: "application/pdf", bytes: MINIMAL_PDF });

  const health = (summary, priority, type, labels, id, extra = {}) =>
    add(fix, "To do", { summary, priority, type, labels: ["auto", ...labels], source: "health", assignee: me, reporter: null, age: 1, touched: 0, hours: 1, ...extra, dedupe_key: id });
  health("Battery low: Front door lock (12%)", "high", "task", ["battery", "security"], "health:battery:dev-lock");
  health("Offline: Hallway motion sensor", "medium", "bug", ["offline", "security"], "health:offline:dev-motion", { priority: "high" });
  health("Offline: Garden irrigation controller", "medium", "bug", ["offline"], "health:offline:dev-irrigation");
  health("Battery low: Bedroom thermostat (18%)", "medium", "task", ["battery"], "health:battery:dev-thermo", { due: due(5) });
  health("Repair needed: Zigbee coordinator firmware", "medium", "bug", [], "health:repair:zha:fw");
  health("Integration problem: Philips Hue (retrying setup)", "medium", "bug", ["offline"], "health:entry:hue", { assignee: null });
  add(fix, "Backlog", { summary: "Document the Zigbee network layout", priority: "low", type: "task", age: 20 });
  picture(issueByKey("FIX-2"), "front_door-20261122-2015.png", 21, "camera");

  const recurring = (project, fields) => {
    const params = { ...fields, summary: fields.summary };
    const rec = backend.recurringRecord(project, params);
    rec.id = backend.id("rec");
    backend.recurring.set(rec.id, rec);
  };
  const nextTuesday = dateString(addDays(today, (((1 - ((today.getDay() + 6) % 7)) + 7) % 7) || 7));
  recurring(home, { summary: "Put out the bins", assignee: pad2, labels: ["chores"], repeat: { every: 1, unit: "week", weekdays: [1] }, next_due: nextTuesday });
  recurring(home, { summary: "Clean the extractor filters", labels: ["kitchen"], repeat: { every: 1, unit: "month", day_of_month: 1 }, next_due: dateString(new Date(today.getFullYear(), today.getMonth() + 1, 1)), create_days_before: 3 });
  recurring(home, { summary: "Annual boiler service", priority: "high", assignee: me, labels: ["bills"], repeat: { every: 1, unit: "year" }, next_due: dateString(new Date(today.getFullYear() + 1, 8, 15)) });
  recurring(home, { summary: "Water the indoor plants", labels: ["chores"], enabled: false, repeat: { every: 3, unit: "day" }, next_due: due(1) });

  backend.suggestions = [
    {
      id: backend.id("sug"),
      kind: "recurring",
      title: "Make 'Order new bin bags' a recurring chore?",
      detail: "Created 4 times, about every 6 weeks",
      evidence: { count: 4, interval_days: 42 },
      proposal: { project_id: home.id, summary: "Order new bin bags", repeat: { every: 6, unit: "week" }, next_due: due(14), assignee: null, labels: ["chores"], priority: "lowest" },
    },
    {
      id: backend.id("sug"),
      kind: "health_ignore",
      title: "Stop reporting 'Offline: Garden irrigation controller'?",
      detail: "You closed this fault 3 times in the last 30 days and it came back each time",
      evidence: { reopened: 3 },
      proposal: { key: "health:offline:dev-irrigation", summary: "Offline: Garden irrigation controller" },
    },
  ];
}
