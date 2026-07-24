import { Button, Form, Input, InputNumber, Select, Switch } from "antd";
import { SaveOutlined } from "@ant-design/icons";
import type { BridgeConfig } from "../types/bridge";

/** SettingsPanelProps 描述设置表单输入。 */
interface SettingsPanelProps {
  config: BridgeConfig;
  saving: boolean;
  onSave(config: BridgeConfig): void;
}

/** SettingsPanel 编辑桥接运行配置，不接触飞书 App Secret。 */
export function SettingsPanel({ config, saving, onSave }: SettingsPanelProps) {
  return (
    <section className="panel settings-panel">
      <Form<BridgeConfig>
        layout="vertical"
        initialValues={config}
        onFinish={onSave}
        requiredMark={false}
      >
        <div className="form-grid">
          <Form.Item
            name="profile"
            label="飞书 Profile"
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item name="provider" label="AI 提供方">
            <Select
              options={[
                { value: "claude", label: "Claude Code" },
                { value: "codex", label: "Codex CLI" },
              ]}
            />
          </Form.Item>
          <Form.Item name="codexModel" label="Codex 模型（可选）">
            <Input placeholder="留空使用 Codex 默认模型" />
          </Form.Item>
          <Form.Item name="larkConfigPath" label="lark-cli 配置">
            <Input />
          </Form.Item>
          <Form.Item name="workspacePath" label="Claude 工作目录">
            <Input placeholder="默认使用应用数据目录" />
          </Form.Item>
          <Form.Item name="claudeTimeout" label="响应超时（秒）">
            <InputNumber min={30} max={1800} />
          </Form.Item>
        </div>
        <div className="form-footer">
          <div className="setting-toggle">
            <span>登录时启动桥接</span>
            <Form.Item name="autoStartBridge" valuePropName="checked" noStyle>
              <Switch />
            </Form.Item>
          </div>
          <Button
            htmlType="submit"
            type="primary"
            icon={<SaveOutlined />}
            loading={saving}
          >
            保存设置
          </Button>
        </div>
      </Form>
    </section>
  );
}
