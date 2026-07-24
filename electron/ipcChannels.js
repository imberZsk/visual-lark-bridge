/** IPC_CHANNELS 存储主进程与渲染进程之间允许调用的通道。 */
export const IPC_CHANNELS = Object.freeze({
  snapshot: "bridge:snapshot",
  saveConfig: "bridge:save-config",
  setTheme: "bridge:set-theme",
  start: "bridge:start",
  stop: "bridge:stop",
  restart: "bridge:restart",
  setAutoStart: "bridge:set-auto-start",
  revealData: "bridge:reveal-data",
  readLogs: "bridge:read-logs",
  clearLogs: "bridge:clear-logs",
  readTasks: "bridge:read-tasks",
  deleteTask: "bridge:delete-task",
  disableLegacy: "bridge:disable-legacy",
  clearRuntime: "bridge:clear-runtime",
  stateChanged: "bridge:state-changed",
});
