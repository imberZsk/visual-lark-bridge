import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** INDEX_HTML_PATH 存储渲染入口路径，用于验证 React 加载前的启动占位。 */
const INDEX_HTML_PATH = join(process.cwd(), "index.html");
/** STARTUP_ICON_PATH 存储轻量启动图标路径。 */
const STARTUP_ICON_PATH = join(process.cwd(), "public", "startup-icon.png");
/** MAIN_PROCESS_PATH 存储 Electron 主进程入口路径，用于验证开发态项目图标。 */
const MAIN_PROCESS_PATH = join(process.cwd(), "electron", "main.js");

describe("Electron 启动体验", () => {
  it("使用项目图标和 Ant Design 默认四点 loading", () => {
    /** indexHtml 存储入口源码，用于锁定静态首屏结构和设计尺寸。 */
    const indexHtml = readFileSync(INDEX_HTML_PATH, "utf8");

    expect(indexHtml).toContain('aria-label="Visual Lark Bridge 正在启动"');
    expect(indexHtml).toContain('src="./startup-icon.png"');
    expect(
      indexHtml.match(/class="startup-splash__spinner-item"/g),
    ).toHaveLength(4);
    expect(indexHtml).toContain("--startup-icon-size: 112px");
    expect(indexHtml).toContain("--startup-spinner-size: 20px");
    expect(indexHtml).toContain("--startup-spinner-item-size: 9px");
    expect(indexHtml).toContain("top: calc(100% + 16px)");
    expect(existsSync(STARTUP_ICON_PATH)).toBe(true);
  });

  it("开发态显式使用仓库内的高清项目图标", () => {
    /** mainProcess 存储主进程源码，用于锁定 BrowserWindow 和 macOS Dock 图标配置。 */
    const mainProcess = readFileSync(MAIN_PROCESS_PATH, "utf8");

    expect(mainProcess).toMatch(
      /path\.join\(\s*projectRoot,\s*"build",\s*"app-icon\.png",?\s*\)/,
    );
    expect(mainProcess).toContain(
      "app.dock?.setIcon(DEVELOPMENT_APP_ICON_PATH)",
    );
  });
});
