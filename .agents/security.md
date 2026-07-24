# 安全约束

- 不读取、打印、提交或回显 App Secret、token、cookie、私钥、`.env` 和 Claude 会话内容。
- 只提交无凭据 `.env.example`；App Secret 使用 `lark-cli profile add --app-secret-stdin` 写入系统 Keychain。
- 附件文件名和路径必须规范化，阻止路径穿越；删除任务附件时限定在运行目录。
- 外部命令参数化执行，动态内容不得直接拼接到 shell。
- 日志、卡片错误和异常堆栈进行敏感字段脱敏。
- `SECURITY.md` 是公开安全边界，行为变化时同步更新。
