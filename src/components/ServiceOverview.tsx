import { Alert, App, Button, Descriptions, List, Space, Tag } from "antd";
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
  onDeleteTask(taskId: string): Promise<void>;
}

/** ServiceOverview 展示状态并提供服务生命周期操作。 */
export function ServiceOverview({
  snapshot,
  busy,
  onStart,
  onStop,
  onRestart,
  onDeleteTask,
}: ServiceOverviewProps) {
  /** modalApi 使用 Ant Design 应用上下文，统一主题、动画和按钮配置。 */
  const { modal: modalApi } = App.useApp();
  /** tasks 存储当前桥接任务；兼容旧版主进程未返回任务字段的快照。 */
  const tasks = snapshot.tasks ?? [];
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
    <div className="service-overview">
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
      <div className="task-status-section">
        <div className="section-heading task-status-heading">
          <h3>任务</h3>
          <Tag>{tasks.length}</Tag>
        </div>
        <List
          size="small"
          dataSource={tasks}
          locale={{ emptyText: "暂无任务" }}
          renderItem={(task) => (
            <List.Item>
              <List.Item.Meta
                title={`${task.task_id} · ${task.title}`}
                description={task.last_question || "尚未开始"}
              />
              <Space size={8}>
                <Tag
                  color={task.status === "进行中" ? "processing" : "default"}
                >
                  {task.status}
                </Tag>
                <span className="task-turns">{task.turns} 轮</span>
                <Button
                  size="small"
                  danger
                  disabled={running}
                  onClick={() =>
                    modalApi.confirm({
                      centered: true,
                      className: "center-confirm-modal",
                      title: "删除任务",
                      content: `确定删除任务 ${task.task_id}？删除后任务记录和历史将无法恢复。`,
                      okText: "删除",
                      cancelText: "取消",
                      okButtonProps: { danger: true },
                      onOk: () => onDeleteTask(task.task_id),
                    })
                  }
                >
                  删除
                </Button>
              </Space>
            </List.Item>
          )}
        />
      </div>
    </div>
  );
}
