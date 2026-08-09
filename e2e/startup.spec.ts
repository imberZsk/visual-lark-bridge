import {
  expect,
  test,
  type ElectronApplication,
  type TestInfo,
} from "@playwright/test";
import { launchApp } from "./helpers/electronApp";

/** STARTUP_ICON_SIZE_PX 存储冷启动图标设计尺寸。 */
const STARTUP_ICON_SIZE_PX = 112;
/** STARTUP_SPINNER_SIZE_PX 存储 Ant Design 四点 loading 容器尺寸。 */
const STARTUP_SPINNER_SIZE_PX = 20;
/** STARTUP_SPINNER_ITEM_SIZE_PX 存储 Ant Design 四点 loading 单点尺寸。 */
const STARTUP_SPINNER_ITEM_SIZE_PX = 9;

/** captureStartupSplash 在隐藏 Electron 窗口中阻止 React 脚本，验收并截图真实静态启动页。 */
async function captureStartupSplash(
  app: ElectronApplication,
  testInfo: TestInfo,
): Promise<void> {
  /** developmentIconMetrics 存储 Electron 对开发态 Dock 原始图标的真实解码结果。 */
  const developmentIconMetrics = await app.evaluate(({ nativeImage }) => {
    /** pathModule 存储 Node 路径工具，用于定位仓库内的高清图标。 */
    const pathModule = process.getBuiltinModule("node:path");
    /** developmentIcon 存储 Electron 从开发态图标路径解码出的原生图片。 */
    const developmentIcon = nativeImage.createFromPath(
      pathModule.join(process.cwd(), "build", "app-icon.png"),
    );
    return {
      isEmpty: developmentIcon.isEmpty(),
      size: developmentIcon.getSize(),
    };
  });
  expect(developmentIconMetrics).toEqual({
    isEmpty: false,
    size: { width: 1024, height: 1024 },
  });
  /** startupPagePromise 存储启动预览窗口对应的 Playwright 页面等待任务。 */
  const startupPagePromise = app.waitForEvent("window");
  await app.evaluate(async ({ BrowserWindow, session }) => {
    /** pathModule 存储 Node 路径工具，用于定位构建后的入口文件。 */
    const pathModule = process.getBuiltinModule("node:path");
    /** previewSession 存储独立请求会话，避免脚本拦截影响主测试窗口。 */
    const previewSession = session.fromPartition(
      `lark-bridge-startup-${Date.now()}`,
    );
    previewSession.webRequest.onBeforeRequest(
      { urls: ["<all_urls>"] },
      (details, callback) => {
        /** shouldBlockScript 标记 React/Vite 构建脚本请求；启动图标继续真实加载。 */
        const shouldBlockScript = /\.js(?:$|\?)/.test(details.url);
        callback({ cancel: shouldBlockScript });
      },
    );
    /** previewWindow 存储不会显示到桌面的真实 Electron 启动预览窗口。 */
    const previewWindow = new BrowserWindow({
      width: 1080,
      height: 760,
      show: false,
      backgroundColor: "#141414",
      webPreferences: { session: previewSession },
    });
    globalThis.__visualLarkBridgeStartupPreview = previewWindow;
    await previewWindow.loadFile(
      pathModule.join(process.cwd(), "dist", "index.html"),
    );
  });
  /** startupPage 存储只渲染静态启动占位的隐藏 Electron 页面。 */
  const startupPage = await startupPagePromise;
  /** icon 存储冷启动项目图标元素。 */
  const icon = startupPage.locator("#startup-splash img");
  /** spinner 存储 Ant Design 形态的 loading 容器。 */
  const spinner = startupPage.locator(".startup-splash__spinner");
  /** spinnerItems 存储四个 loading 状态点。 */
  const spinnerItems = spinner.locator(".startup-splash__spinner-item");
  await expect(icon).toBeVisible();
  await expect(spinner).toBeVisible();
  await expect(spinnerItems).toHaveCount(4);
  await expect(icon).toHaveCSS("width", `${STARTUP_ICON_SIZE_PX}px`);
  await expect(spinner).toHaveCSS("width", `${STARTUP_SPINNER_SIZE_PX}px`);
  await expect(spinnerItems.first()).toHaveCSS(
    "width",
    `${STARTUP_SPINNER_ITEM_SIZE_PX}px`,
  );
  /** screenshotPath 存储冷启动截图输出路径。 */
  const screenshotPath = testInfo.outputPath("startup-splash.png");
  await startupPage.screenshot({
    path: screenshotPath,
    animations: "disabled",
  });
  await testInfo.attach("startup-splash", {
    path: screenshotPath,
    contentType: "image/png",
  });
  await startupPage.close();
}

test("冷启动展示项目图标和统一 loading", async ({ browserName }, testInfo) => {
  expect(browserName).toBe("chromium");
  /** launched 存储本次用例独占的隐藏 Electron 应用。 */
  const launched = await launchApp();
  try {
    await captureStartupSplash(launched.app, testInfo);
  } finally {
    await launched.app.close();
  }
});
