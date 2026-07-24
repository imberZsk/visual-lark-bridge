import { App as AntApp } from "antd";
import { useCallback, useEffect, useState } from "react";
import type {
  BridgeConfig,
  BridgeSnapshot,
  ServiceStatus,
} from "../types/bridge";

/** BridgeController 描述页面可使用的桥接状态和业务操作。 */
export interface BridgeController {
  snapshot: BridgeSnapshot | null;
  serviceBusy: boolean;
  settingsSaving: boolean;
  logs: string;
  logsLoading: boolean;
  startService(): Promise<void>;
  stopService(): Promise<void>;
  restartService(): Promise<void>;
  saveConfig(config: BridgeConfig): Promise<void>;
  refreshLogs(): Promise<void>;
  clearLogs(): Promise<void>;
  setAutoStart(enabled: boolean): Promise<void>;
  revealData(): Promise<void>;
  disableLegacy(): Promise<void>;
  clearRuntime(): Promise<void>;
  deleteTask(taskId: string): Promise<void>;
}

/** useBridgeController 管理 Electron IPC 对应的全部页面业务状态。 */
export function useBridgeController(): BridgeController {
  /** messageApi 存储 Ant Design 全局消息接口。 */
  const { message: messageApi } = AntApp.useApp();
  /** snapshot 存储主进程返回的完整状态。 */
  const [snapshot, setSnapshot] = useState<BridgeSnapshot | null>(null);
  /** serviceBusy 存储服务操作是否正在执行。 */
  const [serviceBusy, setServiceBusy] = useState(false);
  /** settingsSaving 存储配置保存是否正在执行。 */
  const [settingsSaving, setSettingsSaving] = useState(false);
  /** logs 存储当前展示的日志尾部。 */
  const [logs, setLogs] = useState("");
  /** logsLoading 存储日志读取状态。 */
  const [logsLoading, setLogsLoading] = useState(false);

  /** refreshSnapshot 从主进程刷新全部状态。 */
  const refreshSnapshot = useCallback(async () => {
    setSnapshot(await window.larkBridge.getSnapshot());
  }, []);

  /** updateService 只更新快照中的服务状态。 */
  const updateService = useCallback((service: ServiceStatus) => {
    setSnapshot((current) => (current ? { ...current, service } : current));
  }, []);

  /** runServiceAction 执行服务操作并统一处理忙碌和错误状态。 */
  const runServiceAction = useCallback(
    async (action: () => Promise<ServiceStatus>) => {
      setServiceBusy(true);
      try {
        updateService(await action());
      } catch (error) {
        messageApi.error(
          error instanceof Error ? error.message : String(error),
        );
      } finally {
        setServiceBusy(false);
      }
    },
    [messageApi, updateService],
  );

  /** saveConfig 持久化设置并同步登录启动选项。 */
  const saveConfig = useCallback(
    async (config: BridgeConfig) => {
      setSettingsSaving(true);
      try {
        await window.larkBridge.saveConfig(config);
        await window.larkBridge.setAutoStart(config.autoStartBridge);
        await refreshSnapshot();
        messageApi.success("设置已保存");
      } catch (error) {
        messageApi.error(
          error instanceof Error ? error.message : String(error),
        );
      } finally {
        setSettingsSaving(false);
      }
    },
    [messageApi, refreshSnapshot],
  );

  /** refreshLogs 读取最新桥接日志。 */
  const refreshLogs = useCallback(async () => {
    setLogsLoading(true);
    try {
      setLogs(await window.larkBridge.readLogs());
    } finally {
      setLogsLoading(false);
    }
  }, []);

  /** clearLogs 清空运行日志并同步清空当前页面内容。 */
  const clearLogs = useCallback(async () => {
    await window.larkBridge.clearLogs();
    setLogs("");
    messageApi.success("日志已清空");
  }, [messageApi]);

  /** setAutoStart 更新系统登录启动设置并刷新快照。 */
  const setAutoStart = useCallback(
    async (enabled: boolean) => {
      await window.larkBridge.setAutoStart(enabled);
      await refreshSnapshot();
    },
    [refreshSnapshot],
  );

  /** revealData 在 Finder 中打开应用数据目录。 */
  const revealData = useCallback(async () => {
    await window.larkBridge.revealData();
  }, []);

  /** disableLegacy 停用旧 LaunchAgent 并应用最新快照。 */
  const disableLegacy = useCallback(async () => {
    setSnapshot(await window.larkBridge.disableLegacy());
  }, []);

  /** clearRuntime 清理运行数据并应用最新快照。 */
  const clearRuntime = useCallback(async () => {
    setSnapshot(await window.larkBridge.clearRuntime());
  }, []);

  /** deleteTask 删除已停止服务中的任务并刷新任务列表。 */
  const deleteTask = useCallback(
    async (taskId: string) => {
      try {
        await window.larkBridge.deleteTask(taskId);
        await refreshSnapshot();
        messageApi.success("任务已删除");
      } catch (error) {
        messageApi.error(
          error instanceof Error ? error.message : String(error),
        );
      }
    },
    [messageApi, refreshSnapshot],
  );

  useEffect(() => {
    refreshSnapshot().catch((error) => messageApi.error(String(error)));
    /** unsubscribe 存储服务状态监听的清理函数。 */
    const unsubscribe = window.larkBridge.onStateChanged(updateService);
    // taskPollingTimer 定期读取任务状态，让桌面列表跟随飞书会话实时变化。
    const taskPollingTimer = window.setInterval(() => {
      refreshSnapshot().catch(() => undefined);
    }, 2000);
    return () => {
      unsubscribe();
      window.clearInterval(taskPollingTimer);
    };
  }, [messageApi, refreshSnapshot, updateService]);

  return {
    snapshot,
    serviceBusy,
    settingsSaving,
    logs,
    logsLoading,
    startService: () => runServiceAction(window.larkBridge.start),
    stopService: () => runServiceAction(window.larkBridge.stop),
    restartService: () => runServiceAction(window.larkBridge.restart),
    saveConfig,
    refreshLogs,
    clearLogs,
    setAutoStart,
    revealData,
    disableLegacy,
    clearRuntime,
    deleteTask,
  };
}
