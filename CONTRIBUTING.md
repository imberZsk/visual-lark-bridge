# 贡献指南

感谢你改进 Lark Claude Bridge。提交改动时请保持飞书事件处理、Claude 会话和本机凭证之间的边界清晰。

## 开发环境

需要 Python 3.10 或更高版本，以及本机可用的 `claude` 和 `lark-cli`。

```bash
cp .env.example .env
python3 -m pip install -r requirements.txt
PYTHONPATH=. python3 -m unittest discover -s tests
```

## 提交前检查

```bash
bash -n run.sh install-launch-agent.sh
PYTHONPATH=. python3 -m unittest discover -s tests
python3 -m compileall -q lark_ai_bridge.py lark_bridge tests
```

如果安装了 ShellCheck，还应执行：

```bash
shellcheck run.sh install-launch-agent.sh
```

## 代码约定

- 不提交真实 `.env`、App Secret、访问令牌、消息内容、日志、附件或 Claude 会话。
- 不在源码、测试或文档中写入个人绝对路径、企业域名和内部系统标识。
- 新增飞书权限或网络访问时，在 PR 中说明用途、数据范围和关闭方式。
- 修复事件回调或流式卡片问题时，补充只覆盖本次行为的回归测试。

## Pull Request

PR 应说明用户可见行为、主要实现、验证命令，以及是否涉及权限、配置迁移或数据安全边界。
