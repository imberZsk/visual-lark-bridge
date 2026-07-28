"""通过 Claude Code 或 Codex CLI 生成新闻摘要。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import NEWS_SUMMARY_TIMEOUT_SECONDS
from .config import NEWS_SYSTEM_PROMPT


def build_news_summarizer_args(provider: str, prompt: str, codex_model: str = "") -> list[str]:
    """构造新闻摘要命令；provider 支持 claude/codex，codex_model 可选。"""
    if provider == "codex":
        # args 存储 Codex 非交互摘要命令。
        args = ["codex", "exec", "--full-auto"]
        if codex_model:
            args.extend(["--model", codex_model])
        args.append(f"{NEWS_SYSTEM_PROMPT}\n\n{prompt}")
        return args
    return [
        "claude", "--print", "--permission-mode", "bypassPermissions",
        "--append-system-prompt", NEWS_SYSTEM_PROMPT, prompt,
    ]


def summarize_news(
    provider: str, prompt: str, workspace: Path, codex_model: str = ""
) -> str:
    """运行配置的 AI CLI 并返回摘要正文；workspace 是隔离工作目录。"""
    workspace.mkdir(parents=True, exist_ok=True)
    # completed 存储摘要子进程结果，用于统一检查退出码和空输出。
    completed = subprocess.run(
        build_news_summarizer_args(provider, prompt, codex_model),
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        timeout=NEWS_SUMMARY_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "新闻摘要命令执行失败")
    # summary 存储去除首尾空白后的 AI 输出。
    summary = completed.stdout.strip()
    if not summary:
        raise RuntimeError("新闻摘要命令未返回内容")
    return summary
