import { h, icon, clear } from "./dom.js";
import { dateTime } from "./format.js";

const HEIGHT = 190;

function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// ---- y-scale policies: clean numbers, no fake precision ----

const NICE_PERCENT = [10, 25, 50, 75, 100];

const Y_RANGES = {
  percent(max) {
    const target = (max ?? 0) * 1.1;
    return [0, NICE_PERCENT.find((n) => n >= target) ?? 100];
  },
  temperature(max, min) {
    if (max == null) return [0, 100];
    return [Math.floor((min - 3) / 5) * 5, Math.ceil((max + 3) / 5) * 5];
  },
  load(max) {
    return [0, Math.max(1, Math.ceil((max ?? 0) * 1.2 * 10) / 10)];
  },
};

/** Insert nulls where samples are missing (app was off) so the line breaks instead of lying. */
function withGaps(points, bucket) {
  const xs = [];
  const ys = [];
  points.forEach(([t, v], i) => {
    if (i > 0 && t - points[i - 1][0] > bucket * 2.5) {
      xs.push(points[i - 1][0] + bucket);
      ys.push(null);
    }
    xs.push(t);
    ys.push(v);
  });
  return [xs, ys];
}

export class ChartCard {
  constructor({ title, iconName, unit = "", decimals = 0, axisDecimals = 0, scale = "percent", noun }) {
    this.cfg = { title, unit, decimals, axisDecimals, scale, noun: noun || title };
    this.mode = "chart";
    this.points = [];
    this.plot = null;
    this.window = { since: 0, until: 0, bucket: 1 };

    this.nowEl = h("span", { class: "now" }, "Latest", h("strong", null, "–"));
    this.body = h("div", { class: "chart-body" });
    this.el = h(
      "article",
      { class: "card" },
      h("div", { class: "card-head" }, h("h2", null, icon(iconName), title), this.nowEl),
      this.body,
    );

    this.resizer = new ResizeObserver(() => this.#resize());
    this.resizer.observe(this.body);
  }

  fmt(v) {
    return v == null ? "–" : `${v.toFixed(this.cfg.decimals)}${this.cfg.unit}`;
  }

  setLoading(on) {
    this.body.classList.toggle("is-loading", on);
  }

  setMode(mode) {
    this.mode = mode;
    this.render();
  }

  setData({ points, bucket, since, until }) {
    this.points = points;
    this.window = { since, until, bucket };
    const last = [...points].reverse().find((p) => p[1] != null);
    this.nowEl.lastChild.textContent = this.fmt(last ? last[1] : null);
    this.render();
  }

  rebuild() {
    this.render();
  }

  render() {
    this.#destroyPlot();
    clear(this.body);
    this.body.removeAttribute("tabindex");
    this.body.removeAttribute("role");
    this.body.removeAttribute("aria-label");

    const hasData = this.points.some((p) => p[1] != null);
    if (!hasData) {
      this.body.append(
        h("div", { class: "chart-empty" }, h("div", null, icon("info"), " No data for this range yet"), h("div", null, "It fills in as samples are collected.")),
      );
      return;
    }
    if (this.mode === "table") this.#renderTable();
    else this.#renderPlot();
  }

  #renderTable() {
    const rows = [...this.points].reverse().filter((p) => p[1] != null);
    this.body.append(
      h(
        "div",
        { class: "table-wrap scroll-table", tabindex: "0", role: "region", "aria-label": `${this.cfg.noun} values` },
        h(
          "table",
          { class: "tbl" },
          h("thead", null, h("tr", null, h("th", { scope: "col" }, "Time"), h("th", { scope: "col" }, this.cfg.noun))),
          h(
            "tbody",
            null,
            rows.map(([t, v]) => h("tr", null, h("td", null, dateTime(t)), h("td", { class: "num" }, this.fmt(v)))),
          ),
        ),
      ),
    );
  }

  #renderPlot() {
    const { since, until, bucket } = this.window;
    const [xs, ys] = withGaps(this.points, bucket);
    const real = ys.filter((v) => v != null);
    const yRange = Y_RANGES[this.cfg.scale](Math.max(...real), Math.min(...real));

