/** IPC_CHANNELS 存储主进程与渲染进程之间允许调用的通道。 */
export const IPC_CHANNELS = Object.freeze({
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
