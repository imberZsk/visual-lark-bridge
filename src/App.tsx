import { useEffect, useState } from "react";
import {
  App as AntApp,
  ConfigProvider,
  Layout,
  Spin,
  theme as antdTheme,
} from "antd";
import zhCN from "antd/locale/zh_CN";
import { useBridgeController } from "./hooks/useBridgeController";
import { AppSidebar, type ViewKey } from "./layout/AppSidebar";
import { PageHeader } from "./layout/PageHeader";
import { LogsPage } from "./pages/LogsPage";
import { ServicePage } from "./pages/ServicePage";
import { SettingsPage } from "./pages/SettingsPage";
import { useThemeMode, type ThemeMode } from "./theme/useThemeMode";

/** GLOBAL_MESSAGE_CONFIG 将所有 Toast 的几何中心对齐窗口中心。 */
const GLOBAL_MESSAGE_CONFIG = {
  duration: 3,
  maxCount: 3,
  top: "50%",
  styles: { listContent: { transform: "translateY(-50%)" } },
};

/** BridgeConsoleProps 描述控制台外观状态。 */
interface BridgeConsoleProps {
  themeMode: ThemeMode;
  onThemeChange(themeMode: ThemeMode): void;
}

/** BridgeConsole 负责页面选择并组合布局与业务页面。 */
function BridgeConsole({ themeMode, onThemeChange }: BridgeConsoleProps) {
  /** controller 存储桥接业务状态和操作。 */
  const controller = useBridgeController();
  /** activeView 存储当前侧栏页面。 */
  const [activeView, setActiveView] = useState<ViewKey>("service");

  useEffect(() => {
    // 仅在磁盘快照变化时同步主题；依赖当前 themeMode 会把用户刚点击的新主题立即改回旧快照值。
    const configuredTheme = controller.snapshot?.config.theme;
    if (configuredTheme) onThemeChange(configuredTheme);
  }, [controller.snapshot?.config.theme, onThemeChange]);

  if (!controller.snapshot) {
    return (
      <div className="boot-screen">
        <Spin size="small" />
      </div>
    );
  }

  return (
    <Layout className="app-shell">
      <div className="window-drag-region" aria-hidden="true" />
      <AppSidebar
        activeView={activeView}
        serviceState={controller.snapshot.service.state}
        themeMode={themeMode}
        onViewChange={setActiveView}
        onThemeChange={onThemeChange}
      />
      <Layout.Content className="content">
        <PageHeader activeView={activeView} />
        {activeView === "service" && (
          <ServicePage
            snapshot={controller.snapshot}
            busy={controller.serviceBusy}
            onStart={controller.startService}
            onStop={controller.stopService}
            onRestart={controller.restartService}
            onAutoStart={controller.setAutoStart}
            onReveal={controller.revealData}
            onDisableLegacy={controller.disableLegacy}
            onClearRuntime={controller.clearRuntime}
            onDeleteTask={controller.deleteTask}
          />
        )}
        {activeView === "settings" && (
          <SettingsPage
            config={controller.snapshot.config}
            saving={controller.settingsSaving}
            onSave={controller.saveConfig}
          />
        )}
        {activeView === "logs" && (
          <LogsPage
            logs={controller.logs}
            tasks={controller.snapshot.tasks}
            loading={controller.logsLoading}
            onRefresh={controller.refreshLogs}
            onClear={controller.clearLogs}
          />
        )}
      </Layout.Content>
    </Layout>
  );
}

/** App 注入 Ant Design 黑白主题、中文语言和紧凑尺寸。 */
export default function App() {
  /** themeMode 存储当前外观模式和更新方法。 */
  const { themeMode, setThemeMode } = useThemeMode();
  /** darkMode 标记当前是否使用深色模式。 */
  const darkMode = themeMode === "dark";
  return (
    <ConfigProvider
      locale={zhCN}
      componentSize="small"
      modal={{ centered: true }}
      theme={{
        algorithm: darkMode
          ? antdTheme.darkAlgorithm
          : antdTheme.defaultAlgorithm,
        token: {
          borderRadius: 4,
          fontSize: 13,
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        },
        components: {
          Layout: {
            bodyBg: darkMode ? "#141414" : "#f5f5f5",
            siderBg: darkMode ? "#141414" : "#ffffff",
          },
          Menu: {
            darkItemBg: "#141414",
            itemBorderRadius: 4,
          },
          Button: { borderRadius: 4 },
          Input: { borderRadius: 4 },
        },
      }}
    >
      <AntApp message={GLOBAL_MESSAGE_CONFIG}>
        <BridgeConsole themeMode={themeMode} onThemeChange={setThemeMode} />
      </AntApp>
    </ConfigProvider>
  );
}
