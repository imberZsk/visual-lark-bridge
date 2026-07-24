import { useEffect } from "react";
import { LogsPanel } from "../components/LogsPanel";

/** LogsPageProps 描述日志页数据与刷新操作。 */
interface LogsPageProps {
  logs: string;
  loading: boolean;
  onRefresh(): Promise<void>;
  onClear(): Promise<void>;
}

/** LogsPage 在进入页面时读取日志并渲染日志面板。 */
export function LogsPage({ logs, loading, onRefresh, onClear }: LogsPageProps) {
  useEffect(() => {
    void onRefresh();
  }, [onRefresh]);
  return (
    <LogsPanel
      logs={logs}
      loading={loading}
      onRefresh={onRefresh}
      onClear={onClear}
    />
  );
}
