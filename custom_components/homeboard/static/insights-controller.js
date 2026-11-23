// Data and actions behind the Insights tab: load homeboard/insights/get, accept
// / dismiss suggestions, forget learned data (admin).

import { actions } from "./actions.js";
import { HabitsSection } from "./habits-section.js";
import { t } from "./i18n.js";
import { overlay } from "./overlay.js";
import { openProjectSettings } from "./project-dialog.js";

export class InsightsController {
  constructor({ requestRender, onSelectProject }) {
    this.requestRender = requestRender;
    this.onSelectProject = onSelectProject;
    this.data = null;
    this.loading = false;
    this.error = null;
    this.loadedOpen = null; // settings.insights_open when the data was fetched
    this.habits = new HabitsSection({ insights: this, requestRender }); // the inbox of automation ideas (0.4)
  }

  /** Fetch again now (after Create, Undo, Scan, ...). */
  refresh() {
    return this.load(this.loadedOpen);
  }

  /** Called on every render of the tab: fetch once, and again when the number of open suggestions changed. */
  ensure(openCount) {
    if (this.loading) return;
    if (!this.data && !this.error) this.load(openCount);
    else if (this.data && openCount !== this.loadedOpen) this.load(openCount);
  }

  async load(openCount) {
    this.loading = true;
    this.loadedOpen = openCount;
    try {
      this.data = await actions.getInsights();
      this.error = null;
    } catch (error) {
      this.error = error;
    }
    this.loading = false;
    this.requestRender();
  }

  retry() {
    this.error = null;
    this.requestRender();
  }

  async accept(suggestion) {
    const result = await actions.acceptSuggestion(suggestion.id);
    if (!result) return;
    if (suggestion.kind === "recurring") {
      const projectId = suggestion.proposal?.project_id;
      overlay.toast({
        message: t("insights.accepted_recurring"),
        action: projectId ? { label: t("insights.open_recurring"), run: () => openProjectSettings({ projectId, tab: "recurring", onSelectProject: this.onSelectProject }) } : null,
        timeout: 10000,
      });
    } else if (suggestion.kind === "health_ignore") {
      overlay.toast({ message: t("insights.accepted_ignore") });
    } else if (suggestion.kind === "digest_time") {
      overlay.toast({ message: t("insights.accepted_digest", { time: suggestion.proposal?.time || "" }) });
    } else {
      overlay.toast({ message: t("insights.accepted_other") });
    }
    await this.load(this.loadedOpen);
  }

  async dismiss(suggestion) {
    if (!(await actions.dismissSuggestion(suggestion.id))) return;
    overlay.toast({ message: t("insights.dismissed") });
    await this.load(this.loadedOpen);
  }

  /** feature = one of the five names, or null for everything. */
  async forget(feature) {
    const ok = await overlay.confirm({
      title: feature ? t("insights.forget_title", { feature: t(`insights.feature.${feature}`) }) : t("insights.forget_all"),
      message: feature === "habits" ? t("insights.forget_confirm_habits") : feature ? t("insights.forget_confirm", { feature: t(`insights.feature.${feature}`) }) : t("insights.forget_all_confirm"),
      confirmLabel: t("insights.forget"),
      danger: true,
    });
    if (!ok || !(await actions.forgetLearning(feature))) return;
    overlay.toast({ message: t("insights.forgotten") });
    await this.load(this.loadedOpen);
  }
}
