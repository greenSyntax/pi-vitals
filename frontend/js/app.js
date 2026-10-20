import { h, icon, clear } from "./dom.js";
import { getJSON } from "./api.js";
import { clock, SEVERITY_ICON } from "./format.js";
import { currentTheme, toggleTheme } from "./theme.js";
import { Overview, overallSeverity } from "./views/overview.js";
import { PortsView } from "./views/ports.js";
import { NginxView } from "./views/nginx.js";

// Relative URLs so the app works at / and behind a sub-path proxy.
const API = {
  live: "api/live",
  history: (range) => `api/history?range=${range}`,
  ports: "api/ports",
  nginx: "api/nginx",
  nginxRaw: "api/nginx/raw",
};

const TABS = [
  ["overview", "Overview", "layout-dashboard"],
  ["ports", "Ports", "plug"],
  ["nginx", "Nginx", "server"],
];
const RANGES = ["1h", "6h", "24h", "7d"];
const LIVE_MS = 5000;
const HISTORY_MS = 30000;
const PORTS_MS = 15000;

const state = { tab: "overview", range: "1h", mode: "chart", online: true, updated: null };
const views = {
  overview: new Overview(),
  ports: new PortsView(),
  nginx: new NginxView(() => getJSON(API.nginxRaw)),
};

const main = document.getElementById("main");
const badge = document.getElementById("status-badge");
const themeBtn = document.getElementById("theme-btn");
const tabsNav = document.getElementById("tabs");

// ---------- chrome ----------

function setBadge(sev, label, iconName) {
  badge.dataset.sev = sev;
  clear(badge).append(icon(iconName || SEVERITY_ICON[sev]), label);
}

const BADGE_LABEL = { ok: "Healthy", warn: "Warning", danger: "Critical", na: "No data" };

function renderThemeButton() {
  clear(themeBtn).append(icon(currentTheme() === "dark" ? "sun" : "moon"));
  themeBtn.title = currentTheme() === "dark" ? "Switch to light theme" : "Switch to dark theme";
}

themeBtn.addEventListener("click", () => {
  toggleTheme();
  renderThemeButton();
  views.overview.rebuildCharts();
});

function renderTabs() {
  clear(tabsNav).append(
    ...TABS.map(([id, label, iconName]) => h("a", { class: "tab", href: `#/${id}`, "aria-current": id === state.tab ? "page" : null }, icon(iconName), label)),
  );
}

// ---------- toolbar: the one filter row ----------

const updatedEl = h("span", { class: "muted", role: "status" }, "Loading…");
const rangeSeg = h("div", { class: "seg", role: "group", "aria-label": "Time range" });
const modeSeg = h("div", { class: "seg", role: "group", "aria-label": "Chart or table view" });
const refreshBtn = h("button", { class: "btn", type: "button", onClick: () => refreshCurrent(true) }, icon("refresh-cw"), "Refresh");

for (const r of RANGES) {
  rangeSeg.append(h("button", { type: "button", "aria-pressed": String(r === state.range), dataset: { value: r }, onClick: () => setRange(r) }, r));
}
for (const [value, label, iconName] of [["chart", "Chart", "chart-line"], ["table", "Table", "table"]]) {
  modeSeg.append(h("button", { type: "button", "aria-pressed": String(value === state.mode), dataset: { value }, onClick: () => setMode(value) }, icon(iconName), label));
}
const chartControls = h("div", { class: "toolbar", style: "display:contents" }, rangeSeg, modeSeg);
const toolbar = h("div", { class: "toolbar" }, chartControls, h("span", { class: "spacer" }), updatedEl, refreshBtn);

function pressed(seg, value) {
  seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === value)));
}

function setRange(range) {
  state.range = range;
  pressed(rangeSeg, range);
  refreshHistory();
}

function setMode(mode) {
  state.mode = mode;
  pressed(modeSeg, mode);
  views.overview.setMode(mode);
}

function showUpdated() {
  if (!state.updated) return;
  updatedEl.textContent = state.online ? `Updated ${clock(state.updated)}` : `Offline · last update ${clock(state.updated)}`;
}

// ---------- data ----------

let historyRequest = 0;

async function refreshLive() {
  try {
    const live = await getJSON(API.live);
    state.online = true;
    main.classList.remove("is-stale");
    state.updated = live.timestamp;
    views.overview.update(live);
    const sev = overallSeverity(live);
    setBadge(sev, BADGE_LABEL[sev]);
  } catch {
    state.online = false;
    main.classList.add("is-stale"); // old readings must not look live
    setBadge("danger", "Offline", "circle-x");
  }
  showUpdated();
}

async function refreshHistory() {
  const id = ++historyRequest;
  views.overview.setLoading(true);
  try {
    const res = await getJSON(API.history(state.range));
    if (id !== historyRequest) return; // a newer range was picked meanwhile
    if (res.error) throw new Error(res.error);
    views.overview.setHistory(res);
    views.overview.setMode(state.mode);
  } catch {
    /* previous render stays; the header badge reports connectivity */
  } finally {
    if (id === historyRequest) views.overview.setLoading(false);
  }
}

async function refreshPorts() {
  try {
    views.ports.update(await getJSON(API.ports));
  } catch (err) {
    views.ports.update({ error: err.message });
  }
}

async function refreshNginx() {
  try {
    views.nginx.update(await getJSON(API.nginx));
  } catch (err) {
    views.nginx.update({ installed: true, error: "exec_failed", config_test: { ok: false, output: err.message }, servers: [], files: [] });
  }
}

function refreshCurrent(manual = false) {
  refreshLive();
  if (state.tab === "overview") refreshHistory();
  else if (state.tab === "ports") refreshPorts();
  else if (state.tab === "nginx" && manual) refreshNginx();
}

// ---------- routing & polling ----------

function route() {
  const id = (location.hash.match(/^#\/(\w+)/) || [])[1];
  state.tab = TABS.some(([t]) => t === id) ? id : "overview";
  renderTabs();
  chartControls.hidden = state.tab !== "overview";
  chartControls.style.display = state.tab === "overview" ? "contents" : "none";
  clear(main).append(toolbar, views[state.tab].el);
  document.title = `${TABS.find(([t]) => t === state.tab)[1]} · Pi-Vitals`;
  if (state.tab === "overview") refreshHistory();
  else if (state.tab === "ports") refreshPorts();
  else refreshNginx();
  showUpdated();
}

function every(ms, fn) {
  setInterval(() => {
    if (!document.hidden) fn();
  }, ms);
}

every(LIVE_MS, refreshLive);
every(HISTORY_MS, () => state.tab === "overview" && refreshHistory());
every(PORTS_MS, () => state.tab === "ports" && refreshPorts());
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refreshCurrent();
});
window.addEventListener("hashchange", route);

renderThemeButton();
setBadge("na", "Loading…", "activity");
route();
refreshLive();
