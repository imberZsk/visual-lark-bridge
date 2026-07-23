# Changelog

## 0.1.0 - 2026-07-23

- 新增 Electron 桌面控制台，支持桥接服务、登录自启、配置、诊断、日志、旧服务迁移和运行数据清理。
- 新增可持久化的黑白模式，并将控制台调整为更紧凑的 Ant Design 组件布局；服务状态与本机诊断统一为自适应宽度的单一工作区。
- 将 Python 桥接主进程与飞书官方 SDK WebSocket 网关打包为两个随应用分发的 sidecar。
- 统一产品、运行目录、服务与默认 profile 名称为 Lark AI Bridge / `lark-ai-bridge`。
