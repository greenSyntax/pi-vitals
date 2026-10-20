// Theme preference lives in localStorage when available; otherwise follow the OS.
// The stored value is applied before first paint by theme-init.js.
const KEY = "pivitals-theme";

export function currentTheme() {
  const set = document.documentElement.dataset.theme;
  if (set) return set;
  return matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem(KEY, next);
  } catch {
    /* private mode etc.: the choice just won't persist */
  }
  return next;
}
