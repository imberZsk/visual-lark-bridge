import {
  ApiOutlined,
  FileTextOutlined,
  MoonOutlined,
  SettingOutlined,
  SunOutlined,
} from "@ant-design/icons";
import { Layout, Menu, Segmented, Tooltip } from "antd";
import type { ServiceStatus } from "../types/bridge";
import type { ThemeMode } from "../theme/useThemeMode";

/** ViewKey 描述控制台三个固定页面。 */
export type ViewKey = "service" | "settings" | "logs";
/** NAV_ITEMS 存储控制台侧栏的固定页面。 */
const NAV_ITEMS = [
  { key: "service", icon: <ApiOutlined />, label: "服务" },
  { key: "settings", icon: <SettingOutlined />, label: "设置" },
  { key: "logs", icon: <FileTextOutlined />, label: "日志" },
];

/** AppSidebarProps 描述侧栏所需状态和交互。 */
interface AppSidebarProps {
  activeView: ViewKey;
  serviceState: ServiceStatus["state"];
  themeMode: ThemeMode;
  onViewChange(view: ViewKey): void;
  onThemeChange(themeMode: ThemeMode): void;
}

/** AppSidebar 渲染品牌、页面导航、主题切换和服务状态。 */
export function AppSidebar(props: AppSidebarProps) {
  /** serviceLabel 存储侧栏底部的服务状态文本。 */
  const serviceLabel =
    props.serviceState === "running"
      ? "桥接运行中"
      : props.serviceState === "error"
        ? "桥接异常"
        : "桥接未运行";
  return (
    <Layout.Sider width={176} theme={props.themeMode} className="sidebar">
      <div className="brand">
        <div className="brand-mark">LA</div>
        <div>
          <strong>Lark AI Bridge</strong>
          <span>本机控制台</span>
        </div>
      </div>
      <Menu
        mode="inline"
        selectedKeys={[props.activeView]}
        items={NAV_ITEMS}
        onClick={({ key }) => props.onViewChange(key as ViewKey)}
      />
      <div className="sidebar-footer">
        <Tooltip title={props.themeMode === "light" ? "切换深色" : "切换浅色"}>
          <Segmented<ThemeMode>
            block
            size="small"
            aria-label="外观模式"
            value={props.themeMode}
            onChange={props.onThemeChange}
            options={[
              { value: "light", icon: <SunOutlined /> },
              { value: "dark", icon: <MoonOutlined /> },
            ]}
          />
        </Tooltip>
        <div className="sidebar-status">
          <span className={`status-dot ${props.serviceState}`} />
          {serviceLabel}
        </div>
      </div>
    </Layout.Sider>
  );
}
