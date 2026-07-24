# 项目上下文

lark-claude-bridge 通过飞书官方 Node SDK 的 WebSocket 长连接接收消息与卡片事件，再驱动 Python 桥接进程和 Claude Code stream-json 会话，持续更新飞书流式卡片。

- 主业务入口为 `lark_claude_bridge.py`，事件网关为 `lark_event_gateway.cjs`。
- 运行依赖 Python 3、Node.js、Claude Code CLI 和飞书应用配置。
- Node 依赖使用 `package-lock.json`；本仓库不是 pnpm 项目。
- 本机配置从 `.env` 读取，运行副本位于 `~/Library/Application Support/lark-claude-bridge`。

```bash
python3 -m unittest tests/test_lark_claude_bridge.py
node --check lark_event_gateway.cjs
bash -n run.sh
bash -n install-launch-agent.sh
```

工作计划、排查记录和交接说明放在任务根目录的 `docs/`，不要散落到项目代码根目录。
