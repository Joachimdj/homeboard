// All CSS as strings. Colours come from HA theme variables only, so the UI
// follows light / dark themes. Every shadow root adopts the parts it needs.

export const baseCss = `
:host {
  --hb-surface: var(--card-background-color, #fff);
  --hb-bg: var(--primary-background-color, #f4f4f4);
  --hb-field: var(--secondary-background-color, #eee);
  --hb-text: var(--primary-text-color, #212121);
  --hb-muted: var(--secondary-text-color, #6b6b6b);
  --hb-line: var(--divider-color, #dcdcdc);
  --hb-accent: var(--primary-color, #03a9f4);
  --hb-on-accent: var(--text-primary-color, #fff);
  --hb-error: var(--error-color, #db4437);
  --hb-warning: var(--warning-color, #f0a000);
  --hb-success: var(--success-color, #43a047);
  --hb-radius: var(--ha-card-border-radius, 12px);
  --hb-touch: 36px;
  color: var(--hb-text);
  font-family: var(--paper-font-body1_-_font-family, var(--ha-font-family-body, Roboto, system-ui, sans-serif));
  font-size: 14px;
  line-height: 1.4;
}
*, *::before, *::after { box-sizing: border-box; }
button, input, select, textarea { font: inherit; color: inherit; }
button { cursor: pointer; }
button:disabled { cursor: default; opacity: .45; }
ha-icon { --mdc-icon-size: 18px; display: inline-flex; flex: none; align-items: center; justify-content: center; }
:focus-visible { outline: 2px solid var(--hb-accent); outline-offset: 1px; }
.spacer { flex: 1 1 auto; }
.muted { color: var(--hb-muted); }
.small { font-size: 12px; }
.bad { color: var(--hb-error); }
.warn { color: var(--hb-warning); }
.key { color: var(--hb-muted); font-weight: 500; font-size: 12px; letter-spacing: .02em; white-space: nowrap; }
.count { display: inline-block; min-width: 20px; padding: 0 6px; border-radius: 10px; background: var(--hb-field); color: var(--hb-muted); font-size: 12px; font-weight: 500; text-align: center; }
.error-text { color: var(--hb-error); margin: 0; }

.btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: var(--hb-touch); padding: 0 14px; border: 1px solid var(--hb-line); border-radius: 18px; background: var(--hb-surface); font-weight: 500; white-space: nowrap; }
.btn:hover:not(:disabled) { background: var(--hb-field); }
.btn.primary { background: var(--hb-accent); border-color: var(--hb-accent); color: var(--hb-on-accent); }
.btn.primary:hover:not(:disabled) { background: color-mix(in srgb, var(--hb-accent) 85%, #000); }
.btn.primary.danger { background: var(--hb-error); border-color: var(--hb-error); }
.btn.danger-outline { color: var(--hb-error); border-color: var(--hb-error); background: transparent; }
.btn.ghost { border-color: transparent; background: transparent; color: var(--hb-muted); }
.btn.small { min-height: 30px; padding: 0 10px; font-size: 13px; }
.btn.big { min-height: 52px; padding: 0 22px; font-size: 17px; border-radius: 26px; }
.btn.on-bar { background: color-mix(in srgb, var(--app-header-text-color, #fff) 18%, transparent); border-color: transparent; color: inherit; }
.btn.on-bar:hover:not(:disabled) { background: color-mix(in srgb, var(--app-header-text-color, #fff) 28%, transparent); }

.icon-btn { display: inline-flex; align-items: center; justify-content: center; width: var(--hb-touch); height: var(--hb-touch); padding: 0; border: 0; border-radius: 50%; background: transparent; color: inherit; flex: none; }
.icon-btn:hover:not(:disabled) { background: color-mix(in srgb, currentColor 12%, transparent); }
.icon-btn.big { width: 52px; height: 52px; }
.icon-btn.big ha-icon { --mdc-icon-size: 28px; }

.input { width: 100%; min-height: var(--hb-touch); padding: 6px 10px; border: 1px solid var(--hb-line); border-radius: 8px; background: var(--hb-surface); outline-offset: 0; }
.input:focus { border-color: var(--hb-accent); outline: 1px solid var(--hb-accent); }
.input.small { min-height: 32px; padding: 3px 8px; width: auto; font-size: 13px; }
.input.narrow { width: 90px; }
textarea.input { resize: vertical; min-height: 60px; }
select.input { padding-right: 4px; }

.field { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.field.narrow { flex: none; width: 90px; }
.field-label { font-size: 12px; color: var(--hb-muted); font-weight: 500; }
.check { display: inline-flex; align-items: center; gap: 8px; min-height: 28px; cursor: pointer; }
.check input { width: 18px; height: 18px; accent-color: var(--hb-accent); }

.chip { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; padding: 1px 8px 1px 6px; border-radius: 12px; background: var(--hb-field); color: var(--hb-muted); font-size: 12px; font-weight: 500; white-space: nowrap; }
.chip ha-icon { --mdc-icon-size: 14px; }
.chip.plain { padding-left: 8px; }
.chip.due.overdue { background: color-mix(in srgb, var(--hb-error) 16%, transparent); color: var(--hb-error); }
.chip.due.soon { background: color-mix(in srgb, var(--hb-warning) 22%, transparent); color: color-mix(in srgb, var(--hb-warning) 70%, var(--hb-text)); }
.chip.auto { background: color-mix(in srgb, var(--hb-accent) 16%, transparent); color: var(--hb-accent); }
.chip.epic { background: color-mix(in srgb, #9b59d0 18%, transparent); color: #9b59d0; }
.label-chip { display: inline-flex; align-items: center; gap: 2px; padding: 0 8px; border-radius: 4px; border: 1px solid color-mix(in srgb, var(--label-color) 55%, transparent); background: color-mix(in srgb, var(--label-color) 14%, transparent); color: color-mix(in srgb, var(--label-color) 75%, var(--hb-text)); font-size: 12px; font-weight: 500; white-space: nowrap; }
.chip-x { display: inline-flex; margin: 0 -4px 0 2px; padding: 0; border: 0; background: transparent; color: inherit; border-radius: 50%; }
.chip-x ha-icon { --mdc-icon-size: 14px; }
.chip-toggle { display: inline-flex; align-items: center; gap: 4px; min-height: 30px; padding: 0 12px 0 8px; border: 1px solid var(--hb-line); border-radius: 15px; background: var(--hb-surface); font-size: 13px; white-space: nowrap; }
.chip-toggle ha-icon { --mdc-icon-size: 16px; }
.chip-toggle.on { background: color-mix(in srgb, var(--hb-accent) 18%, var(--hb-surface)); border-color: var(--hb-accent); color: var(--hb-accent); }
.chip-toggle:disabled { opacity: .4; }

.avatar { display: inline-flex; align-items: center; justify-content: center; flex: none; overflow: hidden; border-radius: 50%; color: #fff; font-weight: 600; user-select: none; }
.avatar img { width: 100%; height: 100%; object-fit: cover; }
.avatar.xs { width: 18px; height: 18px; font-size: 9px; }
.avatar.sm { width: 24px; height: 24px; font-size: 10px; }
.avatar.md { width: 32px; height: 32px; font-size: 12px; }
.avatar.empty { border: 1px dashed var(--hb-muted); color: var(--hb-muted); background: transparent; }
.avatar.empty ha-icon { --mdc-icon-size: 14px; }
.avatar.md.empty ha-icon { --mdc-icon-size: 18px; }
.type-icon, .prio-icon { --mdc-icon-size: 18px; }

.tabs { display: flex; gap: 2px; overflow-x: auto; scrollbar-width: none; }
.tab { display: inline-flex; align-items: center; gap: 6px; min-height: 40px; padding: 0 14px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--hb-muted); font-weight: 500; white-space: nowrap; }
.tab:hover { color: var(--hb-text); }
.tab.active { color: var(--hb-accent); border-bottom-color: var(--hb-accent); }
.tabs.small .tab { min-height: 34px; padding: 0 12px; }

.empty-state { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 48px 16px; text-align: center; color: var(--hb-muted); }
.empty-state ha-icon { --mdc-icon-size: 48px; opacity: .6; }
.empty-state strong { color: var(--hb-text); font-size: 16px; }
.loading, .card-message { padding: 32px 16px; text-align: center; color: var(--hb-muted); }
.card-message.bad { color: var(--hb-error); }
`;

