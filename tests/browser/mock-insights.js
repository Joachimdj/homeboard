// Demo implementation of the learning features (PROTOCOL 10.4 / 10.5): plain
// token-overlap statistics over the mock's own issues, plus canned health and
// rhythm data. Pure and DOM free.

const STOP = new Set(["the", "and", "for", "with", "new", "our", "til", "med", "den", "det", "ret", "køb"]);

const tokens = (text) => new Set(String(text).toLowerCase().split(/[^a-zæøå0-9]+/).filter((w) => w.length >= 3 && !STOP.has(w)));

function jaccard(a, b) {
  let shared = 0;
  for (const word of a) if (b.has(word)) shared += 1;
  return shared / (a.size + b.size - shared || 1);
}

function majority(values) {
  const counts = new Map();
  for (const value of values.filter(Boolean)) counts.set(value, (counts.get(value) || 0) + 1);
  const [best, count] = [...counts].sort((x, y) => y[1] - x[1])[0] || [null, 0];
  return count * 2 >= values.length ? best : null;
}

function median(numbers) {
  if (!numbers.length) return null;
  const sorted = [...numbers].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

const dayNumber = (iso) => Math.floor(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86400000);

/**
 * candidates: [{ key, summary, status, assignee, labels, priority, due, created }].
 * Returns the PROTOCOL 10.4 suggestion or null when nothing is similar enough.
 */
export function suggestFor(text, candidates) {
  const query = tokens(text);
  if (!query.size) return null;
  const similar = candidates
    .map((c) => ({ c, score: jaccard(query, tokens(c.summary)) }))
    .filter((entry) => entry.score >= 0.34)
    .sort((a, b) => b.score - a.score)
    .slice(0, 5)
    .map((entry) => entry.c);
  if (!similar.length) return null;

  const labelCounts = new Map();
  for (const c of similar) for (const label of c.labels) labelCounts.set(label, (labelCounts.get(label) || 0) + 1);
  const leadTimes = similar.filter((c) => c.due).map((c) => dayNumber(c.due) - dayNumber(c.created)).filter((n) => n >= 0);
  const n = similar.length;
  return {
    assignee: majority(similar.map((c) => c.assignee)),
    labels: [...labelCounts].filter(([, count]) => count * 2 >= n && count > 0).map(([label]) => label),
    priority: majority(similar.map((c) => c.priority)),
    due_in_days: median(leadTimes),
    similar: similar.slice(0, 3).map(({ key, summary, status }) => ({ key, summary, status })),
    evidence: `based on ${n} similar issue${n === 1 ? "" : "s"}`,
    confidence: Math.round(Math.min(1, 0.3 + 0.15 * n) * 100) / 100,
  };
}

/** Drop what the typed text already decided; null when nothing is left to suggest. */
export function onlyMissing(suggestion, parsed) {
  if (!suggestion) return null;
  const rest = {
    ...suggestion,
    assignee: parsed.assignee ? null : suggestion.assignee,
    labels: parsed.labels?.length ? [] : suggestion.labels,
    priority: parsed.priority ? null : suggestion.priority,
    due_in_days: parsed.due ? null : suggestion.due_in_days,
  };
  return rest.assignee || rest.labels.length || rest.priority || rest.due_in_days != null ? rest : null;
}

const round1 = (n) => Math.round(n * 10) / 10;

/** Learned numbers computed from the mock's own issues (people) plus canned type / label averages. */
export function workloadFrom(issues, isDone, people, now) {
  const result = { people: {}, types: { bug: 4.2, story: 6.5, task: 3.1 }, labels: { garden: 6, bills: 1.5, kitchen: 2.8, car: 4 } };
  for (const person of people) {
    const mine = issues.filter((i) => i.assignee === person.entity_id);
    const done = mine.filter((i) => isDone(i) && i.resolved);
    const recent = done.filter((i) => now - new Date(i.resolved).getTime() <= 30 * 86400000);
    const spans = done.map((i) => (new Date(i.resolved) - new Date(i.created)) / 86400000);
    result.people[person.entity_id] = {
      open: mine.filter((i) => !isDone(i)).length,
      done_30d: recent.length,
      avg_days: spans.length ? round1(spans.reduce((a, b) => a + b, 0) / spans.length) : null,
    };
  }
  return result;
}

export function defaultsFrom(issues) {
  const labels = new Map();
  const people = new Map();
  for (const issue of issues) {
    for (const label of issue.labels) labels.set(label, (labels.get(label) || 0) + 1);
    if (issue.assignee) people.set(issue.assignee, (people.get(issue.assignee) || 0) + 1);
  }
  return {
    issues_analysed: issues.length,
    top_labels: [...labels].sort((a, b) => b[1] - a[1]).slice(0, 6),
    people: [...people].map(([person, count]) => ({ person, issues: count })),
  };
}

/** 7 x 24 presence grid (Mon = 0) for demo person `variant`: 0 = never home, 1 = always home. */
export function rhythmGrid(variant) {
  return Array.from({ length: 7 }, (_, day) =>
    Array.from({ length: 24 }, (_, hour) => {
      const weekend = day >= 5;
      const night = hour < 6 || hour >= 22;
      const evening = hour >= 17;
      let value;
      if (variant === 0) value = night ? 0.97 : weekend ? (hour >= 10 && hour < 13 ? 0.45 : 0.8) : evening ? 0.85 - (hour === 17 ? 0.35 : 0) : hour < 8 ? 0.8 : 0.08;
      else value = night ? 0.98 : weekend ? 0.75 : hour < 8 ? 0.9 : hour < 15 ? 0.25 + (hour === 12 ? 0.2 : 0) : 0.7 + (hour >= 18 ? 0.2 : 0);
      const wobble = (((day * 31 + hour * 17 + variant * 7) % 9) - 4) / 100;
      return Math.round(Math.min(1, Math.max(0, value + wobble)) * 100) / 100;
    }),
  );
}

export const HEALTH_LEARNED = {
  tracked_sensors: 812,
  silent: [
    { entity_id: "sensor.garden_soil_moisture", normal_minutes: 15, silent_minutes: 190 },
    { entity_id: "sensor.hallway_motion_battery", normal_minutes: 60, silent_minutes: 1500 },
  ],
  flapping: [{ key: "health:offline:dev-irrigation", summary: "Offline: Garden irrigation controller", reopened: 3 }],
};
