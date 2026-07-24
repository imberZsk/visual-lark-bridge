import type { ViewKey } from "./AppSidebar";

/** VIEW_TITLES 存储各页面的标题。 */
const VIEW_TITLES: Record<ViewKey, string> = {
  service: "服务控制",
  settings: "连接设置",
  logs: "运行日志",
};

/** PageHeaderProps 描述页头当前页面。 */
interface PageHeaderProps {
  activeView: ViewKey;
}

/** PageHeader 渲染紧凑页面标题。 */
export function PageHeader({ activeView }: PageHeaderProps) {
  return (
    <header className="page-header">
      <h1>{VIEW_TITLES[activeView]}</h1>
    </header>
  );
}
