"""claude logs 模块。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional


def utc_now_iso() -> str:
    """返回 Claude JSONL 日志使用的 UTC ISO 时间字符串。"""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso_timestamp(value: str) -> float:
    """把 Claude JSONL 中的 ISO 时间字符串转换为 Unix 秒时间戳。"""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def project_log_dir_for_cwd(cwd: Path) -> Path:
    """根据 Claude Code 的项目路径编码规则计算本工作目录对应的日志目录。"""
    # absolute_cwd 是解析软链后的绝对工作目录。
    absolute_cwd = cwd.resolve()
    # encoded_cwd 是 Claude Code 用于 ~/.claude/projects 子目录的路径编码。
    encoded_cwd = str(absolute_cwd).replace("/", "-")
    return Path.home() / ".claude" / "projects" / encoded_cwd


def newest_jsonl_file(directory: Path, newer_than: float = 0.0) -> Optional[Path]:
    """在目录里找最近修改过的 Claude 会话 JSONL 文件。"""
    if not directory.exists():
        return None

    # newest_path 保存当前扫描到的最新 JSONL 文件路径。
    newest_path: Optional[Path] = None
    # newest_mtime 保存当前最新文件的修改时间，用于过滤旧会话。
    newest_mtime = newer_than
    for path in directory.glob("*.jsonl"):
        # path_mtime 是当前候选 JSONL 文件的修改时间。
        path_mtime = path.stat().st_mtime
        if path_mtime >= newest_mtime:
            newest_path = path
            newest_mtime = path_mtime
    return newest_path


def recent_jsonl_files(root: Path, newer_than: float = 0.0) -> list[Path]:
    """列出 Claude 日志根目录下最近修改的 JSONL 文件。"""
    if not root.exists():
        return []

    # paths 存储符合时间条件的候选 Claude JSONL 日志文件。
    paths: list[Path] = []
    for path in root.glob("*/*.jsonl"):
        try:
            if path.stat().st_mtime >= newer_than:
                paths.append(path)
        except OSError:
            continue
    return sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True)


def find_jsonl_containing_text(
    root: Path, text: str, newer_than: float = 0.0
) -> Optional[Path]:
    """在 Claude JSONL 日志树中查找包含指定文本标记的会话文件。"""
    # needle 是本轮消息唯一标记的字节形式，用于快速文件包含判断。
    needle = text.encode("utf-8")
    for path in recent_jsonl_files(root, newer_than=newer_than):
        try:
            if needle in path.read_bytes():
                return path
        except OSError:
            continue
    return None


def message_content_to_text(content: object) -> str:
    """从 Claude JSONL 的 message.content 字段提取纯文本回答。"""
    if isinstance(content, str):
        return content.strip()

    # parts 收集 Claude assistant content 列表里的所有 text 块。
    parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
    return "\n".join(parts).strip()


def is_final_assistant_message(message: dict) -> bool:
    """判断 Claude assistant 消息是否已经结束本轮而不是即将调用工具。"""
    # stop_reason 存储 Claude 对当前 assistant 消息的停止原因。
    stop_reason = message.get("stop_reason")
    if stop_reason is None:
        return True
    return stop_reason == "end_turn"


def extract_assistant_text(log_path: Path, since_iso: str) -> Optional[str]:
    """读取指定时间之后最后一条 assistant 文本消息。"""
    # since_ts 是本轮提问开始时间，用来排除历史回答。
    since_ts = parse_iso_timestamp(since_iso)
    # latest_text 保存时间窗口内最新的 assistant 文本。
    latest_text: Optional[str] = None
    # latest_ts 保存 latest_text 对应的日志时间戳。
    latest_ts = since_ts

    if not log_path.exists():
        return None

    with log_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # 只读取 assistant 消息，跳过 user、tool、配置变更等日志行。
            if entry.get("type") != "assistant":
                continue

            # message 存储 Claude JSONL 里的 assistant 消息主体。
            message = entry.get("message", {})
            if not isinstance(message, dict):
                continue

            if not is_final_assistant_message(message):
                continue

            # timestamp 是 Claude JSONL 当前行的发生时间。
            timestamp = entry.get("timestamp")
            if not isinstance(timestamp, str):
                continue

            try:
                # entry_ts 是当前 assistant 行转换后的 Unix 秒时间戳。
                entry_ts = parse_iso_timestamp(timestamp)
            except ValueError:
                continue

            # 旧于本轮请求或旧于已记录回答的日志行不应覆盖最新答案。
            if entry_ts < since_ts or entry_ts < latest_ts:
                continue

            # text 是从当前 assistant content 中抽出的纯文本内容。
            text = message_content_to_text(message.get("content"))
            if text:
                latest_text = text
                latest_ts = entry_ts

    return latest_text


def extract_streaming_assistant_text(log_path: Path, since_iso: str) -> Optional[str]:
    """读取本轮最新的 assistant 文本，含尚未终稿的中间块，供流式卡片增量推送。

    与 extract_assistant_text 的区别：本函数不跳过 stop_reason 非 end_turn 的中间块，
    这样卡片能在 Claude 还没结束本轮时就把已产出的文字先冒出来。
    """
    # since_ts 是本轮提问开始时间，用来排除历史回答。
    since_ts = parse_iso_timestamp(since_iso)
    # latest_text 保存时间窗口内最新的 assistant 文本（可能来自中间块）。
    latest_text: Optional[str] = None
    # latest_ts 保存 latest_text 对应的日志时间戳。
    latest_ts = since_ts

    if not log_path.exists():
        return None

    with log_path.open("r", encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            # 只读取 assistant 消息，跳过 user、tool、配置变更等日志行。
            if entry.get("type") != "assistant":
                continue

            # message 存储 Claude JSONL 里的 assistant 消息主体。
            message = entry.get("message", {})
            if not isinstance(message, dict):
                continue

            # timestamp 是 Claude JSONL 当前行的发生时间。
            timestamp = entry.get("timestamp")
            if not isinstance(timestamp, str):
                continue

            try:
                # entry_ts 是当前 assistant 行转换后的 Unix 秒时间戳。
                entry_ts = parse_iso_timestamp(timestamp)
            except ValueError:
                continue

            # 旧于本轮请求或旧于已记录文本的日志行不应覆盖最新内容。
            if entry_ts < since_ts or entry_ts < latest_ts:
                continue

            # text 是从当前 assistant content 中抽出的纯文本内容。
            text = message_content_to_text(message.get("content"))
            if text:
                latest_text = text
                latest_ts = entry_ts

    return latest_text
