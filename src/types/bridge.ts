/** BridgeConfig 描述桌面端持久化的非敏感配置。 */
export interface BridgeConfig {
  profile: string;
  larkConfigPath: string;
  workspacePath: string;
  claudeTimeout: number;
  autoStartBridge: boolean;
}

/** ServiceStatus 描述桥接子进程当前状态。 */
export interface ServiceStatus {
  state: "running" | "stopped" | "error";
  pid: number | null;
  startedAt: string | null;
  lastError: string;
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
  tools: Record<"claude" | "lark-cli", string | null>;
  legacyServices: LegacyService[];
  autoStart: boolean;
  userDataPath: string;
  version: string;
}

/** LarkBridgeApi 描述 preload 暴露给渲染层的安全接口。 */
export interface LarkBridgeApi {
  getSnapshot(): Promise<BridgeSnapshot>;
  saveConfig(config: BridgeConfig): Promise<BridgeConfig>;
  start(): Promise<ServiceStatus>;
  stop(): Promise<ServiceStatus>;
  restart(): Promise<ServiceStatus>;
  setAutoStart(enabled: boolean): Promise<boolean>;
  revealData(): Promise<string>;
  readLogs(): Promise<string>;
  disableLegacy(): Promise<BridgeSnapshot>;
  clearRuntime(): Promise<BridgeSnapshot>;
  onStateChanged(listener: (status: ServiceStatus) => void): () => void;
}

declare global {
  interface Window {
    larkBridge: LarkBridgeApi;
  }
}
