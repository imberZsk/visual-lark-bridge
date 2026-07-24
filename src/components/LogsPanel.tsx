import { App, Button, Empty, Spin } from "antd";
import { DeleteOutlined, ReloadOutlined } from "@ant-design/icons";

/** LogsPanelProps 描述日志面板输入。 */
interface LogsPanelProps {
  logs: string;
  loading: boolean;
  onRefresh(): void;
  onClear(): Promise<void>;
}

/** LogsPanel 展示桥接主日志尾部。 */
export function LogsPanel({
  logs,
  loading,
  onRefresh,
  onClear,
}: LogsPanelProps) {
  /** modalApi 使用 Ant Design 上下文，确保弹层跟随当前明暗主题。 */
  const { modal: modalApi } = App.useApp();
  return (
    <section className="panel logs-panel">
      <div className="panel-actions">
        <Button icon={<ReloadOutlined />} onClick={onRefresh}>
          刷新
        </Button>
        <Button
          danger
          icon={<DeleteOutlined />}
          disabled={!logs}
          onClick={() =>
            modalApi.confirm({
              centered: true,
              className: "center-confirm-modal",
              title: "清空运行日志",
              content: "确定清空当前桥接运行日志吗？此操作不可恢复。",
              okText: "清空",
              cancelText: "取消",
              okButtonProps: { danger: true },
              onOk: onClear,
            })
          }
        >
          清空
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
