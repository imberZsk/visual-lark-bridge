import { useEffect, useState } from "react";
import { App as AntApp, ConfigProvider, Layout, Menu, message } from "antd";
import {
  ApiOutlined,
  FileTextOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import zhCN from "antd/locale/zh_CN";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { LogsPanel } from "./components/LogsPanel";
import { ServiceOverview } from "./components/ServiceOverview";
import { SettingsPanel } from "./components/SettingsPanel";
import type {
  BridgeConfig,
  BridgeSnapshot,
  ServiceStatus,
} from "./types/bridge";

/** NAV_ITEMS 存储控制台侧栏的固定页面。 */
const NAV_ITEMS = [
  { key: "service", icon: <ApiOutlined />, label: "服务" },
  { key: "settings", icon: <SettingOutlined />, label: "设置" },
  { key: "logs", icon: <FileTextOutlined />, label: "日志" },
];

/** BridgeConsole 实现桌面端控制台状态与交互。 */
function BridgeConsole() {
  /** snapshot 存储主进程返回的完整状态。 */
  const [snapshot, setSnapshot] = useState<BridgeSnapshot | null>(null);
  /** activeView 存储当前侧栏页面。 */
  const [activeView, setActiveView] = useState("service");
  /** busy 存储服务操作是否正在执行。 */
  const [busy, setBusy] = useState(false);
  /** saving 存储配置保存是否正在执行。 */
  const [saving, setSaving] = useState(false);
  /** logs 存储当前展示的日志尾部。 */
  const [logs, setLogs] = useState("");
  /** logsLoading 存储日志读取状态。 */
  const [logsLoading, setLogsLoading] = useState(false);

  /** refreshSnapshot 从主进程刷新全部状态。 */
  const refreshSnapshot = async () =>
    setSnapshot(await window.larkBridge.getSnapshot());
  /** updateService 只更新状态快照中的服务字段。 */
  const updateService = (service: ServiceStatus) =>
    setSnapshot((current) => (current ? { ...current, service } : current));
  /** runServiceAction 执行服务操作并统一处理忙碌与错误状态。 */
  const runServiceAction = async (action: () => Promise<ServiceStatus>) => {
    setBusy(true);
    try {
      updateService(await action());
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };
  /** saveConfig 持久化设置并同步登录启动选项。 */
  const saveConfig = async (config: BridgeConfig) => {
    setSaving(true);
    try {
      await window.larkBridge.saveConfig(config);
      await window.larkBridge.setAutoStart(config.autoStartBridge);
      await refreshSnapshot();
      message.success("设置已保存");
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };
  /** refreshLogs 读取最新桥接日志。 */
  const refreshLogs = async () => {
    setLogsLoading(true);
    try {
      setLogs(await window.larkBridge.readLogs());
    } finally {
      setLogsLoading(false);
    }
  };

  useEffect(() => {
    refreshSnapshot().catch((error) => message.error(String(error)));
    /** unsubscribe 存储服务状态监听的清理函数。 */
    const unsubscribe = window.larkBridge.onStateChanged(updateService);
    return unsubscribe;
  }, []);
  useEffect(() => {
    if (activeView === "logs") void refreshLogs();
  }, [activeView]);

  if (!snapshot) return <div className="boot-screen">正在读取本机状态...</div>;
  return (
    <Layout className="app-shell">
      <Layout.Sider width={208} theme="light" className="sidebar">
        <div className="brand">
          <div className="brand-mark">LA</div>
          <div>
            <strong>Lark AI Bridge</strong>
            <span>本机桥接控制台</span>
          </div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[activeView]}
          items={NAV_ITEMS}
          onClick={({ key }) => setActiveView(key)}
        />
        <div className="sidebar-status">
          <span className={`status-dot ${snapshot.service.state}`} />
          {snapshot.service.state === "running" ? "桥接运行中" : "桥接未运行"}
        </div>
      </Layout.Sider>
      <Layout.Content className="content">
        <header className="page-header">
          <h1>
            {activeView === "service"
              ? "服务控制"
              : activeView === "settings"
                ? "连接设置"
                : "运行日志"}
          </h1>
        </header>
        {activeView === "service" && (
          <div className="content-stack">
            <ServiceOverview
              snapshot={snapshot}
              busy={busy}
              onStart={() => runServiceAction(window.larkBridge.start)}
              onStop={() => runServiceAction(window.larkBridge.stop)}
              onRestart={() => runServiceAction(window.larkBridge.restart)}
            />
            <DiagnosticsPanel
              snapshot={snapshot}
              onAutoStart={async (enabled) => {
                await window.larkBridge.setAutoStart(enabled);
                await refreshSnapshot();
              }}
              onReveal={() => void window.larkBridge.revealData()}
              onDisableLegacy={async () =>
                setSnapshot(await window.larkBridge.disableLegacy())
              }
              onClearRuntime={async () =>
                setSnapshot(await window.larkBridge.clearRuntime())
              }
            />
          </div>
        )}
        {activeView === "settings" && (
          <SettingsPanel
            key={JSON.stringify(snapshot.config)}
            config={snapshot.config}
            saving={saving}
            onSave={saveConfig}
          />
        )}
        {activeView === "logs" && (
          <LogsPanel
            logs={logs}
            loading={logsLoading}
            onRefresh={refreshLogs}
          />
        )}
      </Layout.Content>
    </Layout>
  );
}

/** App 注入 Ant Design 中文语言与主题。 */
export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#167a65",
          borderRadius: 6,
          colorBgLayout: "#f4f6f7",
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
      }}
    >
      <AntApp>
        <BridgeConsole />
      </AntApp>
    </ConfigProvider>
  );
}
