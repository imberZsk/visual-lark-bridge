"""Codex CLI 会话适配器。"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from typing import Callable, Optional


class CodexSession:
    """使用 Codex CLI exec 模式处理一轮消息，保持与任务管理器兼容。"""

    def __init__(self, workspace: Path, log_dir: Path, system_prompt: str, timeout: int, session_id: Optional[str] = None, resume: bool = False):
        """初始化 Codex 会话；session_id 仅用于任务状态标识。"""
        self.workspace, self.log_dir = workspace, log_dir
        self.system_prompt, self.timeout = system_prompt, timeout
        self.session_id = session_id or str(uuid.uuid4())
        self.cancelled = False

    def ask(self, message: str, on_delta: Optional[Callable[[str], None]] = None) -> str:
        """执行一轮 Codex CLI 请求并返回文本；message 是飞书用户问题。"""
        self.workspace.mkdir(parents=True, exist_ok=True)
        prompt = f"{self.system_prompt}\n\n请回答下面这条来自飞书的消息，只输出正文：\n{message}"
        completed = subprocess.run(["codex", "exec", "--full-auto", prompt], cwd=self.workspace, capture_output=True, text=True, timeout=self.timeout)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Codex CLI 执行失败")
        answer = completed.stdout.strip() or "Codex 未返回内容。"
        if on_delta:
            on_delta(answer)
        return answer

    def stop(self) -> None:
        """标记会话停止。"""
        self.cancelled = True
