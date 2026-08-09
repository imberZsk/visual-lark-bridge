import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/** readSource 读取仓库内源码，供样式边界静态回归测试复用。 */
function readSource(relativePath: string): string {
  return readFileSync(join(process.cwd(), relativePath), "utf8");
}

describe("桌面端样式规范", () => {
  it("业务组件不使用固定行内样式", () => {
    /** componentSources 存储所有 UI 组件源码，用于阻止固定视觉规则回流 JSX。 */
    const componentSources = [
      "src/App.tsx",
      "src/components/DiagnosticsPanel.tsx",
      "src/components/LogsPanel.tsx",
      "src/components/ServiceOverview.tsx",
      "src/components/SettingsPanel.tsx",
      "src/layout/AppSidebar.tsx",
      "src/layout/PageHeader.tsx",
    ].map(readSource);

    for (const componentSource of componentSources) {
      expect(componentSource).not.toMatch(/\bstyle\s*=/);
      expect(componentSource).not.toMatch(/\bstyles\s*=/);
    }
  });

  it("组件专用样式从全局样式拆分并使用语义变量", () => {
    /** globalCss 存储应用壳样式，用于防止业务规则重新回流全局文件。 */
    const globalCss = readSource("src/styles.css");
    /** componentCss 存储三个业务组件样式，用于验证作用域和语义色。 */
    const componentCss = [
      readSource("src/components/ServiceOverview.css"),
      readSource("src/components/SettingsPanel.css"),
      readSource("src/components/LogsPanel.css"),
    ].join("\n");

    expect(globalCss).not.toContain(".news-source-row");
    expect(globalCss).not.toContain(".log-entry-main");
    expect(componentCss).toContain("var(--ant-color-text-secondary)");
    expect(componentCss).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });

  it("颜色直接使用 Visual Worktree 的 Ant Design 算法", () => {
    /** appSource 存储主题入口，确保没有覆盖算法生成的主色。 */
    const appSource = readSource("src/App.tsx");
    /** indexHtml 存储静态启动页颜色，确保暗色 loading 使用算法主色。 */
    const indexHtml = readSource("index.html");

    expect(appSource).toContain("antdTheme.darkAlgorithm");
    expect(appSource).not.toContain("colorPrimary:");
    expect(indexHtml).toContain("--startup-spinner-color: #1668dc");
  });
});
