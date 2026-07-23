import { Alert, Button, Descriptions, Space, Tag } from "antd";
import {
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import type { BridgeSnapshot } from "../types/bridge";

/** ServiceOverviewProps 描述服务总览组件输入。 */
interface ServiceOverviewProps {
  snapshot: BridgeSnapshot;
  busy: boolean;
  onStart(): void;
  onStop(): void;
  onRestart(): void;
}

/** ServiceOverview 展示状态并提供服务生命周期操作。 */
export function ServiceOverview({
  snapshot,
  busy,
  onStart,
  onStop,
  onRestart,
}: ServiceOverviewProps) {
  /** running 标记桥接进程当前是否运行。 */
  const running = snapshot.service.state === "running";
  /** statusLabel 存储面向用户的状态名称。 */
  const statusLabel = running
    ? "运行中"
    : snapshot.service.state === "error"
      ? "异常"
      : "已停止";
  /** statusColor 存储状态标签颜色。 */
  const statusColor = running
    ? "success"
    : snapshot.service.state === "error"
      ? "error"
      : "default";
  return (
    <section className="panel service-panel">
      <div className="section-heading">
        <div>
          <h2>桥接服务</h2>
          <Tag color={statusColor}>{statusLabel}</Tag>
        </div>
        <Space>
          <Button
            icon={<PlayCircleOutlined />}
            type="primary"
            disabled={running}
            loading={busy}
            onClick={onStart}
          >
            启动
          </Button>
          <Button
            icon={<PauseCircleOutlined />}
            disabled={!running}
            loading={busy}
            onClick={onStop}
          >
            停止
          </Button>
          <Button
            icon={<ReloadOutlined />}
            disabled={!running}
            loading={busy}
            onClick={onRestart}
          >
            重启
          </Button>
        </Space>
      </div>
      {snapshot.service.lastError && (
        <Alert type="error" showIcon message={snapshot.service.lastError} />
      )}
      <Descriptions column={3} size="small">
        <Descriptions.Item label="进程">
          {snapshot.service.pid ?? "-"}
        </Descriptions.Item>
        <Descriptions.Item label="启动时间">
          {snapshot.service.startedAt
            ? new Date(snapshot.service.startedAt).toLocaleString()
            : "-"}
        </Descriptions.Item>
        <Descriptions.Item label="版本">v{snapshot.version}</Descriptions.Item>
      </Descriptions>
    </section>
  );
}