export const boardCss = `
.board { position: relative; flex: 1 1 auto; min-height: 0; overflow: auto; overscroll-behavior: contain; -webkit-overflow-scrolling: touch; }
.grid { display: grid; grid-template-columns: repeat(var(--cols), minmax(250px, 1fr)); grid-auto-rows: auto; gap: 8px 10px; min-width: min-content; align-items: stretch; }
.grid.single { min-height: 100%; grid-template-rows: auto 1fr; }
.board.narrow .grid { grid-template-columns: repeat(var(--cols), 86%); min-width: 0; }
.board.narrow { scroll-snap-type: x mandatory; scroll-padding-inline: 0; }
.board.narrow.dragging { scroll-snap-type: none; }
.board.narrow .col-head, .board.narrow .cell { scroll-snap-align: start; }

.col-head { position: sticky; top: 0; z-index: 3; display: flex; align-items: center; gap: 8px; min-height: 40px; padding: 4px 6px 4px 12px; border-radius: 10px; background: var(--hb-surface); border: 1px solid var(--hb-line); border-top: 3px solid var(--hb-muted); font-weight: 600; }
.col-head[data-category="in_progress"] { border-top-color: var(--hb-accent); }
.col-head[data-category="done"] { border-top-color: var(--hb-success); }
.col-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-transform: uppercase; font-size: 12px; letter-spacing: .05em; color: var(--hb-muted); }
.wip { padding: 0 8px; border-radius: 10px; background: var(--hb-field); color: var(--hb-muted); font-size: 12px; font-weight: 600; }
.wip.over { background: var(--hb-warning); color: #000; }
.col-add { width: 30px; height: 30px; color: var(--hb-muted); }

.lane-head { grid-column: 1 / -1; display: flex; padding-top: 6px; }
.lane-toggle { position: sticky; left: 0; display: inline-flex; align-items: center; gap: 8px; padding: 2px 10px 2px 4px; border: 0; border-radius: 16px; background: transparent; font-weight: 600; }
.lane-toggle:hover { background: var(--hb-field); }

.cell { display: flex; flex-direction: column; gap: 8px; min-height: 96px; padding: 8px; border-radius: 10px; background: color-mix(in srgb, var(--hb-text) 5%, transparent); min-width: 0; }
.cell.drop-target { background: color-mix(in srgb, var(--hb-accent) 10%, transparent); outline: 2px dashed color-mix(in srgb, var(--hb-accent) 55%, transparent); outline-offset: -2px; }

.card { display: flex; flex-direction: column; gap: 6px; padding: 8px 10px; border: 1px solid var(--hb-line); border-radius: 10px; background: var(--hb-surface); box-shadow: 0 1px 2px rgba(0, 0, 0, .1); cursor: grab; user-select: none; -webkit-user-select: none; -webkit-touch-callout: none; min-width: 0; }
.card:hover { border-color: color-mix(in srgb, var(--hb-accent) 55%, var(--hb-line)); }
.card.is-source { opacity: .35; border-style: dashed; }
.card.is-overdue { border-left: 3px solid var(--hb-error); }
.card.done .card-summary { color: var(--hb-muted); }
.card-top { display: flex; align-items: center; gap: 6px; }
.card-menu { width: 28px; height: 28px; margin: -4px -6px -4px 0; color: var(--hb-muted); }
.card-summary { font-size: 14px; font-weight: 500; overflow-wrap: anywhere; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
.card-labels, .card-foot { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; }
.card-foot { min-height: 24px; }
.drop-marker { flex: none; height: 4px; margin: -3px 0; border-radius: 2px; background: var(--hb-accent); }
.drag-clone { position: fixed; left: 0; top: 0; z-index: 10; margin: 0; pointer-events: none; opacity: .96; cursor: grabbing; box-shadow: 0 12px 32px rgba(0, 0, 0, .38); will-change: transform; }

.list-grid { display: flex; flex-direction: column; gap: 14px; max-width: 960px; margin: 0 auto; }
.list-section .col-head { position: static; margin-bottom: 6px; }
.card.row { flex-direction: row; align-items: center; gap: 8px; padding: 6px 8px 6px 10px; }
.row-summary { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.row-labels { display: inline-flex; gap: 4px; }
.board.kiosk .card { padding: 12px 14px; gap: 8px; }
.board.kiosk .card-summary { font-size: 17px; }
.board.kiosk .card-menu { width: 40px; height: 40px; }
.board.kiosk .col-head { min-height: 52px; font-size: 16px; }
.board.kiosk .col-name { font-size: 14px; }
.board.kiosk .avatar.sm { width: 32px; height: 32px; font-size: 12px; }
`;

