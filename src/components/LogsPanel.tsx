import { Button, Empty, Spin } from "antd";
import { ReloadOutlined } from "@ant-design/icons";

/** LogsPanelProps 描述日志面板输入。 */
interface LogsPanelProps {
  logs: string;
  loading: boolean;
  onRefresh(): void;
}

/** LogsPanel 展示桥接主日志尾部。 */
export function LogsPanel({ logs, loading, onRefresh }: LogsPanelProps) {
  return (
    <section className="panel logs-panel">
      <div className="panel-actions">
        <Button icon={<ReloadOutlined />} onClick={onRefresh}>
          刷新
        </Button>
      </div>
      <Spin spinning={loading}>
        {logs ? (
          <pre>{logs}</pre>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无日志" />
        )}
      </Spin>
    </section>
  );
}
