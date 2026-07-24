"""claude protocol 模块。"""

from __future__ import annotations

import re
import time
from typing import Optional


from .config import CARD_HISTORY_PAGE_LIMIT
from .config import CARD_HISTORY_PAGE_TURNS
from .config import CARD_PREVIEW_LIMIT
from .config import CLAUDE_CONTEXT_WINDOW
from .config import STREAM_CARD_SUMMARY_ID
from .models import ClaudeTask


def build_claude_args(
    system_prompt: str, session_id: str, resume: bool = False
) -> list[str]:
    """构造交互式 Claude Code 启动参数，避免使用 claude -p/--print。"""
    # session_flag 决定用 --resume 续接已有会话，还是用 --session-id 新建会话。
    # resume 为真表示持久化里已存在该 session_id 对应的 Claude 历史，需要恢复上下文。
    if resume:
        # --resume <id> 默认复用原会话 ID，续接后的对话仍写回同一个 <id>.jsonl，日志定位逻辑不受影响。
        session_flag = ["--resume", session_id]
    else:
        session_flag = ["--session-id", session_id]
    return [
        "claude",
        *session_flag,
        "--permission-mode",
        "bypassPermissions",
        "--append-system-prompt",
        system_prompt,
        "--no-chrome",
    ]


def format_pty_submission(text: str) -> bytes:
    """把多行文本包装成终端粘贴序列。"""
    return b"\x1b[200~" + text.encode("utf-8") + b"\x1b[201~"


def strip_ansi(value: str) -> str:
    """去掉 Claude TUI 输出中的 ANSI 控制序列，便于日志观察。"""
    # ansi_re 匹配常见 ANSI 控制序列和 OSC 序列。
    ansi_re = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[PX^_].*?\x1b\\|\x1b[@-_]")
    return ansi_re.sub("", value)


def should_accept_trust_prompt(screen: str) -> bool:
    """判断 Claude 当前屏幕是否停在专用工作目录信任确认页。"""
    # compact_screen 是去除控制字符和空白后的屏幕文本，适配 TUI 字符间距变化。
    compact_screen = re.sub(r"\s+", "", strip_ansi(screen)).lower()
    # is_workspace_trust 表示 Claude 首次进入工作目录时的信任确认页。
    is_workspace_trust = (
        "quicksafetycheck" in compact_screen
        and "enter" in compact_screen
        and "confirm" in compact_screen
    )
    # is_external_import 表示 Claude 检测到上级 AGENTS/CLAUDE 导入时的确认页。
    is_external_import = (
        "allowexternalclaude.mdfileimports" in compact_screen
        and "externalimports" in compact_screen
    )
    return is_workspace_trust or is_external_import


def parse_claude_stream_event(
    payload: dict,
    answer_text: str,
    thinking_text: str,
) -> tuple[str, str, Optional[str], Optional[str]]:
    """解析一条 Claude stream-json 事件，返回正文、思考、可展示文本和会话 ID。"""
    # session_id 存储事件携带的 Claude 会话 ID，供任务持久化续接。
    session_id = (
        payload.get("session_id")
        if isinstance(payload.get("session_id"), str)
        else None
    )
    if payload.get("type") == "system" and payload.get("subtype") == "api_retry":
        # attempt 存储 Claude 当前上游 API 重试次数。
        attempt = payload.get("attempt")
        return (
            answer_text,
            thinking_text,
            f"Claude 服务繁忙，正在重试（第 {attempt} 次）...",
            session_id,
        )
    if payload.get("type") != "stream_event":
        return answer_text, thinking_text, None, session_id

    # event 存储 Claude API 原始流式事件主体。
    event = payload.get("event")
    if not isinstance(event, dict):
        return answer_text, thinking_text, None, session_id

    # event_type 存储流式事件类型，用来区分 token 增量和工具调用开始。
    event_type = event.get("type")
    if event_type == "content_block_start":
        # content_block 存储刚开始生成的内容块元数据。
        content_block = event.get("content_block")
        if isinstance(content_block, dict) and content_block.get("type") == "tool_use":
            # tool_name 存储 Claude 当前调用的工具名称。
            tool_name = content_block.get("name")
            if isinstance(tool_name, str) and tool_name:
                return (
                    answer_text,
                    thinking_text,
                    f"正在使用工具：{tool_name}...",
                    session_id,
                )
        return answer_text, thinking_text, None, session_id

    if event_type != "content_block_delta":
        return answer_text, thinking_text, None, session_id

    # delta 存储本条 token 增量。
    delta = event.get("delta")
    if not isinstance(delta, dict):
        return answer_text, thinking_text, None, session_id

    # delta_type 存储增量类型，text_delta 是最终正文，thinking_delta 是思考过程。
    delta_type = delta.get("type")
    if delta_type == "text_delta":
        # text_delta 存储本次新增的最终正文 token。
        text_delta = delta.get("text")
        if isinstance(text_delta, str) and text_delta:
            answer_text += text_delta
            return answer_text, thinking_text, answer_text, session_id
    if delta_type == "thinking_delta" and not answer_text:
        # thinking_delta 存储正文生成前新增的思考文本。
        thinking_delta = delta.get("thinking")
        if isinstance(thinking_delta, str) and thinking_delta:
            thinking_text += thinking_delta
            # visible_thinking 只展示最近的思考文本，避免长任务超过飞书卡片内容限制。
            visible_thinking = thinking_text[-2000:]
            return (
                answer_text,
                thinking_text,
                f"思考中：\n{visible_thinking}",
                session_id,
            )
    return answer_text, thinking_text, None, session_id


