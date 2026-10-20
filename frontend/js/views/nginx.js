import { h, icon, clear } from "../dom.js";

const ERRORS = {
  not_installed: ["info", "na", "Nginx is not installed on this device", "Nothing to inspect here."],
  permission_denied: ["octagon-alert", "danger", "Pi Vitals is not allowed to read the Nginx config", "Run the deploy script, which installs a narrow sudo rule, and set PIVITALS_NGINX_USE_SUDO=1."],
  sudo_not_permitted: ["octagon-alert", "danger", "The sudo rule for Nginx is missing", "Install deploy/sudoers-pi-vitals, or unset PIVITALS_NGINX_USE_SUDO."],
  timeout: ["triangle-alert", "warn", "Nginx took too long to answer", "The config could not be read in time."],
  exec_failed: ["octagon-alert", "danger", "Could not run Nginx", "The binary exists but failed to start."],
};

function statusTile(label, iconName, value, sub, sev) {
  return h(
    "article",
    { class: "tile", "data-sev": sev },
    h("div", { class: "tile-top" }, h("span", { class: "tile-label" }, icon(iconName), label)),
    h("div", { class: "tile-value", style: "font-size:24px" }, value),
    h("p", { class: "tile-sub" }, sub || " "),
  );
}

function serverCard(s) {
  const names = s.server_names.length ? s.server_names.join(" ") : "(no server_name)";
  return h(
    "div",
    { class: "server" },
    h("h3", null, names),
    h(
      "div",
      { class: "chips" },
      s.listen.map((l) => h("span", { class: "chip", "data-sev": l.ssl ? "ok" : "na" }, icon(l.ssl ? "lock" : "lock-open"), l.raw)),
      s.context === "stream" ? h("span", { class: "chip", "data-sev": "na" }, "stream") : null,
    ),
    h(
      "dl",
      { class: "kv" },
      s.root ? [h("dt", null, "root"), h("dd", null, h("code", null, s.root))] : null,
      s.return ? [h("dt", null, "return"), h("dd", null, h("code", null, s.return))] : null,
      s.source ? [h("dt", null, "defined in"), h("dd", null, h("code", null, s.source))] : null,
    ),
    s.locations.length
      ? h(
          "div",
          { class: "loc-list" },
          s.locations.map((l) => {
            const target = l.proxy_pass ? `proxy → ${l.proxy_pass}` : l.alias ? `alias ${l.alias}` : l.root ? `root ${l.root}` : l.return ? `return ${l.return}` : "";
            return h("div", { class: "loc" }, h("code", null, l.path), h("span", { class: "muted" }, target));
          }),
        )
      : null,
  );
}

export class NginxView {
  constructor(fetchRaw) {
    this.fetchRaw = fetchRaw;
    this.status = h("section", { class: "grid-tiles", "aria-label": "Nginx status" });
    this.problem = h("div");
    this.servers = h("div");
    this.pre = h("pre", { class: "raw", tabindex: "0", "aria-label": "Nginx configuration" }, "Loading…");
    this.loadedRaw = false;

    this.details = h(
      "details",
      { onToggle: () => this.#onToggle() },
      h("summary", null, icon("file-text"), "Effective configuration (nginx -T, secrets redacted)", icon("chevron-down")),
      this.pre,
    );

    this.el = h(
      "div",
      { style: "display:contents" },
      this.status,
      this.problem,
      h("article", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, icon("server"), "Server blocks")), this.servers),
      h("article", { class: "card" }, this.details),
    );
  }

  async #onToggle() {
    if (!this.details.open || this.loadedRaw) return;
    try {
      const res = await this.fetchRaw();
      this.pre.textContent = res.raw ?? (res.error ? `Unavailable: ${res.error}` : "No configuration available");
      this.loadedRaw = !!res.raw;
    } catch (err) {
      this.pre.textContent = `Could not load: ${err.message}`;
    }
  }

  update(data) {
    clear(this.status);
    clear(this.problem);
    clear(this.servers);
    this.loadedRaw = false;
    if (this.details.open) this.#onToggle();

    if (!data.installed) {
      const [ic, sev, title, body] = ERRORS[data.error] || ["info", "na", data.error, ""];
      this.status.append(statusTile("Nginx", "server", "Not installed", null, "na"));
      this.problem.append(h("div", { class: "banner", "data-sev": sev }, icon(ic), h("div", null, h("strong", null, title), h("br"), body)));
      this.servers.append(h("p", { class: "empty" }, "No server blocks to show"));
      return;
    }
    if (data.error && ERRORS[data.error]) {
      const [ic, sev, title, body] = ERRORS[data.error];
      this.problem.append(h("div", { class: "banner", "data-sev": sev, role: "alert" }, icon(ic), h("div", null, h("strong", null, title), h("br"), body)));
    }

    const test = data.config_test || {};
    this.status.append(
      statusTile("Service", "activity", data.running ? "Running" : "Stopped", data.version ? `nginx ${data.version}` : null, data.running ? "ok" : "danger"),
      statusTile("Config test", test.ok ? "circle-check" : "circle-x", test.ok ? "Valid" : "Failed", test.output ? test.output.split("\n").pop() : null, test.ok ? "ok" : "danger"),
      statusTile("Server blocks", "globe", String((data.servers || []).length), `${(data.files || []).length} config files read`, "na"),
    );

    if (data.parse_errors?.length) {
      this.problem.append(
        h("div", { class: "banner", "data-sev": "warn" }, icon("triangle-alert"), h("div", null, h("strong", null, "Some files could not be parsed"), h("br"), data.parse_errors.map((e) => `${e.file}: ${e.error}`).join(" · "))),
      );
    }
    if (!test.ok && test.output && data.error !== "permission_denied") {
      this.problem.append(h("pre", { class: "raw" }, test.output));
    }

    const list = data.servers || [];
    if (!list.length) this.servers.append(h("p", { class: "empty" }, "No server blocks found"));
    else list.forEach((s) => this.servers.append(serverCard(s)));
  }
}
