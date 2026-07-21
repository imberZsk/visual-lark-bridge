"""提供桥接运行目录与 Claude Code 本地索引之间的路径转换。"""

from pathlib import Path


def encode_claude_project_path(workspace_path: Path) -> str:
    """把 workspace_path 编码为 Claude Code 在 ~/.claude/projects 使用的目录名。"""
    # absolute_workspace_path 存储解析后的绝对工作区路径，避免相对路径产生不稳定索引。
    absolute_workspace_path = workspace_path.expanduser().resolve()
    # Claude Code 会把路径分隔符和空格都折叠为短横线；遗漏空格会导致 Application Support 下的会话无法恢复。
    return str(absolute_workspace_path).replace("/", "-").replace(" ", "-")
