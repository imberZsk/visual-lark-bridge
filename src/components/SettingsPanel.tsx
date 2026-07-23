import { Button, Form, Input, InputNumber, Switch } from "antd";
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
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>连接设置</h2>
        </div>
      </div>
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
          <Form.Item name="autoStartBridge" valuePropName="checked" noStyle>
            <Switch
              checkedChildren="登录后启动桥接"
              unCheckedChildren="登录后不启动"
            />
          </Form.Item>
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
