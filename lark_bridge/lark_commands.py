"""构造 lark-cli 与 Python 网关子进程命令并解析响应。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional


from .cards import answer_card_actions
from .cards import answer_card_input_form
from .config import DEFAULT_PROCESSING_TEXT
from .config import STREAM_CARD_META_ID
from .config import STREAM_CARD_SUMMARY_ID
import sys


def prepend_lark_profile(args: list[str], profile: Optional[str]) -> list[str]:
    """在 lark-cli argv 中注入 profile，profile 为空时保持原参数不变。"""
    if not profile:
        return args

    return ["lark-cli", "--profile", profile, *args[1:]]


def build_lark_profile_list_args() -> list[str]:
    """构造读取本机 lark-cli profile 列表的命令参数。"""
    return ["lark-cli", "profile", "list"]


def parse_lark_profile_names(output: str) -> set[str]:
    """从 lark-cli profile list 输出中解析 profile 名称集合。"""
    try:
        # profiles 存储 lark-cli 输出解析后的 profile 列表。
        profiles = json.loads(output)
    except json.JSONDecodeError:
        return set()

    if not isinstance(profiles, list):
        return set()

    # names 存储从 profile 对象中提取出的名称集合。
    names: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        # name 是当前 profile 的名称字段。
        name = profile.get("name")
        if isinstance(name, str) and name:
            names.add(name)
    return names


def ensure_lark_profile_exists(profile: Optional[str]) -> None:
    """确认指定 lark-cli profile 存在，避免启动后误连默认机器人。"""
    if not profile:
        return

    # completed 保存 profile 列表命令执行结果，用于判断本机是否已配置目标机器人。
    completed = subprocess.run(
        build_lark_profile_list_args(),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"无法读取 lark-cli profile 列表：{completed.stderr.strip()}"
        )

    # profile_names 存储本机已配置的 lark-cli profile 名称。
    profile_names = parse_lark_profile_names(completed.stdout)
    if profile in profile_names:
        return

    # available 存储错误消息中展示的已有 profile 名称。
    available = ", ".join(sorted(profile_names)) or "无"
    raise RuntimeError(
        f'lark-cli profile "{profile}" 未配置；当前可用 profile：{available}。'
        f"请先为 Claude 桥接机器人添加 profile。"
    )


def build_lark_reply_args(
    message_id: str,
    text: str,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造飞书回复命令参数数组，关键参数为原消息 ID 和回复文本。"""
    # args 存储不含 profile 覆盖的基础 lark-cli 回复命令。
    args = [
        "lark-cli",
        "im",
        "+messages-reply",
        "--message-id",
        message_id,
        "--text",
        text,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_send_chat_message_args(
    chat_id: str,
    markdown: str,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造向指定飞书会话主动发送 Markdown 的命令参数。"""
    # args 存储不含 profile 覆盖的主动发送命令。
    args = [
        "lark-cli", "im", "+messages-send", "--chat-id", chat_id,
        "--markdown", markdown, "--as", identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_update_message_args(
    message_id: str,
    text: str,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造飞书编辑机器人已发文本消息的原生 OpenAPI 命令参数。"""
    # content 存储飞书 text 消息要求的 JSON 字符串内容。
    content = json.dumps({"text": text}, ensure_ascii=False)
    # data 存储编辑消息接口要求的请求体 JSON 字符串。
    data = json.dumps({"msg_type": "text", "content": content}, ensure_ascii=False)
    # args 存储不含 profile 覆盖的基础 lark-cli 原生 API 编辑命令。
    args = [
        "lark-cli",
        "api",
        "PUT",
        f"/open-apis/im/v1/messages/{message_id}",
        "--data",
        data,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_create_card_args(
    identity: str = "bot",
    profile: Optional[str] = None,
    task_id: str = "",
    source_message_id: str = "",
    initial_content: str = DEFAULT_PROCESSING_TEXT,
) -> list[str]:
    """构造流式卡片命令；任务参数写入回调值，initial_content 是初始正文。"""
    # card 存储 cardkit v2 卡片 JSON，config.streaming_mode 打开逐字流式渲染。
    card = {
        "schema": "2.0",
        "config": {
            "streaming_mode": True,
            "width_mode": "default",
            "summary": {"content": "Claude 任务进行中"},
        },
        "header": {
            "title": {"tag": "plain_text", "content": "Claude Code"},
            "subtitle": {"tag": "plain_text", "content": "本地任务实时进度"},
            "template": "blue",
            "icon": {"tag": "standard_icon", "token": "myai_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "large",
            "elements": [
                # 元数据头独立成元素，与正文分离，避免其每帧变化打断正文的流式公共前缀 diff。
                {
                    "tag": "markdown",
                    "content": "",
                    "element_id": STREAM_CARD_META_ID,
                },
                # 建卡时先显示处理状态，避免 Claude 首个 token 到达前飞书出现大块空白。
                {
                    "tag": "markdown",
                    "content": initial_content,
                    "element_id": STREAM_CARD_SUMMARY_ID,
                },
                answer_card_input_form(task_id),
                *answer_card_actions(task_id, source_message_id),
            ],
        },
    }
    # data 存储创建卡片接口要求的请求体：card_json 类型 + 卡片 JSON 字符串。
    data = json.dumps(
        {"type": "card_json", "data": json.dumps(card, ensure_ascii=False)},
        ensure_ascii=False,
    )
    # args 存储不含 profile 覆盖的基础 lark-cli 创建卡片命令。
    args = [
        "lark-cli",
        "api",
        "POST",
        "/open-apis/cardkit/v1/cards",
        "--data",
        data,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_create_custom_card_args(
    card: dict,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造创建任意 Card 2.0 实体的命令；card 是完整卡片 JSON。"""
    # data 存储创建卡片接口要求的 card_json 请求体。
    data = json.dumps(
        {"type": "card_json", "data": json.dumps(card, ensure_ascii=False)},
        ensure_ascii=False,
    )
    # args 存储不含 profile 覆盖的创建卡片命令。
    args = [
        "lark-cli",
        "api",
        "POST",
        "/open-apis/cardkit/v1/cards",
        "--data",
        data,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_send_card_args(
    message_id: str,
    card_id: str,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造回复一条引用流式卡片实体的 interactive 消息命令参数。"""
    # content 存储 interactive 卡片消息要求的 content JSON，用 card_id 引用已创建的卡片实体。
    content = json.dumps(
        {"type": "card", "data": {"card_id": card_id}}, ensure_ascii=False
    )
    # args 存储不含 profile 覆盖的基础 lark-cli 卡片回复命令。
    args = [
        "lark-cli",
        "im",
        "+messages-reply",
        "--message-id",
        message_id,
        "--msg-type",
        "interactive",
        "--content",
        content,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_delayed_card_update_args(
    token: str,
    card: dict,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造卡片按钮回调后的延迟更新命令；token 来自 card.action.trigger。"""
    # data 存储飞书延迟更新接口要求的完整卡片请求体。
    data = json.dumps({"token": token, "card": card}, ensure_ascii=False)
    # args 存储不含 profile 覆盖的延迟更新命令。
    args = [
        "lark-cli",
        "api",
        "POST",
        "/open-apis/interactive/v1/card/update",
        "--data",
        data,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_stream_content_args(
    card_id: str,
    content: str,
    sequence: int,
    element_id: str = STREAM_CARD_SUMMARY_ID,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造往流式卡片元素覆盖写入文本的原生 OpenAPI 命令参数。"""
    # data 存储流式文本更新接口的请求体；sequence 必须递增，飞书据此保证多次更新的顺序。
    data = json.dumps({"content": content, "sequence": sequence}, ensure_ascii=False)
    # args 存储不含 profile 覆盖的基础 lark-cli 流式文本更新命令。
    args = [
        "lark-cli",
        "api",
        "PUT",
        f"/open-apis/cardkit/v1/cards/{card_id}/elements/{element_id}/content",
        "--data",
        data,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_replace_element_args(
    card_id: str,
    element_id: str,
    element: dict,
    sequence: int,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造替换 CardKit 组件的命令；element 是完整新组件，sequence 必须严格递增。"""
    # data 存储更新组件接口要求的序列化组件和更新序号。
    data = json.dumps(
        {"element": json.dumps(element, ensure_ascii=False), "sequence": sequence},
        ensure_ascii=False,
    )
    # args 存储不含 profile 覆盖的基础 CardKit 组件替换命令。
    args = [
        "lark-cli",
        "api",
        "PUT",
        f"/open-apis/cardkit/v1/cards/{card_id}/elements/{element_id}",
        "--data",
        data,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_finish_stream_args(
    card_id: str,
    sequence: int,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造关闭流式模式、给卡片定稿的原生 OpenAPI 命令参数。"""
    # settings 存储卡片设置对象，关掉 streaming_mode 表示本轮流式输出结束定稿。
    # 飞书要求 settings 字段本身是 JSON 字符串而非对象，直接传对象会报 9499 参数类型错误。
    settings = json.dumps({"config": {"streaming_mode": False}}, ensure_ascii=False)
    # data 存储卡片设置更新请求体：settings 是序列化后的字符串，sequence 保证与流式追加的先后顺序。
    data = json.dumps(
        {"settings": settings, "sequence": sequence},
        ensure_ascii=False,
    )
    # args 存储不含 profile 覆盖的基础 lark-cli 卡片设置更新命令。
    args = [
        "lark-cli",
        "api",
        "PATCH",
        f"/open-apis/cardkit/v1/cards/{card_id}/settings",
        "--data",
        data,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_stream_mode_args(
    card_id: str,
    sequence: int,
    enabled: bool,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造开启或关闭卡片流式模式的命令；enabled 控制目标状态。"""
    # settings 存储飞书要求的序列化卡片流式设置。
    settings = json.dumps({"config": {"streaming_mode": enabled}}, ensure_ascii=False)
    # data 存储卡片设置更新请求体。
    data = json.dumps({"settings": settings, "sequence": sequence}, ensure_ascii=False)
    # args 存储不含 profile 覆盖的卡片设置命令。
    args = [
        "lark-cli",
        "api",
        "PATCH",
        f"/open-apis/cardkit/v1/cards/{card_id}/settings",
        "--data",
        data,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def extract_card_id(output: str) -> Optional[str]:
    """从 lark-cli 创建卡片的 JSON 输出里提取 card_id。"""
    try:
        # payload 存储 lark-cli stdout 解析后的 JSON 对象。
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    # data 存储飞书响应里的业务数据对象。
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    # card_id 是新建流式卡片实体的 ID。
    card_id = data.get("card_id")
    if isinstance(card_id, str) and card_id:
        return card_id
    return None


def extract_sent_message_id(output: str) -> Optional[str]:
    """从 lark-cli 发消息或回复消息的 JSON 输出里提取新消息 ID。"""
    try:
        # payload 存储 lark-cli stdout 解析后的 JSON 对象。
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    # data 存储飞书响应里的业务数据对象。
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    # message_id 存储刚发送成功的机器人消息 ID。
    message_id = data.get("message_id")
    if isinstance(message_id, str) and message_id:
        return message_id
    return None


def build_lark_consume_args(
    identity: str,
    profile: Optional[str] = None,
    event_key: str = "im.message.receive_v1",
) -> list[str]:
    """构造飞书事件消费命令参数；event_key 指定消息或卡片回调事件。"""
    # args 存储不含 profile 覆盖的基础 lark-cli 事件监听命令。
    args = [
        "lark-cli",
        "event",
        "consume",
        event_key,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_gateway_args(
    gateway_path: Path,
    config_path: Path,
    profile: str,
) -> list[str]:
    """构造官方 SDK 网关命令；gateway_path 可为 Python 脚本或独立可执行文件。"""
    # gateway_command 存储脚本或打包 sidecar 对应的启动命令。
    gateway_command = (
        [sys.executable, str(gateway_path)]
        if gateway_path.suffix == ".py"
        else [str(gateway_path)]
    )
    return [
        *gateway_command,
        "--config",
        str(config_path),
        "--profile",
        profile,
    ]


def build_lark_message_get_args(
    message_id: str,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造读取单条飞书消息最新内容的命令；message_id 是消息 ID。"""
    # args 存储不含 profile 覆盖的消息批量读取命令。
    args = [
        "lark-cli",
        "im",
        "+messages-mget",
        "--message-ids",
        message_id,
        "--no-reactions",
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_lark_resource_download_args(
    message_id: str,
    file_key: str,
    resource_type: str,
    output_path: str,
    identity: str = "bot",
    profile: Optional[str] = None,
) -> list[str]:
    """构造飞书消息资源下载命令；file_key 是资源键，output_path 必须是相对路径。"""
    # args 存储不含 profile 覆盖的资源下载命令。
    args = [
        "lark-cli",
        "im",
        "+messages-resources-download",
        "--message-id",
        message_id,
        "--file-key",
        file_key,
        "--type",
        resource_type,
        "--output",
        output_path,
        "--as",
        identity,
    ]
    return prepend_lark_profile(args, profile)


def build_stdin_keeper_args() -> list[str]:
    """构造保持 lark-cli event consume stdin 不 EOF 的命令参数。"""
    return ["tail", "-f", "/dev/null"]
