/** BridgeConfig 描述桌面端持久化的非敏感配置。 */
export interface BridgeConfig {
  profile: string;
  provider?: "claude" | "codex";
  codexModel?: string;
  larkConfigPath: string;
  workspacePath: string;
  claudeTimeout: number;
  autoStartBridge: boolean;
  theme: "light" | "dark";
}

/** ServiceStatus 描述桥接子进程当前状态。 */
export interface ServiceStatus {
  state: "running" | "stopped" | "error";
  pid: number | null;
  startedAt: string | null;
  lastError: string;
}

/** BridgeTask 描述桌面端展示的桥接任务状态。 */
export interface BridgeTask {
  task_id: string;
  title: string;
  status: string;
  turns: number;
  last_question: string;
  updated_at: string;
}

/** LegacyService 描述检测到的历史 LaunchAgent。 */
export interface LegacyService {
  label: string;
  plistPath: string;
}

/** BridgeSnapshot 描述控制台首屏需要的全部本机状态。 */
export interface BridgeSnapshot {
  config: BridgeConfig;
  service: ServiceStatus;
  tools: Record<"claude" | "codex" | "lark-cli", string | null>;
  legacyServices: LegacyService[];
  autoStart: boolean;
  userDataPath: string;
  version: string;
  tasks: BridgeTask[];
}

/** LarkBridgeApi 描述 preload 暴露给渲染层的安全接口。 */
export interface LarkBridgeApi {
  getSnapshot(): Promise<BridgeSnapshot>;
  saveConfig(config: BridgeConfig): Promise<BridgeConfig>;
  setTheme(theme: "light" | "dark"): Promise<BridgeConfig>;
  start(): Promise<ServiceStatus>;
  stop(): Promise<ServiceStatus>;
  restart(): Promise<ServiceStatus>;
  setAutoStart(enabled: boolean): Promise<boolean>;
  revealData(): Promise<string>;
  readLogs(): Promise<string>;
  clearLogs(): Promise<void>;
  readTasks(): Promise<BridgeTask[]>;
  deleteTask(taskId: string): Promise<BridgeTask[]>;
  disableLegacy(): Promise<BridgeSnapshot>;
  clearRuntime(): Promise<BridgeSnapshot>;
  onStateChanged(listener: (status: ServiceStatus) => void): () => void;
}

declare global {
  interface Window {
    larkBridge: LarkBridgeApi;
  }
}