export const summaryCss = `
.summary { display: flex; flex-direction: column; gap: 16px; max-width: 1200px; margin: 0 auto; container: summary / inline-size; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr)); gap: 12px; }
.tile { display: flex; flex-direction: column; gap: 12px; padding: 14px; border: 1px solid var(--hb-line); border-radius: var(--hb-radius); background: var(--hb-surface); border-top: 4px solid var(--project-color, var(--hb-accent)); }
.tile-head { display: flex; align-items: center; gap: 8px; min-width: 0; }
.tile-title { display: inline-flex; align-items: baseline; gap: 8px; padding: 0; border: 0; background: transparent; font-size: 16px; text-align: left; min-width: 0; }
.tile-title:hover strong { text-decoration: underline; }
.stack { display: flex; height: 14px; overflow: hidden; border-radius: 7px; background: var(--hb-field); }
.seg { height: 100%; min-width: 4px; opacity: calc(1 - var(--shade, 0) * .28); background: var(--hb-muted); }
.seg[data-category="in_progress"], .swatch[data-category="in_progress"] { background: var(--hb-accent); }
.seg[data-category="done"], .swatch[data-category="done"] { background: var(--hb-success); }
.seg.empty { background: var(--hb-field); }
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 0; padding: 0; list-style: none; font-size: 12px; color: var(--hb-muted); }
.legend li { display: inline-flex; align-items: center; gap: 5px; }
.swatch { width: 10px; height: 10px; border-radius: 3px; background: var(--hb-muted); }
.legend strong { color: var(--hb-text); }
.metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(68px, 1fr)); gap: 8px; }
.metric { display: flex; flex-direction: column; align-items: flex-start; gap: 0; padding: 6px 10px; border: 1px solid var(--hb-line); border-radius: 10px; background: transparent; text-align: left; }
.metric:hover { background: var(--hb-field); }
.metric strong { font-size: 22px; font-weight: 600; line-height: 1.2; }
.metric span { font-size: 12px; color: var(--hb-muted); white-space: nowrap; }
.metric.bad strong { color: var(--hb-error); }
.metric.warn strong { color: var(--hb-warning); }
.tile.health { border-top-color: var(--hb-accent); }
.health-body { display: grid; grid-template-columns: auto 1fr; gap: 12px; align-items: stretch; }
.big-number { display: flex; flex-direction: column; justify-content: center; padding: 6px 18px 6px 12px; border: 1px solid var(--hb-line); border-radius: 10px; background: transparent; text-align: left; }
.big-number:hover { background: var(--hb-field); }
.big-number strong { font-size: 34px; line-height: 1.1; }
.big-number span { font-size: 12px; color: var(--hb-muted); }
.small-metrics { grid-template-columns: repeat(2, 1fr); }
.health-ok { display: flex; align-items: center; gap: 8px; margin: 0; color: var(--hb-success); }
.panel-section { padding: 14px; border: 1px solid var(--hb-line); border-radius: var(--hb-radius); background: var(--hb-surface); }
.panel-section h3 { display: flex; align-items: center; gap: 8px; margin: 0 0 10px; font-size: 15px; }
.attention { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 12px; }
.attention h3.bad { color: var(--hb-error); }
.attention h3.warn { color: color-mix(in srgb, var(--hb-warning) 70%, var(--hb-text)); }
.people { display: flex; flex-direction: column; }
.person-row { display: grid; grid-template-columns: 32px minmax(80px, 1fr) repeat(4, minmax(56px, auto)); align-items: center; gap: 12px; padding: 8px 6px; border: 0; border-bottom: 1px solid var(--hb-line); background: transparent; text-align: left; }
.person-row:last-child { border-bottom: 0; }
.person-row:hover { background: var(--hb-field); }
.person-name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.stat { display: flex; flex-direction: column; align-items: center; line-height: 1.2; }
.stat strong { font-size: 16px; }
.stat span { font-size: 11px; color: var(--hb-muted); }
.stat.bad strong { color: var(--hb-error); }
.issue-list { margin: 0; padding: 0; list-style: none; }
.issue-line { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 40px; padding: 4px 6px; border: 0; border-radius: 8px; background: transparent; text-align: left; }
.issue-line:hover { background: var(--hb-field); }
.line-summary { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-pad { padding: 4px 16px 16px; }
@container summary (max-width: 520px) {
  .tiles { grid-template-columns: minmax(0, 1fr); }
  .person-row { grid-template-columns: 32px minmax(0, 1fr) repeat(3, minmax(44px, auto)); gap: 8px; }
  .person-row .stat:nth-of-type(3) { display: none; }
  .attention { grid-template-columns: minmax(0, 1fr); }
}
`;

