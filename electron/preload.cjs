const { contextBridge, ipcRenderer } = require("electron");

/** channels 存储 preload 允许访问的固定 IPC 通道。 */
const channels = Object.freeze({
  snapshot: "bridge:snapshot",
  saveConfig: "bridge:save-config",
  start: "bridge:start",
  stop: "bridge:stop",
  restart: "bridge:restart",
  setAutoStart: "bridge:set-auto-start",
  revealData: "bridge:reveal-data",
  readLogs: "bridge:read-logs",
  disableLegacy: "bridge:disable-legacy",
  clearRuntime: "bridge:clear-runtime",
  stateChanged: "bridge:state-changed",
});

/** bridgeApi 存储渲染进程可调用的最小桌面能力集合。 */
const bridgeApi = Object.freeze({
  getSnapshot: () => ipcRenderer.invoke(channels.snapshot),
  saveConfig: (config) => ipcRenderer.invoke(channels.saveConfig, config),
  start: () => ipcRenderer.invoke(channels.start),
  stop: () => ipcRenderer.invoke(channels.stop),
  restart: () => ipcRenderer.invoke(channels.restart),
  setAutoStart: (enabled) => ipcRenderer.invoke(channels.setAutoStart, enabled),
  revealData: () => ipcRenderer.invoke(channels.revealData),
  readLogs: () => ipcRenderer.invoke(channels.readLogs),
  disableLegacy: () => ipcRenderer.invoke(channels.disableLegacy),
  clearRuntime: () => ipcRenderer.invoke(channels.clearRuntime),
  onStateChanged: (listener) => {
    /** wrappedListener 将 Electron 事件参数隔离在 preload 内部。 */
    const wrappedListener = (_event, state) => listener(state);
    ipcRenderer.on(channels.stateChanged, wrappedListener);
    return () =>
      ipcRenderer.removeListener(channels.stateChanged, wrappedListener);
  },
});

contextBridge.exposeInMainWorld("larkBridge", bridgeApi);
