import {
  Button,
  Divider,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Switch,
  TimePicker,
} from "antd";
import { DeleteOutlined, PlusOutlined, SaveOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import type { BridgeConfig } from "../types/bridge";

/** SettingsPanelProps 描述设置表单输入。 */
interface SettingsPanelProps {
  config: BridgeConfig;
  saving: boolean;
  onSave(config: BridgeConfig): void;
}

/** SettingsPanel 编辑桥接运行配置，不接触飞书 App Secret。 */
export function SettingsPanel({ config, saving, onSave }: SettingsPanelProps) {
  /** form 存储设置页表单实例，用于根据推送开关联动校验必填项。 */
  const [form] = Form.useForm<BridgeConfig>();
  /** newsEnabled 存储当前表单是否打开新闻定时推送。 */
  const newsEnabled = Form.useWatch(["news", "enabled"], form);
  /** handleSubmit 在保存前执行跨字段业务校验，避免启用状态与目标配置不一致。 */
  const handleSubmit = (values: BridgeConfig) => {
    if (values.news.enabled && !values.news.chat_id.trim()) {
      // 动态 required 规则不会因 Switch 变化自动重跑，提交边界必须再次阻止半配置落盘。
      form.setFields([
        {
          name: ["news", "chat_id"],
          errors: ["启用推送后必须填写目标会话 Chat ID"],
        },
      ]);
      return;
    }
    onSave(values);
  };
  return (
    <section className="panel settings-panel">
      <Form<BridgeConfig>
        form={form}
        layout="vertical"
        initialValues={config}
        onFinish={handleSubmit}
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
          <Form.Item
            name="claudeTimeout"
            label="响应超时（秒）"
            rules={[
              {
                type: "number",
                min: 30,
                max: 1800,
                message: "响应超时必须在 30 到 1800 秒之间",
              },
            ]}
          >
            {/* InputNumber 的 min/max 不会阻止键盘输入越界值，表单规则负责阻止非法配置提交。 */}
            <InputNumber min={30} max={1800} />
          </Form.Item>
        </div>
        <Divider>AI 新闻推送</Divider>
        <div className="setting-toggle news-enabled-toggle">
          <span>启用定时推送</span>
          <Form.Item name={["news", "enabled"]} valuePropName="checked" noStyle>
            <Switch />
          </Form.Item>
        </div>
        <div className="form-grid news-config-grid">
          <Form.Item
            name={["news", "chat_id"]}
            label="目标会话 Chat ID"
            rules={[
              {
                required: newsEnabled,
                message: "启用推送后必须填写目标会话 Chat ID",
              },
              {
                pattern: /^(?:oc_.+)?$/,
                message: "Chat ID 必须以 oc_ 开头",
              },
            ]}
          >
            <Input placeholder="oc_xxx" />
          </Form.Item>
          <Form.Item label="每日推送时刻">
            <Form.List
              name={["news", "times"]}
              rules={[
                {
                  validator: async (_, times: string[] | undefined) => {
                    if (newsEnabled && (!times || times.length === 0)) {
                      throw new Error("启用推送后至少保留一个推送时刻");
                    }
                  },
                },
              ]}
            >
              {(fields, { add, remove }, { errors }) => (
                <div className="news-times">
                  {fields.map(({ key, name, ...restField }) => (
                    <Space key={key} className="news-time-row" align="start">
                      <Form.Item
                        {...restField}
                        name={name}
                        getValueProps={(time: string | undefined) => ({
                          value: time ? dayjs(`2000-01-01T${time}:00`) : null,
                        })}
                        normalize={(time: Dayjs | null) =>
                          time?.format("HH:mm") ?? ""
                        }
                        rules={[{ required: true, message: "请选择推送时刻" }]}
                        noStyle
                      >
                        <TimePicker
                          format="HH:mm"
                          minuteStep={5}
                          placeholder="选择推送时刻"
                        />
                      </Form.Item>
                      <Button
                        aria-label="删除推送时刻"
                        icon={<DeleteOutlined />}
                        onClick={() => remove(name)}
                      />
                    </Space>
                  ))}
                  <Button icon={<PlusOutlined />} onClick={() => add("09:00")}>
                    添加时刻
                  </Button>
                  <Form.ErrorList errors={errors} />
                </div>
              )}
            </Form.List>
          </Form.Item>
          <Form.Item
            name={["news", "max_items"]}
            label="单次新闻条数"
            rules={[{ type: "number", min: 1, max: 20 }]}
          >
            <InputNumber min={1} max={20} />
          </Form.Item>
        </div>
        <Form.List
          name={["news", "sources"]}
          rules={[
            {
              validator: async (_, sources: unknown[] | undefined) => {
                if (newsEnabled && (!sources || sources.length === 0)) {
                  throw new Error("启用推送后至少保留一个信息源");
                }
              },
            },
          ]}
        >
          {(fields, { add, remove }, { errors }) => (
            <div className="news-sources">
              {fields.map(({ key, name, ...restField }) => (
                <Space key={key} className="news-source-row" align="start">
                  <Form.Item
                    {...restField}
                    name={[name, "name"]}
                    rules={[{ required: true, message: "请输入来源名称" }]}
                  >
                    <Input placeholder="来源名称" />
                  </Form.Item>
                  <Form.Item
                    {...restField}
                    name={[name, "url"]}
                    rules={[
                      { required: true, message: "请输入 RSS 地址" },
                      { type: "url", message: "请输入有效的 HTTP(S) 地址" },
                    ]}
                  >
                    <Input placeholder="https://example.com/rss.xml" />
                  </Form.Item>
                  <Button
                    aria-label="删除信息源"
                    icon={<DeleteOutlined />}
                    onClick={() => remove(name)}
                  />
                </Space>
              ))}
              <Button
                icon={<PlusOutlined />}
                onClick={() => add({ name: "", url: "" })}
              >
                添加信息源
              </Button>
              <Form.ErrorList errors={errors} />
            </div>
          )}
        </Form.List>
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
