export function bytes(n) {
  if (n == null) return "–";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n >= 100 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${units[i]}`;
}

export function percent(v, digits = 0) {
  return v == null ? "–" : `${v.toFixed(digits)}%`;
}

export function uptime(seconds) {
  if (seconds == null) return "–";
  const d = Math.floor(seconds / 86400);
  const hrs = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${hrs}h`;
  if (hrs) return `${hrs}h ${m}m`;
  return `${m}m`;
}

export function clock(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function dateTime(ts) {
  return new Date(ts * 1000).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// metric -> [warn, danger] thresholds
const THRESHOLDS = {
  cpu: [75, 90],
  memory: [75, 90],
  disk: [80, 90],
  swap: [50, 80],
  temperature: [65, 80],
};

export function severity(metric, value) {
  if (value == null) return "na";
  const [warn, danger] = THRESHOLDS[metric];
  return value >= danger ? "danger" : value >= warn ? "warn" : "ok";
}

export const SEVERITY_LABEL = { ok: "Normal", warn: "High", danger: "Critical", na: "No data" };
export const SEVERITY_ICON = { ok: "circle-check", warn: "triangle-alert", danger: "octagon-alert", na: "info" };
export const SEVERITY_RANK = { na: 0, ok: 1, warn: 2, danger: 3 };
