// Attachments section of the issue dialog: gallery, upload (file picker, paste,
// drag and drop), camera snapshot, lightbox. Files travel over
// hass.fetchWithAuth("/api/homeboard/upload") (PROTOCOL 10.3); signed URLs in
// the detail expire after an hour, so a failing image triggers a refetch.

import { actions } from "./actions.js";
import { FILE_ACCEPT, cameraEntities, filesFromTransfer, formatSize, isImage, isPdf, uploadError, validateFile } from "./attachments-util.js";
import { icon, spinner } from "./components.js";
import { h } from "./dom.js";
import { t } from "./i18n.js";
import { dialogShell, overlay } from "./overlay.js";
import { store } from "./store.js";
import { cx } from "./util.js";

const URL_REFRESH_MIN_MS = 10000;

export class AttachmentsSection {
  constructor({ dialog }) {
    this.dialog = dialog;
    this.pending = []; // [{ id, label }] uploads and snapshots in flight
    this.counter = 0;
    this.dragging = false;
    this.lastRefresh = 0;
    this.input = null;
  }

  get settings() {
    return store.state.payload?.settings?.attachments || {};
  }

  /** Whether the section is shown at all (hidden when attachments are off, and in the new-issue form). */
  get enabled() {
    return !this.dialog.create && this.settings.enabled === true;
  }

  get items() {
    return this.dialog.detail?.attachments || [];
  }

  // ---- window level paste and drop ---------------------------------------------------

  bind() {
    window.addEventListener("paste", this.onPaste);
    window.addEventListener("dragenter", this.onDragOver);
    window.addEventListener("dragover", this.onDragOver);
    window.addEventListener("dragleave", this.onDragLeave);
    window.addEventListener("drop", this.onDrop);
  }

  unbind() {
    window.removeEventListener("paste", this.onPaste);
    window.removeEventListener("dragenter", this.onDragOver);
    window.removeEventListener("dragover", this.onDragOver);
    window.removeEventListener("dragleave", this.onDragLeave);
    window.removeEventListener("drop", this.onDrop);
  }

  get active() {
    return this.enabled && this.dialog.isTop();
  }

  onPaste = (event) => {
    if (!this.active) return;
    const files = filesFromTransfer(event.clipboardData);
    if (!files.length) return; // plain text pastes into the focused field as usual
    event.preventDefault();
    this.upload(files.map((file) => (file.name && file.name !== "image.png" ? file : new File([file], `pasted-image-${Date.now()}.${file.type.split("/")[1] || "png"}`, { type: file.type }))));
  };

  hasFiles(event) {
    return [...(event.dataTransfer?.types || [])].includes("Files");
  }

  onDragOver = (event) => {
    if (!this.active || !this.hasFiles(event)) return;
    event.preventDefault(); // allows the drop and stops the browser from opening the file
    if (!this.dragging) {
      this.dragging = true;
      this.dialog.update();
    }
  };

  onDragLeave = (event) => {
    if (this.dragging && !event.relatedTarget) {
      this.dragging = false;
      this.dialog.update();
    }
  };

  onDrop = (event) => {
    if (!this.active || !this.hasFiles(event)) return;
    event.preventDefault();
    this.dragging = false;
    this.upload(filesFromTransfer(event.dataTransfer));
  };

  // ---- uploading --------------------------------------------------------------------

  async upload(files) {
    await Promise.all(files.map((file) => this.uploadOne(file)));
    await this.dialog.loadDetail();
  }

  async uploadOne(file) {
    const { max_mb: maxMb } = this.settings;
    const check = validateFile(file, { maxMb });
    if (!check.ok) {
      this.fail(uploadError(check.reason, { maxMb }));
      return;
    }
    const entry = this.track(t("attachments.uploading", { name: file.name }));
    try {
      const body = new FormData();
      body.append("issue_id", this.dialog.issueId);
      body.append("file", file, file.name);
      const response = await store.hass.fetchWithAuth("/api/homeboard/upload", { method: "POST", body });
      if (!response.ok) this.fail(uploadError(response.status, { maxMb }));
    } catch {
      this.fail({ key: "attachments.error_network", vars: {} });
    } finally {
      this.untrack(entry);
    }
  }

  async snapshot(entityId) {
    const entry = this.track(t("attachments.snapshotting"));
    try {
      await actions.snapshot(this.dialog.issueId, entityId);
    } finally {
      this.untrack(entry);
    }
    await this.dialog.loadDetail();
  }

  fail({ key, vars }) {
    overlay.toast({ kind: "error", message: t(key, vars) });
  }

  track(label) {
    const entry = { id: ++this.counter, label };
    this.pending.push(entry);
    this.dialog.update();
    return entry;
  }

  untrack(entry) {
    this.pending = this.pending.filter((p) => p !== entry);
    this.dialog.update();
  }

  /** An image did not load: its signed URL probably expired. */
  imageFailed() {
    if (Date.now() - this.lastRefresh < URL_REFRESH_MIN_MS) return;
    this.lastRefresh = Date.now();
    this.dialog.loadDetail();
  }

  // ---- actions on one file -----------------------------------------------------------

  async remove(attachment) {
    const ok = await overlay.confirm({
      title: t("attachments.delete_title"),
      message: t("attachments.delete_confirm", { name: attachment.name }),
      confirmLabel: t("delete"),
      danger: true,
    });
    if (!ok) return false;
    const removed = await actions.removeAttachment(this.dialog.issueId, attachment.id);
    await this.dialog.loadDetail();
    return Boolean(removed);
  }

