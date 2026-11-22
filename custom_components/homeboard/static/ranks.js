// Rank maths for drag-and-drop reordering. Ranks are sparse integers (gap 1000)
// inside one status; the server owns the real values, these are for the
// optimistic update that is replaced by the next push.

export const RANK_GAP = 1000;

/**
 * Rank for an issue placed in front of `beforeId` among `siblings`
 * (sorted by rank, without the moved issue). `beforeId` null = end of list.
 */
export function rankForInsert(siblings, beforeId) {
  if (!siblings.length) return RANK_GAP;
  const last = siblings[siblings.length - 1];
  if (beforeId == null) return last.rank + RANK_GAP;
  const index = siblings.findIndex((s) => s.id === beforeId);
  if (index === -1) return last.rank + RANK_GAP;
  const next = siblings[index];
  if (index === 0) return next.rank - RANK_GAP;
  const prev = siblings[index - 1];
  const gap = next.rank - prev.rank;
  return gap >= 2 ? prev.rank + Math.floor(gap / 2) : prev.rank + gap / 2;
}

/** Id of the issue that follows `issueId` in `list`, or null when it is last. */
export function followingId(list, issueId) {
  const index = list.findIndex((i) => i.id === issueId);
  if (index === -1 || index === list.length - 1) return null;
  return list[index + 1].id;
}

/** True when dropping `issueId` before `beforeId` would not change the order. */
export function isNoopMove(list, issueId, beforeId) {
  const index = list.findIndex((i) => i.id === issueId);
  if (index === -1) return false;
  if (beforeId === issueId) return true;
  return followingId(list, issueId) === (beforeId ?? null);
}
