import { useEffect, useState } from "react";

/** ThemeMode 描述应用支持的黑白显示模式。 */
export type ThemeMode = "light" | "dark";
/** THEME_STORAGE_KEY 存储主题偏好的 localStorage 键名。 */
const THEME_STORAGE_KEY = "visual-lark-bridge.theme";

/** readInitialTheme 读取持久化主题，首次启动时跟随系统偏好。 */
function readInitialTheme(): ThemeMode {
  /** storedTheme 存储用户上次明确选择的主题。 */
  const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (storedTheme === "light" || storedTheme === "dark") return storedTheme;
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

/** useThemeMode 管理并持久化应用的黑白模式。 */
export function useThemeMode() {
  /** themeMode 存储当前黑白主题。 */
  const [themeMode, setThemeMode] = useState<ThemeMode>(readInitialTheme);
  useEffect(() => {
    window.localStorage.setItem(THEME_STORAGE_KEY, themeMode);
    document.documentElement.dataset.theme = themeMode;
    // 磁盘配置是跨渲染会话的权威持久化；localStorage 仅承担首屏缓存。
    void window.larkBridge?.setTheme(themeMode);
  }, [themeMode]);
  return { themeMode, setThemeMode };
}