def friendly_tool_phase(tool_name: str) -> str:
    """把 Claude 工具名转换为适合飞书展示的执行阶段；tool_name 是原始工具名。"""
    # normalized_name 存储用于不区分大小写匹配的工具名。
    normalized_name = tool_name.lower()
    if normalized_name in {"websearch", "webfetch", "grep", "glob"}:
        return "搜索中"
    if normalized_name in {"read", "notebookread"}:
        return "读取文件"
    if normalized_name in {"bash", "write", "edit", "notebookedit"}:
        return "执行命令"
    return f"调用 {tool_name}"


def format_lark_markdown(text: str) -> str:
    """整理 Claude 输出为飞书卡片 Markdown，保留代码块和表格并压缩多余空行。"""
    # normalized 存储统一换行符并移除行尾空白后的文本。
    normalized = "\n".join(
        line.rstrip() for line in text.replace("\r\n", "\n").split("\n")
    )
    # compact 存储最多保留两个连续换行的紧凑文本。
    compact = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    # 未标注语言的代码块补 text，避免飞书把日志内容误判为 Markdown。
    return re.sub(r"```\n", "```text\n", compact)


def compact_stream_preview(content: str) -> str:
    """返回流式卡片默认可见的紧凑预览，保留开头状态和最新输出。"""
    # formatted 存储整理过空行和代码块的流式内容。
    formatted = format_lark_markdown(content)
    if len(formatted) <= CARD_PREVIEW_LIMIT:
        return formatted
    # head 存储任务元数据和回答开头，帮助用户快速判断当前上下文。
    head = formatted[:320].rstrip()
    # tail 存储最近生成的内容，让长任务仍能体现实时变化。
    tail = formatted[-160:].lstrip()
    return f"{head}\n\n_…中间内容已收起…_\n\n{tail}"


def answer_card_content_elements(content: str) -> list[dict]:
    """把回答转换为单个卡片正文元素；content 是需要直接展示的完整内容。"""
    # formatted 存储适合飞书 Markdown 组件显示的完整回答。
    formatted = format_lark_markdown(content)
    return [
        {"tag": "markdown", "content": formatted, "element_id": STREAM_CARD_SUMMARY_ID}
    ]


