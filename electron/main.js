import { app, BrowserWindow, Menu, Tray, nativeImage } from "electron";
import path from "node:path";
import os from "node:os";
import { writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { ConfigStore } from "./configStore.js";
import { ServiceManager } from "./serviceManager.js";
import { LegacyService } from "./legacyService.js";
import { registerIpcHandlers } from "./ipcHandlers.js";

/** currentDirectory 存储 Electron 主进程模块目录。 */
const currentDirectory = path.dirname(fileURLToPath(import.meta.url));
/** projectRoot 存储开发源码或打包 app.asar 根目录。 */
const projectRoot = path.resolve(currentDirectory, "..");
/** APP_DATA_DIRECTORY 存储跨版本稳定的用户数据目录名称。 */
const APP_DATA_DIRECTORY = "visual-lark-bridge";
/** isDevelopment 标记当前是否连接 Vite 开发服务器。 */
const isDevelopment = process.env.NODE_ENV === "development";
/** isSmokeTest 标记当前是否执行自动启动验证。 */
const isSmokeTest = process.env.LARK_BRIDGE_SMOKE === "1";
/** TRAY_ICON_FILE 存储 macOS 菜单栏模板图标的文件名。 */
const TRAY_ICON_FILE = "trayTemplate.png";

app.setName("Visual Lark Bridge");
app.setPath("userData", path.join(app.getPath("appData"), APP_DATA_DIRECTORY));

/** mainWindow 存储唯一控制台窗口。 */
let mainWindow = null;
/** tray 存储菜单栏常驻图标。 */
let tray = null;
/** service 存储桥接子进程生命周期管理器。 */
let service = null;
/** isQuitting 标记关闭窗口时是否真正退出应用。 */
let isQuitting = false;

/** createWindow 创建安全隔离的控制台窗口。 */
async function createWindow() {
  /** window 存储新建的浏览器窗口。 */
  const window = new BrowserWindow({
    width: 1080,
    height: 760,
    minWidth: 860,
    minHeight: 620,
    show: false,
    titleBarStyle: "hiddenInset",
    backgroundColor: "#f5f7f8",
    webPreferences: {
      preload: path.join(currentDirectory, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.once("ready-to-show", () => window.show());
  window.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      window.hide();
    }
  });
  if (isDevelopment) await window.loadURL("http://127.0.0.1:5276");
  else await window.loadFile(path.join(projectRoot, "dist", "index.html"));
  return window;
}

/** resolveTrayIconPath 返回开发环境或安装包中的菜单栏图标路径。 */
function resolveTrayIconPath() {
  return app.isPackaged
    ? path.join(process.resourcesPath, TRAY_ICON_FILE)
    : path.join(projectRoot, "build", TRAY_ICON_FILE);
}

/** createTray 创建菜单栏入口，窗口关闭后仍可管理后台桥接。 */
function createTray() {
  /** trayImage 存储只有符号轮廓的 macOS 模板图标。 */
  const trayImage = nativeImage.createFromPath(resolveTrayIconPath());
  // 打包资源路径错误时 Electron 会返回空图像；立即失败可防止菜单栏出现空白占位。
  if (trayImage.isEmpty()) throw new Error("菜单栏图标加载失败");
  trayImage.setTemplateImage(true);
  /** createdTray 存储新建的菜单栏图标。 */
  const createdTray = new Tray(trayImage);
  createdTray.setToolTip("Visual Lark Bridge");
  createdTray.setContextMenu(
    Menu.buildFromTemplate([
      {
        label: "打开控制台",
        click: () => {
          mainWindow?.show();
          mainWindow?.focus();
        },
      },
      { type: "separator" },
      {
        label: "退出",
        click: () => {
          isQuitting = true;
          app.quit();
        },
      },
    ]),
  );
  createdTray.on("click", () => {
    mainWindow?.show();
    mainWindow?.focus();
  });
  return createdTray;
}

/** bootstrap 在 Electron ready 后初始化服务、IPC、窗口和菜单栏。 */
async function bootstrap() {
  if (isSmokeTest) console.log("SMOKE_STAGE:after-ready");
  /** userDataPath 存储所有可变配置、日志与工作区的目录。 */
  const userDataPath = app.getPath("userData");
  /** configStore 存储配置持久化服务。 */
  const configStore = new ConfigStore(userDataPath);
  service = new ServiceManager({
    userDataPath,
    projectRoot,
    homePath: os.homedir(),
    resourcesPath: process.resourcesPath,
    isPackaged: app.isPackaged,
  });
  /** legacyService 存储历史 LaunchAgent 管理器。 */
  const legacyService = new LegacyService(os.homedir());

  registerIpcHandlers({
    app,
    configStore,
    service,
    legacyService,
    userDataPath,
    broadcast: (channel, payload) =>
      BrowserWindow.getAllWindows().forEach((window) =>
        window.webContents.send(channel, payload),
      ),
  });
  mainWindow = await createWindow();
  if (isSmokeTest) console.log("SMOKE_STAGE:window-loaded");
  tray = createTray();

  if (isSmokeTest) {
    /** preloadReady 存储生产窗口是否成功暴露安全 API。 */
    const preloadReady = await mainWindow.webContents.executeJavaScript(
      "typeof window.larkBridge?.getSnapshot === 'function'",
    );
    /** uiReady 存储 IPC 快照返回后控制面板是否完成渲染。 */
    const uiReady = await mainWindow.webContents.executeJavaScript(`
      new Promise((resolve) => {
        const deadline = Date.now() + 10000;
        const check = () => {
          if (document.querySelector('.service-panel')) return resolve(true);
          if (Date.now() >= deadline) return resolve(false);
          setTimeout(check, 100);
        };
        check();
      })
    `);
    /** dragRegionReady 标记顶部预留区域是否已启用 Electron 窗口拖拽。 */
    const dragRegionReady = await mainWindow.webContents.executeJavaScript(`
      (() => {
        // dragRegion 存储渲染进程中的窗口拖拽层。
        const dragRegion = document.querySelector('.window-drag-region');
        if (!dragRegion) return false;
        // dragStyle 存储拖拽层经过 CSS 计算后的最终样式。
        const dragStyle = getComputedStyle(dragRegion);
        return dragStyle.getPropertyValue('-webkit-app-region') === 'drag';
      })()
    `);
    /** requestedView 存储冒烟截图需要打开的页面。 */
    const requestedView = process.env.LARK_BRIDGE_SMOKE_VIEW;
    if (requestedView === "settings" || requestedView === "logs") {
      /** viewIndex 存储目标页面在侧栏菜单中的位置。 */
      const viewIndex = requestedView === "settings" ? 1 : 2;
      /** viewSelector 存储用于确认目标页面完成渲染的选择器。 */
      const viewSelector =
        requestedView === "settings" ? ".settings-panel" : ".logs-panel";
      await mainWindow.webContents.executeJavaScript(`
        new Promise((resolve) => {
          // menuItems 存储侧栏中的页面导航项。
          const menuItems = document.querySelectorAll('.ant-menu-item');
          menuItems[${viewIndex}]?.click();
          // deadline 存储等待目标页面渲染的截止时间。
          const deadline = Date.now() + 3000;
          // check 持续确认目标页面是否已经出现。
          const check = () => {
            if (document.querySelector(${JSON.stringify(viewSelector)})) return resolve(true);
            if (Date.now() >= deadline) return resolve(false);
            setTimeout(check, 100);
          };
          check();
        })
      `);
    }
    /** requestedTheme 存储冒烟截图需要切换到的外观模式。 */
    const requestedTheme = process.env.LARK_BRIDGE_SMOKE_THEME;
    if (requestedTheme === "light" || requestedTheme === "dark") {
      await mainWindow.webContents.executeJavaScript(`
        new Promise((resolve) => {
          // items 存储主题分段控件的两个可点击选项。
          const items = document.querySelectorAll('.ant-segmented-item');
          // targetIndex 存储目标主题对应的选项位置。
          const targetIndex = ${JSON.stringify(requestedTheme)} === 'dark' ? 1 : 0;
          items[targetIndex]?.click();
          // deadline 存储等待主题稳定渲染的截止时间。
          const deadline = Date.now() + 3000;
          // stableChecks 存储主题和页面连续就绪的检查次数。
          let stableChecks = 0;
          const check = () => {
            // themeReady 标记根节点主题是否已经更新。
            const themeReady = document.documentElement.dataset.theme === ${JSON.stringify(requestedTheme)};
            // contentReady 标记业务面板是否已经完成重绘。
            const contentReady = Boolean(document.querySelector('.service-panel'));
            stableChecks = themeReady && contentReady ? stableChecks + 1 : 0;
            if (stableChecks >= 5) return resolve(true);
            if (Date.now() >= deadline) return resolve(false);
            setTimeout(check, 100);
          };
          check();
        })
      `);
    }
    if (process.env.LARK_BRIDGE_SMOKE_SCREENSHOT) {
      /** screenshot 存储生产窗口的 PNG 截图。 */
      const screenshot = await mainWindow.webContents.capturePage();
      await writeFile(
        process.env.LARK_BRIDGE_SMOKE_SCREENSHOT,
        screenshot.toPNG(),
      );
    }
    console.log(
      preloadReady && uiReady && dragRegionReady ? "SMOKE_OK" : "SMOKE_FAILED",
    );
    isQuitting = true;
    app.quit();
    return;
  }

  /** initialConfig 存储应用启动时读取的桥接自动启动偏好。 */
  const initialConfig = await configStore.read();
  if (initialConfig.autoStartBridge) {
    try {
      /** discoveryModule 存储应用启动时延迟加载的工具探测模块。 */
      const discoveryModule = await import("./toolDiscovery.js");
      /** discovery 存储自动启动桥接所需的外部工具路径。 */
      const discovery = await discoveryModule.discoverTools();
      await service.start(initialConfig, discovery.path);
    } catch (error) {
      service.lastError =
        error instanceof Error ? error.message : String(error);
    }
  }
}

if (isSmokeTest) console.log("SMOKE_STAGE:before-ready");
app
  .whenReady()
  .then(bootstrap)
  .catch((error) => {
    console.error(error);
    app.exit(1);
  });

app.on("activate", async () => {
  if (!mainWindow || mainWindow.isDestroyed())
    mainWindow = await createWindow();
  mainWindow.show();
});
app.on("before-quit", async () => {
  isQuitting = true;
  tray?.destroy();
  await service?.stop();
});
