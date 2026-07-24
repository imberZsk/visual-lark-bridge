"""messages 模块。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


from .models import BotCommand
from .models import LarkMessage


# GENERIC_TASK_TITLES 存储不适合作为长期任务名称的常见寒暄文本。
GENERIC_TASK_TITLES = frozenset(
    {"你好", "您好", "你哈", "嗨", "哈喽", "hello", "hi", "在吗", "测试"}
)


def suggest_task_title(text: str, task_number: int) -> str:
    """根据用户问题生成紧凑任务名；text 是原始输入，task_number 用于空内容兜底。"""
    # normalized_text 存储去除首尾空白和连续换行后的标题候选文本。
    normalized_text = " ".join(text.split())
    if not normalized_text or normalized_text.casefold() in GENERIC_TASK_TITLES:
        return f"新对话 {task_number}"
    return preview_text(normalized_text, limit=24)


def should_upgrade_task_title(title: str) -> bool:
    """判断现有标题是否仍是问候语或自动占位名，适合被下一条实质问题替换。"""
    # normalized_title 存储用于识别占位标题的去空白文本。
    normalized_title = title.strip()
    return (
        normalized_title.casefold() in GENERIC_TASK_TITLES
        or normalized_title.startswith("新对话 ")
        or normalized_title.startswith("任务 ")
        or normalized_title == "默认任务"
    )


def normalize_lark_event(event: dict) -> Optional[LarkMessage]:
    """把 lark-cli 输出的消息事件整理为桥接脚本内部消息对象。"""
    # message_type 表示飞书消息类型；桥接支持文本和常见媒体附件。
    message_type = event.get("message_type")
    if message_type not in {"text", "post", "image", "file", "audio", "video", "media"}:
        return None

    # message_id 是飞书原消息 ID；部分旧事件用 id 作为兼容字段。
    message_id = event.get("message_id") or event.get("id")
    # content 是 lark-cli 已预渲染的人类可读消息内容。
    content = event.get("content")
    # sender_id 是发送者 open_id，主要用于日志与将来过滤。
    sender_id = event.get("sender_id", "")
    # chat_id 是消息所在会话 ID，当前用于记录上下文并保留后续主动发消息能力。
    chat_id = event.get("chat_id", "")
    # event_id 是飞书事件唯一 ID，用来避免重复处理。
    event_id = event.get("event_id") or message_id
    # chat_type 表示 p2p 或 group，会保存在内部消息对象里。
    chat_type = event.get("chat_type", "")

    if not isinstance(message_id, str) or not message_id:
        return None
    if not isinstance(content, str):
        content = ""
    # normalized_content 存储交给 Claude 的初始消息正文；媒体消息允许正文为空。
    normalized_content = content.strip()
    if not normalized_content and message_type == "text":
        return None
    if not normalized_content:
        normalized_content = f"请分析这条{message_type}消息。"

    return LarkMessage(
        event_id=str(event_id),
        message_id=message_id,
        sender_id=str(sender_id),
        chat_id=str(chat_id),
        text=normalized_content,
        chat_type=str(chat_type),
        message_type=str(message_type),
    )


def parse_bot_command(text: str) -> Optional[BotCommand]:
    """解析飞书用户输入的斜杠命令，普通消息返回 None。"""
    # stripped 存储去掉两端空白后的消息文本。
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None

    # command_text 存储去掉前导斜杠后的命令正文。
    command_text = stripped[1:]
    if not command_text:
        return BotCommand(name="help", args="")

    # parts 存储命令名和参数文本，最多拆成两段以保留原始参数。
    parts = command_text.split(maxsplit=1)
    # name 存储归一化后的命令名。
    name = parts[0].lower()
    # args 存储命令参数，没有参数时为空字符串。
    args = parts[1].strip() if len(parts) > 1 else ""
    return BotCommand(name=name, args=args)


def build_help_text() -> str:
    """构造飞书里 /help 命令返回的用户帮助文案。"""
    return (
        "可用命令：\n"
        "/help 查看这份帮助\n"
        "/new <任务名> 新开一个独立 Claude 任务窗口\n"
        "/tasks 查看所有任务和进度\n"
        "/use <任务ID> 切换当前对话任务\n"
        "/ask <任务ID> <问题> 指定某个任务继续问\n"
        "/status 查看当前任务状态\n"
        "/stop <任务ID> 停止正在生成的任务\n"
        "/rename <任务ID> <新名称> 重命名任务\n"
        "/close <任务ID> 关闭一个任务窗口\n\n"
        "直接发消息会进入当前任务；没有任务时会自动创建 t1。"
    )


def preview_text(text: str, limit: int = 40) -> str:
    """返回适合状态列表展示的单行文本预览。"""
    # one_line 存储去除换行后的紧凑预览文本。
    one_line = " ".join(text.strip().split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1] + "…"


def should_show_processing_placeholder(text: str) -> bool:
    """判断一条飞书输入是否需要先展示 AI 思考中的占位回复。"""
    # command 存储解析出的斜杠命令；普通消息默认需要等待 Claude。
    command = parse_bot_command(text)
    if command is None:
        return True

    # /ask 会进入指定 Claude 任务，通常耗时明显；其它命令都是本地控制命令。
    return command.name == "ask"


def workspace_instruction_text() -> str:
    """返回写给 Claude 工作区的飞书桥接上下文说明。"""
    return (
        "# 飞书 Claude Bridge 工作说明\n\n"
        "这是飞书对话接入的本地 Claude Code 工作区。用户在飞书里说话可能比较口语化，"
        "请先确认请求目标和当前工作区上下文，再执行本机操作。\n\n"
        "协作原则：\n"
        "- 使用用户当前使用的语言回复，优先给适合飞书阅读的清晰短答。\n"
        "- 需要操作文件时先确认目标路径和已有上下文，不要泄露密钥或 token。\n"
        "- 只访问用户明确授权的目录；不确定路径或操作范围时先询问。\n"
        "- 可以在本文件中补充本机项目、知识库和工作目录映射，但不要提交个人路径或敏感信息。\n"
    )


def ensure_workspace_instruction_files(workspace_root: Path) -> None:
    """确保 workspace_root 工作区根目录存在 Claude Code 可识别的上下文说明。"""
    workspace_root.mkdir(parents=True, exist_ok=True)
    # instruction 存储要写入说明文件的统一文本。
    instruction = workspace_instruction_text()
    # instruction_path 存储 Claude Code 实际识别的工作区说明路径。
    instruction_path = workspace_root / "CLAUDE.md"
    if instruction_path.exists():
        return
    instruction_path.write_text(instruction, encoding="utf-8")