def conversation_card_content(
    history: list[dict[str, str]],
    question: str = "",
    answer: str = "",
    page: int = 0,
    paginate: bool = True,
) -> str:
    """生成分页对话正文；history 是已完成轮次，当前问答只显示在最新页，page 从零开始。"""
    # normalized_page 存储非负历史页码，零表示最新一页。
    normalized_page = max(0, page) if paginate else 0
    # page_end 存储当前页在历史列表中的右边界。
    page_end = max(0, len(history) - normalized_page * CARD_HISTORY_PAGE_TURNS) if paginate else len(history)
    # page_start 存储当前页在历史列表中的左边界。
    page_start = max(0, page_end - CARD_HISTORY_PAGE_TURNS)
    # turns 存储当前页需要展示的历史副本，避免渲染过程修改任务状态。
    turns = list(history[page_start:page_end])
    if normalized_page == 0 and (question or answer):
        # current_turn 存储尚未写入历史的当前问答。
        current_turn = {"question": question, "answer": answer}
        turns.append(current_turn)
    # blocks 存储按轮次分隔并标注角色的飞书 Markdown。
    blocks = [
        f"**你**\n{format_lark_markdown(str(turn.get('question', '')))}\n\n"
        f"**Claude**\n{format_lark_markdown(str(turn.get('answer', '')))}"
        for turn in turns
        if isinstance(turn, dict)
    ]
    # page_trimmed 标记是否因字符容量隐藏了当前页更早的对话。
    page_trimmed = False
    while len("\n\n---\n\n".join(blocks)) > CARD_HISTORY_PAGE_LIMIT and len(blocks) > 1:
        blocks.pop(0)
        page_trimmed = True
    # content 存储最终连续对话正文。
    content = "\n\n---\n\n".join(blocks) or "这个任务还没有对话，可在下方输入问题开始。"
    if len(content) > CARD_HISTORY_PAGE_LIMIT:
        # 单轮回答过长时保留开头和最新结尾，避免整次卡片更新被飞书拒绝。
        content = f"{content[:2500]}\n\n_…本页中间内容已省略…_\n\n{content[-1300:]}"
        page_trimmed = True
    # visible_turn_count 存储历史加当前轮的总轮数，用于生成准确页码。
    visible_turn_count = len(history) + (
        1 if normalized_page == 0 and (question or answer) else 0
    )
    # total_pages 存储可见问答的总页数，至少为一页。
    total_pages = max(
        1, (visible_turn_count + CARD_HISTORY_PAGE_TURNS - 1) // CARD_HISTORY_PAGE_TURNS
    )
    # page_label 存储用户可理解的倒序页码说明。
    page_label = f"对话记录 · 第 {min(normalized_page + 1, total_pages)}/{total_pages} 页（从新到旧）" if paginate else "对话记录"
    if page_trimmed:
        page_label += " · 本页过长已压缩"
    content = f"_<font color='grey'>{page_label}</font>_\n\n{content}"
    return content


def render_task_progress(task: ClaudeTask, body: str, started_at: float) -> str:
    """渲染任务阶段、耗时、模型、上下文和当前正文。"""
    # elapsed_seconds 存储本轮从开始到当前的整数秒数。
    elapsed_seconds = max(0, int(time.monotonic() - started_at))
    # session 存储当前任务的 Claude 会话对象。
    session = task.session
    # model 存储当前会话报告的模型名称。
    model = getattr(session, "model", "Claude") if session is not None else "Claude"
    # context_tokens 存储当前会话已经使用的上下文 token 数。
    context_tokens = (
        int(getattr(session, "context_tokens", 0) or 0) if session is not None else 0
    )
    # context_window 存储当前模型上下文窗口大小。
    context_window = int(
        getattr(session, "context_window", CLAUDE_CONTEXT_WINDOW)
        or CLAUDE_CONTEXT_WINDOW
    )
    # context_percent 存储上下文使用百分比。
    context_percent = (
        min(100, round(context_tokens * 100 / context_window)) if context_window else 0
    )
    # phase 存储当前 Claude 执行阶段。
    phase = (
        getattr(session, "phase", task.status) if session is not None else task.status
    )
    return (
        f"**{task.task_id} · {task.title}**\n"
        f"`{phase}` · {elapsed_seconds}s · `{model}` · 上下文 {context_percent}%\n\n"
        f"{format_lark_markdown(body)}"
    )


def friendly_error_message(exc: Exception) -> str:
    """把底层异常转换为用户可理解的失败说明，不泄露本机内部错误细节。"""
    if isinstance(exc, InterruptedError):
        return "生成已停止。可以点击“继续”或“重新生成”。"
    # message 存储异常文本，仅用于分类，不直接展示给用户。
    message = str(exc).lower()
    if "503" in message or "overloaded" in message or "service" in message:
        return "Claude 服务暂时繁忙，本次没有完成。请稍后点击“重新生成”。"
    if "permission" in message or "权限" in message:
        return "当前任务需要额外权限才能继续。请检查 Claude Code 或飞书应用权限后重试。"
    if "timeout" in message or "超时" in message:
        return "任务等待时间较长且暂未完成。可以点击“继续”或“重新生成”。"
    return "本次任务没有成功完成。详细原因已写入本机日志，可以点击“查看日志”排查或直接重试。"
