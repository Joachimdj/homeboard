// User-level mutations: optimistic update, error toast, undo. Every function
// resolves to the server result, or null after the failure was shown to the user.

import { t } from "./i18n.js";
import { statusName } from "./indexes.js";
import { moveIssue, patchIssue, removeIssue, reorderStatuses } from "./optimistic.js";
import { overlay } from "./overlay.js";
import { followingId } from "./ranks.js";
import { store } from "./store.js";

function describeError(error) {
  if (error.code === "unauthorized") return t("error.unauthorized");
  return error.message || t("error.generic");
}

async function run(command, params, optimistic) {
  try {
    return await store.call(command, params, { optimistic });
  } catch (error) {
    overlay.toast({ kind: "error", message: describeError(error) });
    return null;
  }
}

function counted(issueId, { done, total }) {
  return (payload) => patchIssue(payload, issueId, { checklist_done: done, checklist_total: total });
}

/** Payload field `type` is called `issue_type` on the wire. */
function toWire(fields) {
  const { type, ...rest } = fields;
  return type === undefined ? rest : { ...rest, issue_type: type };
}

export const actions = {
  /** `before` = issue id to be placed in front of, null = end of the column. */
  async moveIssue(issueId, status, before = null, { undo = true } = {}) {
    const { index } = store.state;
    const issue = index?.issueById.get(issueId);
    if (!issue) return null;
    const column = (index.byProject.get(issue.project_id) || []).filter((i) => i.status === issue.status);
    const previous = { status: issue.status, before: followingId(column, issueId) };
    const result = await run(
      "homeboard/issue/move",
      { issue_id: issueId, status, before },
      (payload) => moveIssue(payload, issueId, status, before),
    );
    if (result && undo) {
      overlay.toast({
        message: t("toast.moved", { key: issue.key, status: statusName(store.state.index, status) }),
        action: { label: t("undo"), run: () => actions.moveIssue(issueId, previous.status, previous.before, { undo: false }) },
      });
    }
    return result;
  },

  createIssue(fields) {
    return run("homeboard/issue/create", toWire(fields));
  },

  updateIssue(issueId, fields) {
    const optimistic = fields.archived ? (p) => removeIssue(p, issueId) : (p) => patchIssue(p, issueId, fields);
    return run("homeboard/issue/update", { issue_id: issueId, ...toWire(fields) }, optimistic);
  },

  deleteIssue(issueId) {
    return run("homeboard/issue/delete", { issue_id: issueId }, (p) => removeIssue(p, issueId));
  },

  addComment(issueId, text) {
    return run("homeboard/issue/comment", { issue_id: issueId, text });
  },

  quickAdd(text, project, { suggest = false } = {}) {
    return run("homeboard/quick_add", { text, ...(project ? { project } : {}), ...(suggest ? { suggest: true } : {}) });
  },

  createProject(fields) {
    return run("homeboard/project/create", fields);
  },

  updateProject(projectId, fields) {
    return run("homeboard/project/update", { project_id: projectId, ...fields });
  },

  deleteProject(projectId) {
    return run("homeboard/project/delete", { project_id: projectId, confirm: true });
  },

  createStatus(projectId, fields) {
    return run("homeboard/status/create", { project_id: projectId, ...fields });
  },

  updateStatus(projectId, statusId, fields) {
    return run("homeboard/status/update", { project_id: projectId, status_id: statusId, ...fields });
  },

  reorderStatuses(projectId, statusIds) {
    return run("homeboard/status/reorder", { project_id: projectId, status_ids: statusIds }, (p) => reorderStatuses(p, projectId, statusIds));
  },

  deleteStatus(projectId, statusId, moveTo) {
    return run("homeboard/status/delete", { project_id: projectId, status_id: statusId, ...(moveTo ? { move_to: moveTo } : {}) });
  },

  createRecurring(projectId, fields) {
    return run("homeboard/recurring/create", { project_id: projectId, ...fields });
  },

  updateRecurring(recurringId, fields) {
    return run("homeboard/recurring/update", { recurring_id: recurringId, ...fields });
  },

  deleteRecurring(recurringId) {
    return run("homeboard/recurring/delete", { recurring_id: recurringId });
  },

  runRecurring(recurringId) {
    return run("homeboard/recurring/run_now", { recurring_id: recurringId });
  },

  // `counts` = { done, total } after the change, shown on the cards before the push arrives.
  addChecklistItem(issueId, text, counts) {
    return run("homeboard/checklist/add", { issue_id: issueId, text }, counts && counted(issueId, counts));
  },

  updateChecklistItem(issueId, itemId, fields, counts) {
    return run("homeboard/checklist/update", { issue_id: issueId, item_id: itemId, ...fields }, counts && counted(issueId, counts));
  },

  removeChecklistItem(issueId, itemId, counts) {
    return run("homeboard/checklist/remove", { issue_id: issueId, item_id: itemId }, counts && counted(issueId, counts));
  },

  reorderChecklist(issueId, itemIds) {
    return run("homeboard/checklist/reorder", { issue_id: issueId, item_ids: itemIds });
  },

  removeAttachment(issueId, attachmentId) {
    return run("homeboard/attachment/remove", { issue_id: issueId, attachment_id: attachmentId });
  },

  snapshot(issueId, entityId) {
    return run("homeboard/attachment/snapshot", { issue_id: issueId, entity_id: entityId });
  },

  acceptSuggestion(suggestionId) {
    return run("homeboard/insights/accept", { suggestion_id: suggestionId });
  },

  dismissSuggestion(suggestionId) {
    return run("homeboard/insights/dismiss", { suggestion_id: suggestionId });
  },

  forgetLearning(feature) {
    return run("homeboard/insights/forget", feature ? { feature } : {});
  },

  /** Plain reads: callers handle failures themselves. */
  getInsights() {
    return store.call("homeboard/insights/get");
  },

  suggest(text, project) {
    return store.call("homeboard/suggest", { text, ...(project ? { project } : {}) });
  },

  /**
   * AI Fix (PROTOCOL 11.2), administrators only. Plain calls: the AI Fix section shows the error itself
   * (inline and as a toast) because it also needs the code. `preview` and `analyze` can take up to a minute.
   */
  aiGet(issueId) {
    return store.call("homeboard/ai/get", { issue_id: issueId });
  },

  aiPreview(issueId, note) {
    return store.call("homeboard/ai/preview", { issue_id: issueId, ...(note ? { note } : {}) });
  },

  aiAnalyze(issueId, note) {
    return store.call("homeboard/ai/analyze", { issue_id: issueId, ...(note ? { note } : {}) });
  },

  aiApply(issueId, proposalId) {
    return store.call("homeboard/ai/apply", { issue_id: issueId, proposal_id: proposalId });
  },

  aiUndo(issueId, proposalId) {
    return store.call("homeboard/ai/undo", { issue_id: issueId, proposal_id: proposalId });
  },

  aiDismiss(issueId, proposalId) {
    return store.call("homeboard/ai/dismiss", { issue_id: issueId, proposal_id: proposalId });
  },

  /** Plain read (no toast on failure is wanted by callers that handle it themselves). */
  getIssue(issueId) {
    return store.call("homeboard/issue/get", { issue_id: issueId });
  },

  previewQuickAdd(text, project) {
    return store.call("homeboard/quick_add/preview", { text, ...(project ? { project } : {}) });
  },
};
