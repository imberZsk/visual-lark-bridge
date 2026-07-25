import { defineConfig } from "@playwright/test";

/** Playwright 配置仅运行真实 Electron 桌面端用例并保留失败诊断。 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  reporter: [["list"], ["html", { open: "never" }]],
  outputDir: "test-results/e2e-artifacts",
  use: { screenshot: "only-on-failure", trace: "retain-on-failure" },
});
