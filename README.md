# Lark AI Bridge

桥接通过 Claude Code 的 stream-json 接口实时接收思考、工具状态和正文 token，并持续更新飞书流式卡片。卡片创建后会先显示“AI思考中...”，不会在首个 token 到达前出现空白。

回答卡片会展示任务名称、执行阶段、耗时、模型和上下文使用量。同一任务持续复用一张进度卡片，并在没有新 token 时每 10 秒刷新耗时。每条普通飞书消息都会创建新任务和新流式卡片；卡片内输入才会继续该卡片绑定的任务，不产生新的用户消息气泡。“新任务”也会另外发送一张独立卡片，旧卡和新卡都能继续对话。卡片正文按约 4200 字符和每页 4 轮控制可见高度，可通过“较早对话 / 回到最新”在同一卡片翻页，Claude 上下文不受影响。

消息和卡片按钮由官方飞书 Node SDK 的同一条 WebSocket 长连接接收。这样能在连接建立时同时注册 `im.message.receive_v1` 和 `card.action.trigger`，避免旧的双 `lark-cli` 消费者漏注册卡片处理器并提示 `200671`。

卡片内使用独立单行输入组件，输入后按 Enter 直接发送。飞书只有独立输入组件会回传 `input_value`，放在 `form` 中则 Enter 不会提交；因此新版移除了读取不到输入值的发送/清空按钮。收到 Enter 后先显示本轮问题与思考状态，再清空输入框；生成期间只流式更新当前一轮，回答完成后才恢复分页历史。任务卡保持 streaming mode，支持后续多轮继续更新。

桥接支持文本、富文本、图片、文件、语音和视频消息。媒体会下载到运行目录的 `attachments/` 后交给 Claude；引用回复会把被引用消息一并加入问题上下文。“重新生成”会重新读取原消息，因此用户编辑消息后可以直接点击该按钮按最新内容提问。

每张回答卡都有“所有任务”按钮；点击后会另外发送交互式任务列表。列表中的“打开”会为已有任务唤起新的活动流式卡片，也支持停止、重命名和删除任务。

完整的飞书端使用方法见 [`功能说明.md`](./功能说明.md)。

## 安全与开源

项目采用 [MIT License](./LICENSE)。真实 `.env`、日志、附件、AI 会话和本机工作区配置不得提交；详细边界见 [`SECURITY.md`](./SECURITY.md)，参与开发前请阅读 [`CONTRIBUTING.md`](./CONTRIBUTING.md)。

## macOS 开机自启

首次运行先创建本机配置：

```bash
cp .env.example .env
```

在 `.env` 中填写自己的 `LARK_PROFILE` 和 `LARK_APP_ID`。App Secret 不应提交或长期明文保存；使用 `lark-cli profile add --app-secret-stdin` 将它写入系统 Keychain。仓库会忽略真实 `.env`，只提交不含凭证的 `.env.example`。

运行一次安装脚本后，桥接服务会在每次开机并登录当前 macOS 用户时自动启动，异常退出后由 `launchd` 自动拉起：

```bash
./install-launch-agent.sh
```

安装脚本会把运行副本、本机 `.env` 和首次安装时的任务状态迁移到 `~/Library/Application Support/lark-ai-bridge`。如果检测到旧版 `lark-claude-bridge`，还会迁移任务、日志、附件、个性化工作区和 Claude 会话。运行目录中的 `.env` 权限为 `0600`，LaunchAgent 通过 `run.sh` 加载它，不会把配置值展开写入 plist。后台服务不再访问 Desktop，因此无需给 Python 开启“完整磁盘访问权限”。以后源码有更新时，重新运行安装脚本即可同步程序，运行目录里的任务状态和日志会保留。

常用命令：

```bash
# 查看服务状态
launchctl print gui/$(id -u)/com.imber.lark-ai-bridge

# 查看桥接日志
tail -f "$HOME/Library/Application Support/lark-ai-bridge/logs/bridge.log"

# 停止并取消自启
launchctl bootout gui/$(id -u)/com.imber.lark-ai-bridge
rm "$HOME/Library/LaunchAgents/com.imber.lark-ai-bridge.plist"
```
