import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useThemeMode } from "../../src/theme/useThemeMode";

describe("useThemeMode", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute("data-theme");
    /** matchMediaMock 存储系统深色偏好的测试实现。 */
    const matchMediaMock = vi.fn().mockReturnValue({ matches: true });
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: matchMediaMock,
    });
  });

  it("uses the system preference on first launch", () => {
    /** result 存储主题 hook 当前返回值。 */
    const { result } = renderHook(() => useThemeMode());
    expect(result.current.themeMode).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("persists an explicit light mode selection", () => {
    /** result 存储主题 hook 当前返回值。 */
    const { result } = renderHook(() => useThemeMode());
    act(() => result.current.setThemeMode("light"));
    expect(window.localStorage.getItem("lark-ai-bridge.theme")).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
