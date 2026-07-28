import {
  _electron as electron,
  test,
  type ElectronApplication,
  type Page,
} from "@playwright/test";

/** DEFAULT_SNAPSHOT 存储每条用例默认使用的停止态控制台数据。 */
export const DEFAULT_SNAPSHOT = {
  config: {
    profile: "visual-lark-bridge",
    provider: "claude",
    codexModel: "",
    larkConfigPath: "~/.lark-cli/config.json",
    workspacePath: "",
    claudeTimeout: 180,
    autoStartBridge: true,
    theme: "dark",
    news: {
      enabled: false,
      chat_id: "",
      times: ["09:07"],
      sources: [
        { name: "Hacker News", url: "https://hnrss.org/frontpage" },
      ],
      max_items: 8,
    },
  },
  service: { state: "stopped", pid: null, startedAt: null, lastError: "" },
  tools: {
    claude: "/bin/claude",
    codex: "/bin/codex",
    "lark-cli": "/bin/lark-cli",
  },
  legacyServices: [],
  autoStart: false,
  userDataPath: "/tmp/visual-lark-bridge-e2e",
  version: "0.1.0",
  tasks: [],
};

/** launchApp 使用隔离状态启动真实 Electron 渲染进程。 */
export async function launchApp(
  overrides: Record<string, unknown> = {},
): Promise<{ app: ElectronApplication; page: Page }> {
  /** snapshotOverrides 存储用例需要覆盖的快照字段。 */
  const snapshotOverrides = (overrides.snapshot || {}) as Record<
    string,
    unknown
  >;
  /** snapshot 存储合并后的完整桌面状态。 */
  const snapshot = {
    ...DEFAULT_SNAPSHOT,
    ...snapshotOverrides,
    config: {
      ...DEFAULT_SNAPSHOT.config,
      ...((snapshotOverrides.config || {}) as object),
    },
    service: {
      ...DEFAULT_SNAPSHOT.service,
      ...((snapshotOverrides.service || {}) as object),
    },
    tools: {
      ...DEFAULT_SNAPSHOT.tools,
      ...((snapshotOverrides.tools || {}) as object),
    },
  };
  /** app 存储当前用例独占的 Electron 应用进程。 */
  const app = await electron.launch({
    args: ["."],
    env: {
      ...process.env,
      NODE_ENV: "production",
      LARK_BRIDGE_E2E: "1",
      LARK_BRIDGE_E2E_STATE: JSON.stringify({ ...overrides, snapshot }),
    },
  });
  /** page 存储 Electron 主窗口页面。 */
  const page = await app.firstWindow();
  await page.getByRole("heading", { name: "服务控制" }).waitFor();
  return { app, page };
}

/** readCalls 读取隔离 preload 记录的桌面动作。 */
export async function readCalls(
  page: Page,
): Promise<Array<{ name: string; value: unknown }>> {
  return page.evaluate(() => window.larkBridgeE2e.getCalls());
}

/** e2eTest 注册一条带独占 Electron 生命周期的桌面用例。 */
export function e2eTest(
  name: string,
  overrides: Record<string, unknown>,
  body: (page: Page) => Promise<void>,
): void {
  test(name, async () => {
    /** launched 存储当前用例的 Electron 应用和主窗口。 */
    const launched = await launchApp(overrides);
    try {
      await body(launched.page);
    } finally {
      await launched.app.close();
    }
  });
}