  chooseCamera(event) {
    const cameras = cameraEntities(store.hass?.states);
    overlay.menu({
      anchor: event.currentTarget,
      label: t("attachments.pick_camera"),
      items: cameras.length
        ? [{ heading: t("attachments.pick_camera") }, ...cameras.map((camera) => ({ label: camera.name, icon: "mdi:camera-outline", onSelect: () => this.snapshot(camera.entity_id) }))]
        : [{ label: t("attachments.no_camera"), icon: "mdi:camera-off-outline", disabled: true }],
    });
  }

  openLightbox(attachment) {
    const section = this;
    const images = () => section.items.filter(isImage);
    let index = Math.max(0, images().findIndex((a) => a.id === attachment.id));
    const step = (delta) => {
      const list = images();
      if (list.length) index = (index + delta + list.length) % list.length;
      entry.update();
    };
    const entry = overlay.dialog({
      size: "lightbox",
      label: () => images()[index]?.name || t("attachments.title"),
      render() {
        const list = images();
        const current = list[Math.min(index, list.length - 1)];
        if (!current) {
          queueMicrotask(() => entry.close());
          return dialogShell({ title: t("attachments.title"), onClose: () => entry.close(), body: null });
        }
        return dialogShell({
          title: current.name,
          onClose: () => entry.close(),
          body: h(
            "div.lightbox-body",
            { tabindex: "0", "data-autofocus": "", onkeydown: (event) => (event.key === "ArrowLeft" ? step(-1) : event.key === "ArrowRight" ? step(1) : null) },
            list.length > 1 ? h("button.icon-btn.big.lightbox-nav", { type: "button", "aria-label": t("attachments.previous"), onclick: () => step(-1) }, icon("mdi:chevron-left")) : null,
            h("img.lightbox-image", { key: current.id, src: current.url, alt: current.name, onerror: () => section.imageFailed() }),
            list.length > 1 ? h("button.icon-btn.big.lightbox-nav", { type: "button", "aria-label": t("attachments.next"), onclick: () => step(1) }, icon("mdi:chevron-right")) : null,
          ),
          footer: [
            h("span.muted.small.spacer", `${formatSize(current.size)}${list.length > 1 ? ` · ${index + 1}/${list.length}` : ""}`),
            h("button.btn.danger-outline", { type: "button", onclick: async () => { if (await section.remove(current)) index = Math.max(0, index - 1); entry.update(); } }, icon("mdi:delete-outline"), t("delete")),
            h("a.btn", { href: current.url, target: "_blank", rel: "noopener" }, icon("mdi:open-in-new"), t("attachments.open_original")),
          ],
        });
      },
    });
  }

  // ---- view ---------------------------------------------------------------------------

  tile(attachment) {
    const open = (child) =>
      isPdf(attachment)
        ? h("a.thumb-open", { href: attachment.url, target: "_blank", rel: "noopener", "aria-label": t("attachments.open", { name: attachment.name }) }, child)
        : h("button.thumb-open", { type: "button", "aria-label": t("attachments.open", { name: attachment.name }), onclick: () => this.openLightbox(attachment) }, child);
    return h(
      "figure.thumb",
      { key: attachment.id, class: cx(attachment.source === "camera" && "camera") },
      open(
        isImage(attachment) && (attachment.thumb_url || attachment.url)
          ? h("img", { src: attachment.thumb_url || attachment.url, alt: "", loading: "lazy", draggable: "false", onerror: () => this.imageFailed() })
          : h("span.file-icon", icon(isPdf(attachment) ? "mdi:file-pdf-box" : "mdi:file-outline")),
      ),
      h("figcaption", h("span.thumb-name", { title: attachment.name }, attachment.name), h("span.muted.small", formatSize(attachment.size))),
      attachment.source === "camera" ? h("span.thumb-badge", { title: t("attachments.from_camera") }, icon("mdi:camera-outline")) : null,
      h("button.icon-btn.small.thumb-delete", { type: "button", "aria-label": t("attachments.delete", { name: attachment.name }), title: t("attachments.delete", { name: attachment.name }), onclick: () => this.remove(attachment) }, icon("mdi:delete-outline")),
    );
  }

  render() {
    if (!this.enabled) return null;
    const items = this.items;
    const cameras = cameraEntities(store.hass?.states);
    return h(
      "section.section.attachments",
      { key: "attachments", class: this.dragging ? "dragging" : "" },
      h("div.section-head", h("h3", t("attachments.title")), items.length ? h("span.count", items.length) : null),
      h(
        "div.attach-actions",
        h("input", {
          key: "file-input",
          type: "file",
          hidden: true,
          multiple: true,
          accept: FILE_ACCEPT,
          ref: (element) => {
            this.input = element;
          },
          onchange: (event) => {
            const files = [...event.target.files];
            event.target.value = "";
            if (files.length) this.upload(files);
          },
        }),
        h("button.btn.small", { type: "button", onclick: () => this.input?.click() }, icon("mdi:paperclip"), t("attachments.add")),
        h("button.btn.small", { type: "button", disabled: !cameras.length, title: cameras.length ? "" : t("attachments.no_camera"), "aria-haspopup": "menu", onclick: (event) => this.chooseCamera(event) }, icon("mdi:camera-outline"), t("attachments.camera")),
      ),
      items.length || this.pending.length
        ? h(
            "div.gallery",
            items.map((attachment) => this.tile(attachment)),
            this.pending.map((entry) => h("figure.thumb.pending", { key: `pending-${entry.id}` }, h("span.file-icon", spinner(entry.label)), h("figcaption", h("span.thumb-name", entry.label)))),
          )
        : h("p.muted.small", t("attachments.empty")),
    );
  }
}
