import { useState } from "react";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Space,
  Tag,
  Tooltip,
} from "antd";
import {
  DeleteOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  UnorderedListOutlined,
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
  /** taskDrawerOpen 标记任务管理抽屉当前是否打开。 */
  const [taskDrawerOpen, setTaskDrawerOpen] = useState(false);
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
          <div>
            <h3>任务</h3>
            <Tag>{tasks.length}</Tag>
          </div>
          <Button
            icon={<UnorderedListOutlined />}
            onClick={() => setTaskDrawerOpen(true)}
          >
            管理任务
          </Button>
        </div>
        <div className="task-summary">
          {tasks.length > 0
            ? `最近任务：${tasks.at(-1)?.title ?? "-"}`
            : "暂无任务，飞书发起对话后会显示在这里。"}
        </div>
        <Drawer
          title={`任务管理 · ${tasks.length}`}
          placement="right"
          size="large"
          open={taskDrawerOpen}
          onClose={() => setTaskDrawerOpen(false)}
        >
          {tasks.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无任务"
            />
          ) : (
            <div className="task-drawer-list">
              {[...tasks].reverse().map((task) => (
                <div className="task-drawer-row" key={task.task_id}>
                  <div className="task-drawer-main">
                    <div className="task-drawer-title">
                      <strong>{task.title}</strong>
                      <span>{task.task_id}</span>
                    </div>
                    <div className="task-drawer-question">
                      {task.last_question || "尚未开始"}
                    </div>
                  </div>
                  <Space size={8}>
                    <Tag
                      color={
                        task.status === "进行中" ? "processing" : "default"
                      }
                    >
                      {task.status}
                    </Tag>
                    <span className="task-turns">{task.turns} 轮</span>
                    <Tooltip title={running ? "停止服务后可删除" : "删除任务"}>
                      <Button
                        aria-label={`删除任务 ${task.title}`}
                        icon={<DeleteOutlined />}
                        size="small"
                        danger
                        disabled={running}
                        onClick={() =>
                          modalApi.confirm({
                            centered: true,
                            className: "center-confirm-modal",
                            title: "删除任务",
                            content: `确定删除任务“${task.title}”？删除后任务记录和历史将无法恢复。`,
                            okText: "删除",
                            cancelText: "取消",
                            okButtonProps: { danger: true },
                            onOk: () => onDeleteTask(task.task_id),
                          })
                        }
                      />
                    </Tooltip>
                  </Space>
                </div>
              ))}
            </div>
          )}
        </Drawer>
      </div>
    </div>
  );
}
