const { contextBridge } = require("electron");

/** initialState 存储当前用例通过环境变量注入的隔离桌面状态。 */
const initialState = JSON.parse(process.env.LARK_BRIDGE_E2E_STATE || "{}");
/** listeners 存储服务状态订阅者。 */
const listeners = new Set();
/** state 存储测试运行中可变的快照、日志和调用记录。 */
const state = {
  snapshot: initialState.snapshot,
  logs: initialState.logs || "",
  calls: [],
};

/** record 记录渲染层动作及参数，供 E2E 断言副作用。 */
function record(name, value) {
  state.calls.push({ name, value });
}

/** updateService 更新服务状态并模拟主进程推送。 */
function updateService(service) {
  state.snapshot = { ...state.snapshot, service };
  listeners.forEach((listener) => listener(service));
  return service;
}

/** bridgeApi 模拟 preload 的最小稳定协议，不访问真实飞书和本机凭据。 */
const bridgeApi = {
  getSnapshot: async () => structuredClone(state.snapshot),
  saveConfig: async (config) => {
    record("saveConfig", config);
    state.snapshot.config = { ...config };
    return config;
  },
  setTheme: async (theme) => {
    record("setTheme", theme);
    state.snapshot.config.theme = theme;
    return state.snapshot.config;
  },
  start: async () =>
    updateService({
      state: "running",
      pid: 43210,
      startedAt: "2026-07-25T01:00:00.000Z",
      lastError: "",
    }),
  stop: async () =>
    updateService({
      state: "stopped",
      pid: null,
      startedAt: null,
      lastError: "",
    }),
  restart: async () => {
    record("restart", true);
    return updateService({
      state: "running",
      pid: 43211,
      startedAt: "2026-07-25T01:01:00.000Z",
      lastError: "",
    });
  },
  setAutoStart: async (enabled) => {
    record("setAutoStart", enabled);
    state.snapshot.autoStart = Boolean(enabled);
    return state.snapshot.autoStart;
  },
  revealData: async () => {
    record("revealData", true);
    return "";
  },
  readLogs: async () => state.logs,
  clearLogs: async () => {
    record("clearLogs", true);
    state.logs = "";
  },
  readTasks: async () => structuredClone(state.snapshot.tasks || []),
  deleteTask: async (taskId) => {
    record("deleteTask", taskId);
    state.snapshot.tasks = (state.snapshot.tasks || []).filter(
      (task) => task.task_id !== taskId,
    );
    return structuredClone(state.snapshot.tasks);
  },
  disableLegacy: async () => {
    record("disableLegacy", true);
    state.snapshot.legacyServices = [];
    return structuredClone(state.snapshot);
  },
  clearRuntime: async () => {
    record("clearRuntime", true);
    state.logs = "";
    state.snapshot.tasks = [];
    return structuredClone(state.snapshot);
  },
  onStateChanged: (listener) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

contextBridge.exposeInMainWorld("larkBridge", bridgeApi);
contextBridge.exposeInMainWorld("larkBridgeE2e", {
  getCalls: () => structuredClone(state.calls),
});
