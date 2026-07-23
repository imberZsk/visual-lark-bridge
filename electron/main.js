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
const APP_DATA_DIRECTORY = "lark-ai-bridge";
/** isDevelopment 标记当前是否连接 Vite 开发服务器。 */
const isDevelopment = process.env.NODE_ENV === "development";
/** isSmokeTest 标记当前是否执行自动启动验证。 */
const isSmokeTest = process.env.LARK_BRIDGE_SMOKE === "1";

app.setName("Lark AI Bridge");
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

/** createTray 创建菜单栏入口，窗口关闭后仍可管理后台桥接。 */
function createTray() {
  /** trayImage 存储 macOS 模板图标；空图像时系统仍显示菜单项。 */
  const trayImage = nativeImage.createFromPath(
    path.join(projectRoot, "build", "trayTemplate.png"),
  );
  trayImage.setTemplateImage(true);
  /** createdTray 存储新建的菜单栏图标。 */
  const createdTray = new Tray(trayImage);
  createdTray.setToolTip("Lark AI Bridge");
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
    if (process.env.LARK_BRIDGE_SMOKE_SCREENSHOT) {
      /** screenshot 存储生产窗口的 PNG 截图。 */
      const screenshot = await mainWindow.webContents.capturePage();
      await writeFile(
        process.env.LARK_BRIDGE_SMOKE_SCREENSHOT,
        screenshot.toPNG(),
      );
    }
    console.log(preloadReady && uiReady ? "SMOKE_OK" : "SMOKE_FAILED");
    isQuitting = true;
    app.quit();
    return;
  }

  /** initialConfig 存储首次启动时读取的自动启动偏好。 */
  const initialConfig = await configStore.read();
  if (
    initialConfig.autoStartBridge &&
    app.getLoginItemSettings().wasOpenedAtLogin
  ) {
    try {
      /** discoveryModule 存储延迟加载的工具探测模块。 */
      const discoveryModule = await import("./toolDiscovery.js");
      /** discovery 存储登录启动时的外部工具路径。 */
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
