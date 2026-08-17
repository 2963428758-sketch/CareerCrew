/** 主题管理：class 切换 Light / Dark，默认浅色，持久化到 localStorage。 */

export type Theme = "light" | "dark"

const STORAGE_KEY = "careercrew-theme"

export function getStoredTheme(): Theme {
  try {
    return localStorage.getItem(STORAGE_KEY) === "dark" ? "dark" : "light"
  } catch {
    return "light"
  }
}

export function applyTheme(theme: Theme) {
  const root = document.documentElement
  root.classList.toggle("dark", theme === "dark")
  root.style.colorScheme = theme
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // 隐私模式等场景下忽略持久化失败
  }
}

export function initTheme() {
  applyTheme(getStoredTheme())
}

export function toggleTheme() {
  applyTheme(document.documentElement.classList.contains("dark") ? "light" : "dark")
}

export function isDark(): boolean {
  return document.documentElement.classList.contains("dark")
}