    const mark = token("--data");
    const grid = token("--grid");
    const muted = token("--text-3");
    const font = '12px "Google Sans", system-ui, sans-serif';
    // one line per tick: clock time within a day, the date for longer ranges
    const timeTick = (t) =>
      until - since > 86400
        ? new Date(t * 1000).toLocaleDateString([], { month: "short", day: "numeric" })
        : new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const axisFmt = (v) => `${v.toFixed(this.cfg.axisDecimals)}${this.cfg.unit}`;

    const tip = h("div", { class: "chart-tip" }, h("div", { class: "tip-val" }, h("span", { class: "tip-key" }), h("span")), h("div", { class: "tip-time" }));

    const opts = {
      width: Math.max(this.body.clientWidth, 200),
      height: HEIGHT,
      padding: [10, 12, 0, 0],
      legend: { show: false },
      select: { show: false },
      cursor: {
        y: false,
        drag: { x: false, y: false },
        points: { size: 9, width: 2, fill: mark, stroke: token("--surface") },
      },
      scales: { x: { time: true, range: () => [since, until] }, y: { range: () => yRange } },
      axes: [
        { stroke: muted, font, grid: { stroke: grid, width: 1 }, ticks: { show: false }, space: 80, values: (u, vals) => vals.map(timeTick) },
        { stroke: muted, font, size: 46, grid: { stroke: grid, width: 1 }, ticks: { show: false }, values: (u, vals) => vals.map(axisFmt) },
      ],
      series: [{}, { stroke: mark, width: 2, fill: token("--data-wash"), points: { show: false }, spanGaps: false }],
      hooks: {
        ready: [(u) => u.over.append(tip)],
        setCursor: [
          (u) => {
            const idx = u.cursor.idx;
            const v = idx == null ? null : u.data[1][idx];
            if (v == null) {
              tip.style.display = "none";
              return;
            }
            tip.children[0].lastChild.textContent = this.fmt(v);
            tip.children[1].textContent = dateTime(u.data[0][idx]);
            tip.style.display = "block";
            const x = u.valToPos(u.data[0][idx], "x");
            const y = u.valToPos(v, "y");
            const w = tip.offsetWidth;
            tip.style.left = `${x + 14 + w > u.over.clientWidth ? x - w - 14 : x + 14}px`;
            tip.style.top = `${Math.max(0, y - tip.offsetHeight - 10)}px`;
          },
        ],
      },
    };

    this.body.setAttribute("tabindex", "0");
    this.body.setAttribute("role", "img");
    this.body.setAttribute("aria-label", `${this.cfg.noun} over time. Use the left and right arrow keys to inspect values, or switch to table view.`);

    // eslint-disable-next-line no-undef
    this.plot = new uPlot(opts, [xs, ys], this.body);
    this.#bindKeys(this.plot, xs, ys);
  }

  #bindKeys(u, xs, ys) {
    const valid = ys.map((v, i) => (v == null ? -1 : i)).filter((i) => i >= 0);
    let pos = valid.length - 1;
    const show = () => {
      const i = valid[pos];
      u.setCursor({ left: Math.round(u.valToPos(xs[i], "x")), top: Math.round(u.valToPos(ys[i], "y")) });
    };
    this.body.onfocus = show;
    this.body.onblur = () => u.setCursor({ left: -10, top: -10 });
    this.body.onkeydown = (e) => {
      if (e.key === "ArrowLeft") pos = Math.max(0, pos - 1);
      else if (e.key === "ArrowRight") pos = Math.min(valid.length - 1, pos + 1);
      else if (e.key === "Home") pos = 0;
      else if (e.key === "End") pos = valid.length - 1;
      else if (e.key === "Escape") return this.body.blur();
      else return;
      e.preventDefault();
      show();
    };
  }

  #resize() {
    if (this.plot) this.plot.setSize({ width: Math.max(this.body.clientWidth, 200), height: HEIGHT });
  }

  #destroyPlot() {
    if (this.plot) {
      this.plot.destroy();
      this.plot = null;
    }
  }

  destroy() {
    this.resizer.disconnect();
    this.#destroyPlot();
  }
}
