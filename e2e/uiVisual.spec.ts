import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { launchApp } from "./helpers/electronApp";

/** capturePage 截取当前 Electron 页面并作为测试附件保留，供 UI 人工验收。 */
async function capturePage(
  page: Page,
  testInfo: TestInfo,
  screenshotName: string,
): Promise<void> {
  /** screenshotPath 存储当前页面截图在 Playwright 用例输出目录中的路径。 */
  const screenshotPath = testInfo.outputPath(`${screenshotName}.png`);
  await page.screenshot({
    path: screenshotPath,
    animations: "disabled",
  });
  await testInfo.attach(screenshotName, {
    path: screenshotPath,
    contentType: "image/png",
  });
}

/** assertStableLayout 验证主页面不存在横向溢出且内容面板位于可视区域内。 */
async function assertStableLayout(page: Page): Promise<void> {
  /** layoutMetrics 存储当前视口和主面板几何数据，用于定位截图中不易察觉的溢出。 */
  const layoutMetrics = await page.evaluate(() => {
    /** panel 存储当前页面唯一主内容面板。 */
    const panel = document.querySelector<HTMLElement>(".panel");
    /** panelBounds 存储主面板相对视口的位置和尺寸。 */
    const panelBounds = panel?.getBoundingClientRect();
    return {
      clientWidth: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      panelLeft: panelBounds?.left ?? -1,
      panelRight: panelBounds?.right ?? -1,
    };
  });

  expect(layoutMetrics.scrollWidth).toBe(layoutMetrics.clientWidth);
  expect(layoutMetrics.panelLeft).toBeGreaterThanOrEqual(0);
  expect(layoutMetrics.panelRight).toBeLessThanOrEqual(
    layoutMetrics.clientWidth,
  );
}

test("关键页面生成深浅主题 UI 验收截图", async ({ browserName }, testInfo) => {
  // browserName 验证截图统一由 Chromium 渲染，避免不同浏览器字体度量污染视觉基线。
  expect(browserName).toBe("chromium");
  /** launched 存储本次视觉验收独占的 Electron 应用和页面。 */
  const launched = await launchApp({
    logs: [
      "[2026-07-29T08:00:00] bridge started",
      '[2026-07-29T08:00:01] 收到卡片动作：{"task_id":"t1","chat_id":"oc_demo"}',
    ].join("\n"),
  });
  try {
    await expect(launched.page.locator(".brand img")).toHaveCount(0);
    await assertStableLayout(launched.page);
    await capturePage(launched.page, testInfo, "service-dark");

    await launched.page.getByText("设置", { exact: true }).click();
    await assertStableLayout(launched.page);
    await capturePage(launched.page, testInfo, "settings-dark");

    await launched.page.getByText("日志", { exact: true }).click();
    await launched.page.getByText("bridge started").waitFor();
    await assertStableLayout(launched.page);
    await capturePage(launched.page, testInfo, "logs-dark");

    await launched.page.locator(".ant-segmented-item").first().click();
    await launched.page.getByText("服务", { exact: true }).click();
    await expect(launched.page.locator("html")).toHaveAttribute(
      "data-theme",
      "light",
    );
    await assertStableLayout(launched.page);
    await capturePage(launched.page, testInfo, "service-light");
  } finally {
    await launched.app.close();
  }
});
