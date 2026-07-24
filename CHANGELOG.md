# Changelog

## 0.1.0 - 2026-07-23

- 将项目、应用、数据目录、服务标识、Bundle ID、sidecar 和安装包统一重命名为 Visual Lark Bridge / `visual-lark-bridge`，不迁移旧产品数据。
- 使用新的紫色应用 Logo，并为 macOS 菜单栏提供透明单色桥接图标。
- 参考 Visual Worktree 的 Ant Design 默认主题体系，重新调整亮色、暗色与交互状态配色。
- macOS 安装包使用免费 ad-hoc 完整性签名，不依赖付费开发者证书。
- 新增 Electron 桌面控制台，支持桥接服务、登录自启、配置、诊断、日志、旧服务迁移和运行数据清理。
- 新增可持久化的黑白模式，并将控制台调整为更紧凑的 Ant Design 组件布局；服务状态与本机诊断统一为自适应宽度的单一工作区。
- 将 Python 桥接主进程与飞书官方 SDK WebSocket 网关打包为两个随应用分发的 sidecar。
- 统一产品、运行目录、服务与默认 profile 名称为 Visual Lark Bridge / `visual-lark-bridge`。
