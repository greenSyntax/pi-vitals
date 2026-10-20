import { h, icon, clear } from "../dom.js";

const EXPOSURE = {
  all_interfaces: { label: "All interfaces", sev: "warn", icon: "shield-alert", hint: "Reachable from the whole network" },
  specific: { label: "Single interface", sev: "ok", icon: "network", hint: "Bound to one network address" },
  local: { label: "Local only", sev: "ok", icon: "lock", hint: "Only reachable from this device" },
};

const COLUMNS = [
  ["port", "Port", true],
  ["protocol", "Protocol"],
  ["address", "Address"],
  ["exposure", "Exposure"],
  ["process", "Process"],
  ["pid", "PID", true],
];

function summaryTile(label, iconName, value, sub, sev) {
  return h(
    "article",
    { class: "tile", "data-sev": sev || "na" },
    h("div", { class: "tile-top" }, h("span", { class: "tile-label" }, icon(iconName), label)),
    h("div", { class: "tile-value" }, String(value)),
    h(
      "div",
      { class: "tile-foot" },
      h("p", { class: "tile-sub" }, sub),
      sev === "warn" ? h("span", { class: "status", "data-sev": "warn" }, icon("triangle-alert"), "Review") : null,
    ),
  );
}

export class PortsView {
  constructor() {
    this.data = null;
    this.sort = { key: "port", dir: 1 };
    this.filter = { exposure: "all", text: "" };

    this.summary = h("section", { class: "grid-tiles", "aria-label": "Port summary" });
    this.note = h("div");
    this.tableHost = h("div");

    const search = h("input", {
      class: "input",
      type: "search",
      placeholder: "Filter by port, process or address",
      "aria-label": "Filter listeners",
      onInput: (e) => {
        this.filter.text = e.target.value.trim().toLowerCase();
        this.#renderTable();
      },
    });
    this.seg = h("div", { class: "seg", role: "group", "aria-label": "Exposure filter" });
    for (const [value, label] of [["all", "All"], ["all_interfaces", "All interfaces"], ["specific", "Single interface"], ["local", "Local only"]]) {
      this.seg.append(
        h("button", { type: "button", "aria-pressed": String(value === "all"), dataset: { value }, onClick: () => this.#setExposure(value) }, label),
      );
    }

    this.el = h(
      "div",
      { style: "display:contents" },
      this.summary,
      this.note,
      h("article", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, icon("plug"), "Listening ports")), h("div", { class: "filters" }, this.seg, search), this.tableHost),
    );
  }

  #setExposure(value) {
    this.filter.exposure = value;
    this.seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.value === value)));
    this.#renderTable();
  }

  update(data) {
    this.data = data;
    clear(this.summary);
    clear(this.note);
    if (data.error) {
      this.note.append(h("div", { class: "banner", "data-sev": "danger", role: "alert" }, icon("octagon-alert"), h("div", null, h("strong", null, "Could not read ports"), data.error)));
      clear(this.tableHost);
      return;
    }
    const s = data.summary;
    this.summary.append(
      summaryTile("Listening", "plug", s.total, "TCP and UDP sockets"),
      summaryTile("All interfaces", "shield-alert", s.all_interfaces, s.all_interfaces ? "Reachable from the network: confirm each one is intended" : "Nothing exposed on every interface", s.all_interfaces ? "warn" : "ok"),
      summaryTile("Local only", "lock", s.local_only, "Loopback, not reachable from outside"),
    );
    if (data.partial) {
      this.note.append(
        h("div", { class: "banner", "data-sev": "warn" }, icon("info"), h("div", null, h("strong", null, "Partial view"), "Some processes are hidden by permissions, so their names and PIDs are missing.")),
      );
    }
    this.#renderTable();
  }

  #rows() {
    const { exposure, text } = this.filter;
    const rows = (this.data?.listeners || []).filter((l) => {
      if (exposure !== "all" && l.exposure !== exposure) return false;
      if (!text) return true;
      return [l.port, l.protocol, l.address, l.process, l.pid].some((v) => v != null && String(v).toLowerCase().includes(text));
    });
    const { key, dir } = this.sort;
    return rows.sort((a, b) => {
      const x = a[key];
      const y = b[key];
      if (x == null) return 1;
      if (y == null) return -1;
      return (typeof x === "number" ? x - y : String(x).localeCompare(String(y))) * dir || a.port - b.port;
    });
  }

  #renderTable() {
    clear(this.tableHost);
    const rows = this.#rows();
    if (!rows.length) return this.tableHost.append(h("p", { class: "empty" }, "No listeners match the filter"));

    const head = h("tr");
    for (const [key, label] of COLUMNS) {
      const active = this.sort.key === key;
      head.append(
        h(
          "th",
          { scope: "col", "aria-sort": active ? (this.sort.dir === 1 ? "ascending" : "descending") : "none" },
          h(
            "button",
            {
              type: "button",
              onClick: () => {
                this.sort = { key, dir: active ? -this.sort.dir : 1 };
                this.#renderTable();
              },
            },
            label,
            active ? icon("chevron-down", this.sort.dir === 1 ? "flip" : "") : null,
          ),
        ),
      );
    }
    this.tableHost.append(
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          { class: "tbl" },
          h("thead", null, head),
          h(
            "tbody",
            null,
            rows.map((l) => {
              const e = EXPOSURE[l.exposure] || EXPOSURE.specific;
              return h(
                "tr",
                null,
                h("td", { class: "num" }, String(l.port)),
                h("td", null, l.protocol.toUpperCase()),
                h("td", null, l.address),
                h("td", null, h("span", { class: "chip", "data-sev": e.sev, title: e.hint }, icon(e.icon), e.label)),
                h("td", null, l.process ?? "–"),
                h("td", { class: "num" }, l.pid ?? "–"),
              );
            }),
          ),
        ),
      ),
    );
  }
}
