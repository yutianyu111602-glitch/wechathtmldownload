export const PCUI_THEME_STORAGE_KEY = "pcui_theme";
export const PCUI_THEMES = Object.freeze(["dark", "light"]);

function normalizeTheme(theme, fallback = "dark") {
  return PCUI_THEMES.includes(theme) ? theme : fallback;
}

function getStorageItem(storage, key) {
  try {
    return storage?.getItem?.(key) || "";
  } catch {
    return "";
  }
}

function setStorageItem(storage, key, value) {
  try {
    storage?.setItem?.(key, value);
  } catch {
    // Theme persistence is best-effort; rendering must still proceed.
  }
}

function syncThemeToggle(themeToggle, theme) {
  if (!themeToggle) {
    return;
  }
  const nextTheme = theme === "light" ? "dark" : "light";
  themeToggle.textContent = theme === "light" ? "深色" : "浅色";
  themeToggle.title = `切换到${nextTheme === "light" ? "浅色" : "深色"}主题`;
  themeToggle.setAttribute("aria-label", `切换到${nextTheme === "light" ? "浅色" : "深色"}主题`);
  themeToggle.setAttribute("aria-pressed", theme === "light" ? "true" : "false");
}

export function applyPcuiTheme({
  root = globalThis.document?.documentElement,
  themeToggle = null,
  storage = globalThis.localStorage,
  persist = true,
} = {}, theme = "dark") {
  const nextTheme = normalizeTheme(theme);
  root?.setAttribute?.("data-theme", nextTheme);
  root?.setAttribute?.("data-theme-ready", "true");
  syncThemeToggle(themeToggle, nextTheme);
  if (persist) {
    setStorageItem(storage, PCUI_THEME_STORAGE_KEY, nextTheme);
  }
  return nextTheme;
}

export function createPcuiThemeController({
  root = globalThis.document?.documentElement,
  themeToggle = null,
  storage = globalThis.localStorage,
  defaultTheme = "dark",
} = {}) {
  let currentTheme = normalizeTheme(getStorageItem(storage, PCUI_THEME_STORAGE_KEY), defaultTheme);

  function apply(theme, options = {}) {
    currentTheme = applyPcuiTheme({
      root,
      themeToggle,
      storage,
      persist: options.persist !== false,
    }, theme);
    return currentTheme;
  }

  function toggle() {
    return apply(currentTheme === "light" ? "dark" : "light");
  }

  function bind() {
    themeToggle?.addEventListener?.("click", toggle);
  }

  apply(currentTheme, { persist: false });
  bind();

  return {
    apply,
    getTheme: () => currentTheme,
    toggle,
  };
}
