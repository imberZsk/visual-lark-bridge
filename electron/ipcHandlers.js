import { ipcMain, shell } from "electron";
import { rm } from "node:fs/promises";
import path from "node:path";
import { IPC_CHANNELS } from "./ipcChannels.js";
import { discoverTools } from "./toolDiscovery.js";

/** registerIpcHandlers 注册桌面控制台允许执行的全部主进程操作。 */
export function registerIpcHandlers(context) {
  /** sendState 将最新服务状态推送给所有渲染窗口。 */
  const sendState = (state) =>
    context.broadcast(IPC_CHANNELS.stateChanged, state);
  context.service.on("changed", sendState);

  /** buildSnapshot 汇总配置、服务、依赖和旧安装状态。 */
  const buildSnapshot = async () => {
    /** config 存储磁盘中的当前配置。 */
    const config = await context.configStore.read();
    /** discovery 存储外部命令探测结果。 */
    const discovery = await discoverTools();
    /** legacyServices 存储检测到的历史 LaunchAgent。 */
    const legacyServices = await context.legacyService.inspect();
    return {
      config,
      service: context.service.status(),
      tools: discovery.tools,
      legacyServices,
      autoStart: context.app.getLoginItemSettings().openAtLogin,
      userDataPath: context.userDataPath,
      version: context.app.getVersion(),
    };
  };

  ipcMain.handle(IPC_CHANNELS.snapshot, buildSnapshot);
  ipcMain.handle(IPC_CHANNELS.saveConfig, async (_event, input) =>
    context.configStore.write(input),
  );
  ipcMain.handle(IPC_CHANNELS.start, async () => {
    /** config 存储本次启动使用的持久化配置。 */
    const config = await context.configStore.read();
    /** discovery 存储本次启动使用的 PATH 与工具状态。 */
    const discovery = await discoverTools();
    if (Object.values(discovery.tools).some((toolPath) => !toolPath))
      throw new Error("缺少 claude 或 lark-cli 命令");
    return context.service.start(config, discovery.path);
  });
  ipcMain.handle(IPC_CHANNELS.stop, () => context.service.stop());
  ipcMain.handle(IPC_CHANNELS.restart, async () => {
    /** config 存储重启后应用的持久化配置。 */
    const config = await context.configStore.read();
    /** discovery 存储重启时重新读取的登录环境。 */
    const discovery = await discoverTools();
    if (Object.values(discovery.tools).some((toolPath) => !toolPath))
      throw new Error("缺少 claude 或 lark-cli 命令");
    return context.service.restart(config, discovery.path);
  });
  ipcMain.handle(IPC_CHANNELS.setAutoStart, (_event, enabled) => {
    context.app.setLoginItemSettings({
      openAtLogin: Boolean(enabled),
      openAsHidden: true,
    });
    return context.app.getLoginItemSettings().openAtLogin;
  });
  ipcMain.handle(IPC_CHANNELS.revealData, () =>
    shell.openPath(context.userDataPath),
  );
  ipcMain.handle(IPC_CHANNELS.readLogs, () => context.service.readLogs());
  ipcMain.handle(IPC_CHANNELS.disableLegacy, async () => {
    await context.legacyService.disable();
    return buildSnapshot();
  });
  ipcMain.handle(IPC_CHANNELS.clearRuntime, async () => {
    await context.service.stop();
    /** removablePaths 存储允许清理且严格位于 userData 下的运行目录。 */
    const removablePaths = ["logs", "workspace"].map((name) =>
      path.join(context.userDataPath, name),
    );
    await Promise.all(
      removablePaths.map((targetPath) =>
        rm(targetPath, { recursive: true, force: true }),
      ),
    );
    return buildSnapshot();
  });
}
