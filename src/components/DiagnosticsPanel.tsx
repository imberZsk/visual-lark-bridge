import {
  Alert,
  Button,
  Descriptions,
  Popconfirm,
  Space,
  Switch,
  Tag,
  Tooltip,
} from "antd";
import {
  DeleteOutlined,
  FolderOpenOutlined,
  StopOutlined,
} from "@ant-design/icons";
import type { BridgeSnapshot } from "../types/bridge";

/** DiagnosticsPanelProps 描述诊断与维护操作输入。 */
interface DiagnosticsPanelProps {
  snapshot: BridgeSnapshot;
  onAutoStart(enabled: boolean): void;
  onReveal(): void;
  onDisableLegacy(): void;
  onClearRuntime(): void;
}

/** DiagnosticsPanel 展示外部依赖并承载安装维护操作。 */
export function DiagnosticsPanel(props: DiagnosticsPanelProps) {
  /** missingTools 存储尚未在登录环境中找到的依赖命令。 */
  const missingTools = Object.entries(props.snapshot.tools)
    .filter(([, toolPath]) => !toolPath)
    .map(([name]) => name);
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>本机诊断</h2>
        </div>
      </div>
      {missingTools.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message={`缺少命令：${missingTools.join("、")}`}
        />
      )}
      {props.snapshot.legacyServices.length > 0 && (
        <Alert
          type="info"
          showIcon
          message={`检测到 ${props.snapshot.legacyServices.length} 个旧后台服务`}
          action={
            <Button
              size="small"
              icon={<StopOutlined />}
              onClick={props.onDisableLegacy}
            >
              停用旧服务
            </Button>
          }
        />
      )}
      <Descriptions column={1} size="small" className="diagnostics-list">
        {Object.entries(props.snapshot.tools).map(([name, toolPath]) => (
          <Descriptions.Item key={name} label={name}>
            <Tag color={toolPath ? "success" : "error"}>
              {toolPath ?? "未找到"}
            </Tag>
          </Descriptions.Item>
        ))}
        <Descriptions.Item label="数据目录">
          {props.snapshot.userDataPath}
        </Descriptions.Item>
        <Descriptions.Item label="登录时启动">
          <Switch
            checked={props.snapshot.autoStart}
            onChange={props.onAutoStart}
          />
        </Descriptions.Item>
      </Descriptions>
      <Space>
        <Button icon={<FolderOpenOutlined />} onClick={props.onReveal}>
          打开数据目录
        </Button>
        <Popconfirm
          title="清理运行数据？"
          description="将停止服务并删除日志与默认工作目录，配置会保留。"
          okText="清理"
          cancelText="取消"
          onConfirm={props.onClearRuntime}
        >
          <Tooltip title="保留配置，仅清理运行数据">
            <Button danger icon={<DeleteOutlined />}>
              清理数据
            </Button>
          </Tooltip>
        </Popconfirm>
      </Space>
    </section>
  );
}
