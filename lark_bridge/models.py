"""models 模块。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class LarkMessage:
    """保存一条可交给 Claude 处理的飞书文本消息。"""

    # event_id 用于飞书事件去重；没有 event_id 时会退化为 message_id。
    event_id: str
    # message_id 是飞书原消息 ID，回复时必须带上它。
    message_id: str
    # sender_id 是发送者 open_id，用于日志记录和后续按人过滤扩展。
    sender_id: str
    # chat_id 是消息所在会话 ID，便于后续扩展主动发送或按会话分流。
    chat_id: str
    # text 是已清洗的飞书文本消息正文。
    text: str
    # chat_type 记录 p2p/group，便于后续按会话类型扩展策略。
    chat_type: str
    # message_type 记录 text/image/file/audio 等原始飞书消息类型。
    message_type: str = "text"
    # attachment_paths 存储从飞书下载到本机、可交给 Claude 分析的附件路径。
    attachment_paths: tuple[str, ...] = ()
    # quoted_text 存储用户引用回复的原消息内容。
    quoted_text: str = ""


@dataclass(frozen=True)
class BotCommand:
    """保存飞书用户输入的斜杠命令。"""

    # name 存储命令名，不包含前导斜杠。
    name: str
    # args 存储命令名后面的原始参数文本。
    args: str


@dataclass
class ClaudeTask:
    """保存一个独立 Claude 任务会话的状态。"""

    # task_id 存储任务短 ID，例如 t1。
    task_id: str
    # title 存储用户给任务起的标题。
    title: str
    # workspace 存储该任务独立 Claude 会话的工作目录。
    workspace: Path
    # session 存储该任务懒启动后的 Claude 会话对象。
    session: Optional[object] = None
    # session_id 存储该任务对应 Claude 会话的 UUID，用于关机重启后 --resume 续接同一会话。
    session_id: str = ""
    # status 存储任务当前状态。
    status: str = "未启动"
    # turns 存储该任务已经完成的问答轮数。
    turns: int = 0
    # last_question 存储最近一次发送给 Claude 的问题。
    last_question: str = ""
    # last_answer 存储最近一次 Claude 返回的回答。
    last_answer: str = ""
    # conversation_history 存储已经完成的问答轮次，每项包含 question 和 answer。
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    # last_error 存储最近一次任务处理错误。
    last_error: str = ""
    # created_at 存储任务创建时间戳。
    created_at: str = ""
    # updated_at 存储任务最近更新时间戳。
    updated_at: str = ""
    # lock 串行化同一个 Claude 任务的 TUI 输入和状态更新，避免多条消息交错。
    lock: Optional[threading.Lock] = None
