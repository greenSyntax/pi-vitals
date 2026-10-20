import { h, icon, clear, append } from "../dom.js";
import { ChartCard } from "../charts.js";
import { bytes, percent, uptime, severity, SEVERITY_LABEL, SEVERITY_ICON, SEVERITY_RANK } from "../format.js";

const RANGE_SECONDS = { "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800 };

const THROTTLE_NOW = {
  under_voltage: "Under-voltage: the power supply is too weak",
  freq_capped: "CPU frequency is capped",
  throttled: "CPU is being throttled",
  soft_temp_limit: "Soft temperature limit is active",
};
const THROTTLE_PAST = {
  under_voltage_occurred: "under-voltage",
  freq_capped_occurred: "frequency capping",
  throttled_occurred: "throttling",
  soft_temp_limit_occurred: "the soft temperature limit",
};

function rootPartition(live) {
  const parts = live?.storage?.partitions || [];
  return parts.find((p) => p.mountpoint === "/") || parts[0] || null;
}

/** Worst severity across the headline metrics, plus any live throttling. */
export function overallSeverity(live) {
  const t = live?.health?.throttling;
  let worst = t && (t.under_voltage || t.throttled || t.freq_capped || t.soft_temp_limit) ? "danger" : "na";
  const readings = [
    ["cpu", live?.system?.cpu?.percent],
    ["memory", live?.system?.memory?.percent],
    ["temperature", live?.health?.temperature_c],
    ["disk", rootPartition(live)?.percent],
  ];
  for (const [metric, value] of readings) {
    const sev = severity(metric, value);
    if (SEVERITY_RANK[sev] > SEVERITY_RANK[worst]) worst = sev;
  }
  return worst;
}

function chip(sev) {
  return h("span", { class: "chip", "data-sev": sev }, icon(SEVERITY_ICON[sev]), SEVERITY_LABEL[sev]);
}

function makeTile({ label, iconName, metric, unit }) {
  const value = h("div", { class: "tile-value" }, "–");
  const sub = h("p", { class: "tile-sub" }, " ");
  const fill = h("span");
  const meter = h("div", { class: "meter", role: "meter", "aria-label": label, "aria-valuemin": "0", "aria-valuemax": "100" }, fill);
  const top = h("div", { class: "tile-top" }, h("span", { class: "tile-label" }, icon(iconName), label));
  const el = h("article", { class: "tile", "data-sev": "na" }, top, value, meter, sub);

  return {
    el,
    set({ reading, text, subText, meterPct }) {
      const sev = severity(metric, reading);
      el.dataset.sev = sev;
      el.querySelector(".chip")?.remove();
      top.append(chip(sev));
      append(clear(value), [text ?? "–", reading != null && unit ? h("span", { class: "unit" }, unit) : null]);
      sub.textContent = subText || " ";
      const pct = meterPct ?? reading;
      fill.style.width = pct == null ? "0" : `${Math.min(100, Math.max(0, pct))}%`;
      if (pct == null) meter.removeAttribute("aria-valuenow");
      else meter.setAttribute("aria-valuenow", String(Math.round(pct)));
    },
  };
}

function kvRow(dt, dd) {
  return [h("dt", null, dt), h("dd", null, dd)];
}

export class Overview {
  constructor() {
    this.banner = h("div", { "aria-live": "polite" });
    this.tiles = {
      cpu: makeTile({ label: "CPU", iconName: "cpu", metric: "cpu", unit: "%" }),
      memory: makeTile({ label: "Memory", iconName: "memory-stick", metric: "memory", unit: "%" }),
      temperature: makeTile({ label: "Temperature", iconName: "thermometer", metric: "temperature", unit: "°C" }),
      disk: makeTile({ label: "Storage", iconName: "hard-drive", metric: "disk", unit: "%" }),
    };
    this.charts = {
      cpu: new ChartCard({ title: "CPU usage", iconName: "activity", unit: "%", scale: "percent" }),
      memory: new ChartCard({ title: "Memory usage", iconName: "memory-stick", unit: "%", scale: "percent" }),
      temperature: new ChartCard({ title: "Temperature", iconName: "thermometer", unit: "°C", decimals: 1, scale: "temperature" }),
      load: new ChartCard({ title: "Load average (1 min)", iconName: "gauge", decimals: 2, axisDecimals: 1, scale: "load", noun: "Load average" }),
    };
    this.cores = h("div", { class: "bars" });
    this.storage = h("div");
    this.system = h("dl", { class: "kv" });

    this.el = h(
      "div",
      { style: "display:contents" },
      this.banner,
      h("section", { class: "grid-tiles", "aria-label": "Current readings" }, ...Object.values(this.tiles).map((t) => t.el)),
      h("section", { class: "grid-charts", "aria-label": "History" }, ...Object.values(this.charts).map((c) => c.el)),
      h(
        "section",
        { class: "grid-3", "aria-label": "Details" },
        h("article", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, icon("cpu"), "Per-core usage")), this.cores),
        h("article", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, icon("hard-drive"), "Storage")), this.storage),
        h("article", { class: "card" }, h("div", { class: "card-head" }, h("h2", null, icon("server"), "System")), this.system),
      ),
    );
  }

  update(live) {
    const sys = live.system || {};
    const cpu = sys.cpu || {};
    const mem = sys.memory || {};
    const temp = live.health?.temperature_c ?? null;
    const root = rootPartition(live);

    this.tiles.cpu.set({
      reading: cpu.percent ?? null,
      text: cpu.percent == null ? null : cpu.percent.toFixed(0),
      subText: cpu.cores ? `${cpu.cores} cores${cpu.load_avg ? ` · load ${cpu.load_avg["1m"]}` : ""}` : sys.error,
    });
    this.tiles.memory.set({
      reading: mem.percent ?? null,
      text: mem.percent == null ? null : mem.percent.toFixed(0),
      subText: mem.total ? `${bytes(mem.used)} of ${bytes(mem.total)}` : sys.error,
    });
    this.tiles.temperature.set({
      reading: temp,
      text: temp == null ? null : temp.toFixed(1),
      subText: temp == null ? "Sensor not available on this device" : "CPU core",
      meterPct: temp == null ? null : (temp / 100) * 100,
    });
    this.tiles.disk.set({
      reading: root?.percent ?? null,
      text: root ? root.percent.toFixed(0) : null,
      subText: root ? `${bytes(root.used)} of ${bytes(root.total)} on ${root.mountpoint}` : live.storage?.error,
    });

    this.#renderBanner(live.health?.throttling);
    this.#renderCores(cpu.per_core_percent || []);
    this.#renderStorage(live.storage?.partitions || [], live.storage?.error);
    this.#renderSystem(sys);
  }

  #renderBanner(t) {
    clear(this.banner);
    if (!t) return;
    const now = Object.keys(THROTTLE_NOW).filter((k) => t[k]);
    const past = Object.keys(THROTTLE_PAST).filter((k) => t[k]);
    if (now.length) {
      this.banner.append(
        h("div", { class: "banner", "data-sev": "danger", role: "alert" }, icon("octagon-alert"), h("div", null, h("strong", null, "Power or thermal problem right now"), h("br"), now.map((k) => THROTTLE_NOW[k]).join(" · "))),
      );
    } else if (past.length) {
      this.banner.append(
        h("div", { class: "banner", "data-sev": "warn" }, icon("triangle-alert"), h("div", null, h("strong", null, "Problems since boot"), h("br"), `The Pi has seen ${past.map((k) => THROTTLE_PAST[k]).join(", ")}. Check the power supply and cooling.`)),
      );
    }
  }

  #renderCores(cores) {
    clear(this.cores);
    if (!cores.length) return this.cores.append(h("p", { class: "muted" }, "No data"));
    cores.forEach((pct, i) => {
      this.cores.append(
        h(
          "div",
          { class: "bar-row" },
          h("span", { class: "label" }, `Core ${i}`),
          h("div", { class: "meter", role: "meter", "aria-label": `Core ${i}`, "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(pct)) }, h("span", { style: `width:${Math.min(100, pct)}%` })),
          h("span", { class: "val" }, percent(pct)),
        ),
      );
    });
  }

  #renderStorage(parts, error) {
    clear(this.storage);
    if (!parts.length) return this.storage.append(h("p", { class: "muted" }, error || "No mounted volumes found"));
    for (const p of parts) {
      const sev = severity("disk", p.percent);
      this.storage.append(
        h(
          "div",
          { class: "part", "data-sev": sev },
          h("div", { class: "part-head" }, h("strong", null, p.mountpoint), h("span", { class: "part-sub" }, `${bytes(p.used)} of ${bytes(p.total)} · ${percent(p.percent)}`)),
          h("div", { class: "meter", role: "meter", "aria-label": `${p.mountpoint} usage`, "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(p.percent)) }, h("span", { style: `width:${Math.min(100, p.percent)}%` })),
          h("span", { class: "part-sub" }, `${p.device} · ${p.fstype}`),
        ),
      );
    }
  }

  #renderSystem(sys) {
    clear(this.system);
    const cpu = sys.cpu || {};
    const swap = sys.swap || {};
    const rows = [
      ["Hostname", sys.hostname ?? "–"],
      ["Uptime", uptime(sys.uptime_seconds)],
      ["Load (1 / 5 / 15 min)", cpu.load_avg ? `${cpu.load_avg["1m"]} / ${cpu.load_avg["5m"]} / ${cpu.load_avg["15m"]}` : "–"],
      ["CPU frequency", cpu.freq ? `${Math.round(cpu.freq.current_mhz)} MHz` : "–"],
      ["Swap", swap.total ? `${bytes(swap.used)} of ${bytes(swap.total)} (${percent(swap.percent)})` : "None"],
    ];
    for (const [dt, dd] of rows) this.system.append(...kvRow(dt, dd));
  }

  setHistory(res) {
    const seconds = RANGE_SECONDS[res.range];
    for (const [key, chart] of Object.entries(this.charts)) {
      chart.setData({ points: res.series[key] || [], bucket: res.bucket_seconds, since: res.since, until: res.since + seconds });
    }
  }

  setMode(mode) {
    Object.values(this.charts).forEach((c) => c.setMode(mode));
  }

  setLoading(on) {
    Object.values(this.charts).forEach((c) => c.setLoading(on));
  }

  rebuildCharts() {
    Object.values(this.charts).forEach((c) => c.rebuild());
  }
}