export const panelCss = `
:host { display: block; height: 100%; background: var(--hb-bg); }
.root, .app { height: 100%; }
.app { display: flex; flex-direction: column; min-height: 0; }
.topbar, .kiosk-bar { display: flex; align-items: center; flex: none; gap: 8px; min-height: 56px; padding: 0 12px; background: var(--app-header-background-color, var(--hb-accent)); color: var(--app-header-text-color, var(--hb-on-accent)); }
.title { margin: 0; font-size: 20px; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.project-select { width: auto; max-width: 240px; min-height: 36px; border-radius: 18px; }
.topbar .project-select, .kiosk-bar .project-select { background: color-mix(in srgb, var(--app-header-text-color, #fff) 16%, transparent); border-color: transparent; color: inherit; }
.topbar .project-select option, .kiosk-bar .project-select option { color: var(--hb-text); background: var(--hb-surface); }
.app > .tabs { flex: none; padding: 0 8px; background: var(--hb-surface); border-bottom: 1px solid var(--hb-line); }
.quickadd-bar { flex: none; padding: 10px 12px 0; }
.quickadd { display: flex; flex-direction: column; gap: 6px; }
.qa-row { display: flex; align-items: center; gap: 6px; }
.qa-input { flex: 1 1 auto; min-height: 42px; border-radius: 21px; padding: 0 16px; }
.qa-send { min-height: 42px; }
.mic.listening { background: var(--hb-error); color: #fff; animation: pulse 1.2s infinite; }
@keyframes pulse { 50% { opacity: .65; } }
.qa-preview { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 0 6px; }
.qa-summary { font-weight: 600; margin-right: 4px; }
.qa-chip { background: color-mix(in srgb, var(--chip-color, var(--hb-accent)) 16%, var(--hb-surface)); color: var(--hb-text); border: 1px solid color-mix(in srgb, var(--chip-color, var(--hb-accent)) 45%, transparent); }
.qa-chip ha-icon { color: var(--chip-color, var(--hb-muted)); }
.qa-chip.label { border-radius: 4px; }
.qa-chip.unresolved { background: transparent; border-style: dashed; color: var(--hb-muted); }
.filterbar { display: flex; flex: none; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding: 10px 12px 4px; }
.chips, .filter-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.filter-controls .search { width: 160px; }
.app.narrow .filterbar { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; }
.app.narrow .chips, .app.narrow .filter-controls { flex-wrap: nowrap; }
.app.narrow .btn-text { display: none; }
.app.narrow .with-select .title, .app.narrow .with-select .spacer { display: none; }
.app.narrow .project-select { flex: 1 1 0; min-width: 0; max-width: none; }
.app.narrow .qa-send-text { display: none; }
.app.narrow .qa-send { padding: 0 12px; }
.content { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 10px 12px 12px; display: flex; flex-direction: column; }
.content.tab-board, .content.tab-backlog { overflow: hidden; }
.content > .summary, .content > .list-view { width: 100%; }
.app.kiosk .content { padding: 12px; }
.kiosk-bar { min-height: 68px; }
.kiosk-bar .title { font-size: 26px; }

.list-view { overflow-x: auto; }
.list-table { width: 100%; max-width: 1200px; margin: 0 auto; border-collapse: separate; border-spacing: 0; background: var(--hb-surface); border: 1px solid var(--hb-line); border-radius: var(--hb-radius); overflow: hidden; }
.list-table th { text-align: left; font-size: 12px; color: var(--hb-muted); background: var(--hb-surface); border-bottom: 1px solid var(--hb-line); }
.sort { display: inline-flex; align-items: center; gap: 2px; width: 100%; padding: 10px 10px; border: 0; background: transparent; color: inherit; font-weight: 600; text-align: left; }
.list-table td { padding: 8px 10px; border-bottom: 1px solid var(--hb-line); vertical-align: middle; }
.list-table tbody tr { cursor: pointer; }
.list-table tbody tr:hover { background: var(--hb-field); }
.list-table tbody tr:last-child td { border-bottom: 0; }
.list-table tr.done td.col-summary { color: var(--hb-muted); }
.col-key { white-space: nowrap; }
.col-key ha-icon { margin-right: 6px; vertical-align: middle; }
.col-summary { width: 100%; font-weight: 500; }
.app.narrow .list-table thead { display: none; }
.app.narrow .list-table, .app.narrow .list-table tbody { display: block; }
.app.narrow .list-table tr { display: grid; grid-template-columns: auto 1fr auto auto; gap: 2px 10px; align-items: center; padding: 8px 10px; border-bottom: 1px solid var(--hb-line); }
.app.narrow .list-table td { padding: 0; border: 0; }
.app.narrow .list-table .col-summary { grid-column: 1 / -1; grid-row: 2; }
.app.narrow .list-table .col-status, .app.narrow .list-table .col-updated { display: none; }
`;

export const cardCss = `
:host { display: block; }
ha-card { display: block; overflow: hidden; }
ha-card.kiosk .col-head { min-height: 52px; }
.card-header { display: flex; align-items: center; gap: 8px; padding: 12px 8px 4px 16px; }
.card-title { font-size: 18px; font-weight: 500; }
ha-card > .board { padding: 4px 12px 12px; }
ha-card > .summary { padding: 8px 12px 12px; }
ha-card .tile { border-radius: 10px; }
ha-card .quickadd { padding: 0; }
`;

export const editorCss = `
.editor { display: flex; flex-direction: column; gap: 14px; padding: 4px 0; }
`;

export const overlayCss = `
:host { position: fixed; inset: 0; z-index: 9999; pointer-events: none; }
.layer, .floats { pointer-events: none; }
.backdrop { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; padding: 16px; background: rgba(0, 0, 0, .5); pointer-events: auto; animation: fade .12s ease-out; }
@keyframes fade { from { opacity: 0; } }
.dialog { display: flex; flex-direction: column; width: min(960px, 100%); max-height: min(100%, 860px); border-radius: var(--hb-radius); background: var(--hb-surface); box-shadow: 0 16px 48px rgba(0, 0, 0, .4); overflow: hidden; }
.dialog.small { width: min(440px, 100%); }
.dialog.tall { min-height: min(600px, 100%); }
.dialog-header { display: flex; align-items: center; gap: 10px; flex: none; min-height: 56px; padding: 6px 8px 6px 20px; border-bottom: 1px solid var(--hb-line); }
.dialog-title { margin: 0; font-size: 18px; font-weight: 500; white-space: nowrap; }
.dialog-body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 14px; }
.dialog-footer { display: flex; justify-content: flex-end; gap: 8px; flex: none; padding: 10px 20px; border-top: 1px solid var(--hb-line); }
.dialog-message { margin: 0; line-height: 1.5; }
.issue-ref { display: inline-flex; align-items: center; gap: 8px; }
.project-name { font-size: 13px; }

.issue-layout { display: grid; grid-template-columns: minmax(0, 1fr) 270px; gap: 20px; }
.issue-main, .issue-side, .issue-head, .issue-thread { display: flex; flex-direction: column; gap: 12px; min-width: 0; }
.issue-side { padding: 12px; border: 1px solid var(--hb-line); border-radius: 10px; align-self: start; }
.summary-input { min-height: 44px; font-size: 20px; font-weight: 600; border-color: transparent; background: transparent; padding-left: 6px; }
.summary-input:hover { background: var(--hb-field); }
.summary-input:focus { background: var(--hb-surface); }
.description { min-height: 110px; }
.section-title, .section h3 { margin: 4px 0 0; font-size: 13px; color: var(--hb-muted); text-transform: uppercase; letter-spacing: .05em; }
.hint { display: flex; align-items: center; gap: 8px; margin: 0; padding: 8px 12px; border-radius: 10px; background: color-mix(in srgb, var(--hb-accent) 12%, transparent); font-size: 13px; }
.hint ha-icon { color: var(--hb-accent); }
.meta { display: grid; grid-template-columns: auto 1fr; gap: 4px 10px; margin: 4px 0 0; font-size: 12px; }
.meta dt { color: var(--hb-muted); }
.meta dd { margin: 0; }
.labels-edit { display: flex; flex-wrap: wrap; gap: 4px; }
.labels-edit.big { gap: 8px; margin-bottom: 8px; }
.due-edit { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.due-edit .input { min-width: 0; }
.due-edit input[type="date"] { flex: 1 1 130px; width: auto; }
.due-edit input[type="time"] { width: 104px; flex: none; }
.child-list { margin: 6px 0 0; padding: 0; list-style: none; }
.child { display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px; border: 0; border-radius: 8px; background: transparent; text-align: left; }
.child:hover { background: var(--hb-field); }
.child-summary { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.thread { display: flex; flex-direction: column; gap: 14px; }
.comment, .comment-new { display: flex; gap: 10px; align-items: flex-start; }
.comment-body, .comment-new-body { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.comment-new-body { align-items: flex-start; }
.comment-head { display: flex; gap: 8px; align-items: baseline; }
.comment-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.activity { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; font-size: 13px; }

.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.form-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
.static-value { min-height: var(--hb-touch); display: flex; align-items: center; font-weight: 600; letter-spacing: .06em; }
.colors { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.swatch { width: 28px; height: 28px; border: 2px solid transparent; border-radius: 50%; }
.swatch.selected { border-color: var(--hb-text); box-shadow: 0 0 0 2px var(--hb-surface) inset; }
.color-input { width: 36px; height: 30px; padding: 0; border: 1px solid var(--hb-line); border-radius: 8px; background: transparent; }
.danger-zone { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; margin-top: 8px; padding-top: 14px; border-top: 1px solid var(--hb-line); }
.settings-body { display: flex; flex-direction: column; gap: 14px; padding-top: 6px; }
.status-list, .recurring-list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 8px; }
.status-row { display: grid; grid-template-columns: auto minmax(120px, 1fr) 130px 84px auto auto; align-items: center; gap: 8px; padding: 6px 8px; border: 1px solid var(--hb-line); border-radius: 10px; }
.status-order { display: flex; }
.status-order .icon-btn { width: 28px; height: 28px; }
.add-status { display: flex; flex-wrap: wrap; gap: 8px; }
.add-status .input:first-child { flex: 1 1 180px; width: auto; }
.add-status select.input { width: auto; }
.recurring-item { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border: 1px solid var(--hb-line); border-radius: 10px; }
.recurring-item.disabled { opacity: .6; }
.recurring-main { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; }
.switch input { width: 36px; height: 20px; accent-color: var(--hb-accent); }
.repeat-box { display: flex; flex-direction: column; gap: 10px; padding: 10px 12px; border: 1px solid var(--hb-line); border-radius: 10px; margin: 0; }
.repeat-box legend { padding: 0 6px; font-size: 12px; color: var(--hb-muted); font-weight: 500; }
.repeat-preview { display: flex; align-items: center; gap: 8px; margin: 0; font-weight: 500; }
.inline { display: flex; align-items: flex-end; flex-wrap: wrap; gap: 10px; }
.weekdays { display: flex; flex-wrap: wrap; gap: 6px; }

.menu-backdrop { position: fixed; inset: 0; pointer-events: auto; }
.menu { position: fixed; display: flex; flex-direction: column; min-width: 200px; max-width: calc(100vw - 16px); padding: 6px 0; overflow: auto; border-radius: 10px; background: var(--hb-surface); box-shadow: 0 8px 28px rgba(0, 0, 0, .35); border: 1px solid var(--hb-line); }
.menu-item { display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 0 16px 0 12px; border: 0; background: transparent; text-align: left; }
.menu-item:hover, .menu-item:focus-visible { background: var(--hb-field); outline: none; }
.menu-item.selected { color: var(--hb-accent); font-weight: 600; }
.menu-item ha-icon { width: 20px; }
.menu-sep { height: 1px; margin: 4px 0; background: var(--hb-line); }
.menu-heading { padding: 6px 16px; font-size: 12px; color: var(--hb-muted); text-transform: uppercase; letter-spacing: .05em; }
.toasts { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; gap: 8px; width: max-content; max-width: calc(100vw - 24px); pointer-events: none; }
.toast { display: flex; align-items: center; gap: 12px; padding: 6px 6px 6px 16px; border-radius: 10px; background: #323232; color: #fff; box-shadow: 0 4px 16px rgba(0, 0, 0, .4); pointer-events: auto; animation: rise .16s ease-out; }
.toast.error { background: var(--hb-error); }
.toast-action { min-height: 32px; padding: 0 12px; border: 0; border-radius: 16px; background: rgba(255, 255, 255, .16); color: #fff; font-weight: 600; }
.toast-close { width: 30px; height: 30px; color: #fff; }
@keyframes rise { from { opacity: 0; transform: translateY(8px); } }

@media (max-width: 720px) {
  .backdrop { padding: 0; align-items: flex-end; }
  .dialog { width: 100%; max-height: 100%; height: 100%; border-radius: 0; }
  .dialog.small { height: auto; border-radius: var(--hb-radius) var(--hb-radius) 0 0; }
  .issue-layout { grid-template-columns: minmax(0, 1fr); gap: 14px; }
  .issue-main { display: contents; }
  .issue-side { order: 1; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 12px; }
  .issue-side > .wide { grid-column: 1 / -1; }
  .issue-thread { order: 2; }
  .status-row { grid-template-columns: auto 1fr auto; }
  .status-row .status-category, .status-row .status-wip, .status-row .status-backlog { grid-column: 2 / -1; }
  .dialog-body { padding: 14px 14px; }
}
`;
