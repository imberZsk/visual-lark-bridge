"""通过飞书官方 Python SDK 接收消息与卡片回调。"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

import lark_oapi as lark
from Crypto.Cipher import AES
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)


# KEYCHAIN_SERVICE 存储 lark-cli 在 macOS Keychain 中使用的服务名称。
KEYCHAIN_SERVICE = "lark-cli"
# KEYCHAIN_ACCOUNT 存储 lark-cli 主密钥在 macOS Keychain 中使用的账户名称。
KEYCHAIN_ACCOUNT = "master.key"
# KEYCHAIN_PREFIX 存储 go-keyring 对 Keychain 文本值添加的编码前缀。
KEYCHAIN_PREFIX = "go-keyring-base64:"
# AES_NONCE_SIZE 存储 lark-cli AES-GCM 密文开头的 nonce 字节数。
AES_NONCE_SIZE = 12
# AES_TAG_SIZE 存储 lark-cli AES-GCM 密文末尾的认证标签字节数。
AES_TAG_SIZE = 16
# AES_KEY_SIZE 存储 AES-256 主密钥要求的字节数。
AES_KEY_SIZE = 32
# SAFE_SECRET_NAME_PATTERN 匹配不能直接用于 lark-cli 密钥文件名的字符。
SAFE_SECRET_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]")


def load_lark_master_key() -> bytes:
    """读取并解码 lark-cli 的 macOS Keychain 主密钥。"""
    # completed 存储 macOS security 命令的执行结果。
    completed = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
            "-w",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # stored_value 存储 Keychain 返回的 go-keyring 编码文本。
    stored_value = completed.stdout.strip()
    # encoded_value 存储去掉 go-keyring 前缀后的双层 Base64 文本。
    encoded_value = stored_value.removeprefix(KEYCHAIN_PREFIX)
    # inner_value 存储第一层 Base64 解码得到的内部 Base64 文本。
    inner_value = base64.b64decode(encoded_value).decode("utf-8").strip()
    # master_key 存储第二层 Base64 解码得到的 AES-256 主密钥。
    master_key = base64.b64decode(inner_value)
    if len(master_key) != AES_KEY_SIZE:
        raise ValueError("lark-cli Keychain 主密钥格式无效")
    return master_key


def decrypt_keychain_secret(secret_id: str) -> str:
    """解密 lark-cli 安全存储文件；secret_id 是配置中的密钥引用 ID。"""
    # safe_name 存储 lark-cli 规则转换后的安全文件名。
    safe_name = SAFE_SECRET_NAME_PATTERN.sub("_", secret_id)
    # encrypted_path 存储 lark-cli AES-GCM 密钥文件路径。
    encrypted_path = (
        Path.home()
        / "Library"
        / "Application Support"
        / "lark-cli"
        / f"{safe_name}.enc"
    )
    # encrypted 存储 nonce、密文和认证标签组成的二进制数据。
    encrypted = encrypted_path.read_bytes()
    if len(encrypted) <= AES_NONCE_SIZE + AES_TAG_SIZE:
        raise ValueError(f"lark-cli 密钥文件格式无效：{secret_id}")
    # nonce 存储密文开头的 AES-GCM 随机数。
    nonce = encrypted[:AES_NONCE_SIZE]
    # ciphertext 存储 nonce 与认证标签之间的密文字节。
    ciphertext = encrypted[AES_NONCE_SIZE:-AES_TAG_SIZE]
    # auth_tag 存储密文末尾的 AES-GCM 认证标签。
    auth_tag = encrypted[-AES_TAG_SIZE:]
    # cipher 存储使用 Keychain 主密钥初始化的 AES-GCM 解密器。
    cipher = AES.new(load_lark_master_key(), AES.MODE_GCM, nonce=nonce)
    # plaintext 存储完成认证并解密后的应用密钥。
    plaintext = cipher.decrypt_and_verify(ciphertext, auth_tag)
    return plaintext.decode("utf-8")


def resolve_app_secret(secret_value: object) -> str:
    """解析明文或安全引用形式的 appSecret 配置。"""
    if isinstance(secret_value, str) and secret_value:
        return secret_value
    if not isinstance(secret_value, dict):
        raise ValueError("飞书应用密钥配置无效")
    # source 存储安全引用的数据来源类型。
    source = secret_value.get("source", "")
    # secret_id 存储安全引用的密钥标识或环境变量名。
    secret_id = secret_value.get("id", "")
    if source == "keychain" and isinstance(secret_id, str) and secret_id:
        return decrypt_keychain_secret(secret_id)
    if source == "env" and isinstance(secret_id, str) and secret_id:
        # environment_value 存储配置指定环境变量中的应用密钥。
        environment_value = os.environ.get(secret_id)
        if environment_value:
            return environment_value
    raise ValueError(f"暂不支持的 lark-cli 密钥来源：{source or 'unknown'}")


def load_profile(config_path: Path, profile_name: str) -> dict[str, str]:
    """读取指定 lark-cli profile；profile_name 可为配置名或 App ID。"""
    # config 存储 lark-cli 配置文件解析后的对象。
    config = json.loads(config_path.read_text(encoding="utf-8"))
    # apps 存储配置中的飞书应用列表。
    apps = config.get("apps", [])
    if not isinstance(apps, list):
        apps = []
    # profile 存储名称或 App ID 与目标匹配的应用配置。
    profile = next(
        (
            app
            for app in apps
            if isinstance(app, dict)
            and (app.get("name") == profile_name or app.get("appId") == profile_name)
        ),
        None,
    )
    if not profile or not profile.get("appId") or not profile.get("appSecret"):
        raise ValueError(f"找不到可用的飞书应用配置：{profile_name}")
    return {
        "app_id": str(profile["appId"]),
        "app_secret": resolve_app_secret(profile["appSecret"]),
        "brand": str(profile.get("brand", "feishu")),
    }


def collect_visible_text(node: object, output: list[str]) -> None:
    """递归提取富文本节点中的可见文字；output 用于收集文字片段。"""
    if isinstance(node, list):
        for item in node:
            collect_visible_text(item, output)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key in {"text", "content"} and isinstance(value, str):
            output.append(value)
            continue
        collect_visible_text(value, output)


def render_message_content(message_type: str, raw_content: str) -> str:
    """将飞书消息 content JSON 转为桥接主进程使用的文本。"""
    try:
        # parsed_content 存储飞书消息 content 解析后的对象。
        parsed_content = json.loads(raw_content or "{}")
    except json.JSONDecodeError:
        return raw_content
    if message_type == "text" and isinstance(parsed_content.get("text"), str):
        return parsed_content["text"]
    if message_type == "post":
        # text_parts 存储从富文本中递归提取到的文字片段。
        text_parts: list[str] = []
        collect_visible_text(parsed_content, text_parts)
        return "\n".join(text_parts)
    return ""


def normalize_message_event(event: Any) -> dict[str, object]:
    """把 Python SDK 消息事件转换为桥接器兼容的扁平事件。"""
    # header 存储飞书事件头信息。
    header = getattr(event, "header", None)
    # event_data 存储消息事件业务数据。
    event_data = getattr(event, "event", None)
    # message 存储飞书消息主体。
    message = getattr(event_data, "message", None)
    # sender 存储飞书消息发送者主体。
    sender = getattr(event_data, "sender", None)
    # sender_id_data 存储发送者的多种用户 ID。
    sender_id_data = getattr(sender, "sender_id", None)
    # message_id 存储当前消息的飞书消息 ID。
    message_id = getattr(message, "message_id", "") or ""
    # message_type 存储当前消息的类型。
    message_type = getattr(message, "message_type", "") or ""
    # raw_content 存储 SDK 返回的消息 content JSON 文本。
    raw_content = getattr(message, "content", "") or ""
    return {
        "type": "im.message.receive_v1",
        "event_id": getattr(header, "event_id", "") or message_id,
        "timestamp": getattr(header, "create_time", "") or "",
        "id": message_id,
        "message_id": message_id,
        "create_time": getattr(message, "create_time", "") or "",
        "chat_id": getattr(message, "chat_id", "") or "",
        "chat_type": getattr(message, "chat_type", "") or "",
        "message_type": message_type,
        "sender_id": getattr(sender_id_data, "open_id", "") or "",
        "sender_type": getattr(sender, "sender_type", "") or "",
        "content": render_message_content(message_type, raw_content),
    }


def normalize_card_action(event: P2CardActionTrigger) -> dict[str, object]:
    """把 Python SDK 卡片回调转换为桥接器兼容的扁平事件。"""
    # header 存储飞书回调事件头信息。
    header = getattr(event, "header", None)
    # event_data 存储卡片回调业务数据。
    event_data = getattr(event, "event", None)
    # context 存储卡片所在消息与会话信息。
    context = getattr(event_data, "context", None)
    # action 存储按钮或输入组件触发的动作信息。
    action = getattr(event_data, "action", None)
    # operator 存储触发回调的用户信息。
    operator = getattr(event_data, "operator", None)
    # message_id 存储卡片所在的飞书消息 ID。
    message_id = getattr(context, "open_message_id", "") or ""
    # action_value 存储开发者配置的卡片动作参数。
    action_value = getattr(action, "value", None) or {}
    # form_value 存储卡片表单字段对象。
    form_value = getattr(action, "form_value", None)
    # options 存储多选组件选中的值列表。
    options = getattr(action, "options", None)
    return {
        "type": "card.action.trigger",
        "event_id": getattr(header, "event_id", "") or message_id,
        "timestamp": getattr(header, "create_time", "") or "",
        "operator_id": getattr(operator, "open_id", "") or "",
        "message_id": message_id,
        "chat_id": getattr(context, "open_chat_id", "") or "",
        "host": getattr(event_data, "host", "") or "im_message",
        "token": getattr(event_data, "token", "") or "",
        "action_tag": getattr(action, "tag", "") or "",
        "action_value": json.dumps(action_value, ensure_ascii=False),
        "action_name": getattr(action, "name", "") or "",
        "form_value": ""
        if form_value is None
        else json.dumps(form_value, ensure_ascii=False),
        "input_value": getattr(action, "input_value", "") or "",
        "option": getattr(action, "option", "") or "",
        "options": ",".join(options) if isinstance(options, list) else options or "",
        "checked": bool(getattr(action, "checked", False)),
        "timezone": getattr(action, "timezone", "") or "",
    }


def emit_event(payload: dict[str, object]) -> None:
    """把扁平事件以单行 NDJSON 写给桥接主进程。"""
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def build_event_handler() -> Any:
    """创建同时注册消息事件与卡片回调的官方 SDK 分发器。"""

    def handle_message(event: Any) -> None:
        """确认消息事件前将其写入主进程事件流。"""
        emit_event(normalize_message_event(event))

    def handle_card_action(event: P2CardActionTrigger) -> P2CardActionTriggerResponse:
        """确认卡片回调前将其写入主进程事件流。"""
        emit_event(normalize_card_action(event))
        return P2CardActionTriggerResponse()

    # builder 存储飞书官方 SDK 的事件分发器构建器。
    builder = lark.EventDispatcherHandler.builder("", "")
    return (
        builder.register_p2_im_message_receive_v1(handle_message)
        .register_p2_card_action_trigger(handle_card_action)
        .build()
    )


class ReadyAwareClient(lark.ws.Client):
    """在官方 SDK 完成首次 WebSocket 握手后向父进程报告就绪。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        """初始化客户端；args 和 kwargs 原样传给官方 SDK 客户端。"""
        super().__init__(*args, **kwargs)
        # ready_reported 标记是否已经向父进程发送过首次连接就绪信号。
        self.ready_reported = False

    async def _connect(self) -> None:
        """连接官方 WebSocket，并在首次成功后输出父进程识别的 ready 标记。"""
        # 官方 SDK 1.7.1 没有公开连接成功回调；固定版本下覆盖连接协程可避免握手前误报就绪。
        await super()._connect()
        if not self.ready_reported:
            print("[gateway] ready", file=sys.stderr, flush=True)
            self.ready_reported = True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析网关参数；argv 允许测试传入独立参数列表。"""
    # parser 存储 Python 网关的命令行参数定义。
    parser = argparse.ArgumentParser(description="飞书 WebSocket 事件网关")
    parser.add_argument("--config", required=True, help="lark-cli 配置文件路径")
    parser.add_argument(
        "--profile", required=True, help="lark-cli profile 名称或 App ID"
    )
    return parser.parse_args(argv)


def main() -> NoReturn:
    """读取应用凭证并启动飞书官方 Python SDK 长连接。"""
    # args 存储完成解析的网关命令行参数。
    args = parse_args()
    # profile 存储目标飞书应用的 App ID、密钥和品牌。
    profile = load_profile(Path(args.config).expanduser().resolve(), args.profile)
    # domain 存储飞书或 Lark 对应的开放平台域名。
    domain = lark.LARK_DOMAIN if profile["brand"] == "lark" else lark.FEISHU_DOMAIN
    # client 存储飞书官方 Python SDK WebSocket 客户端。
    client = ReadyAwareClient(
        profile["app_id"],
        profile["app_secret"],
        event_handler=build_event_handler(),
        domain=domain,
        log_level=lark.LogLevel.ERROR,
    )

    def stop_gateway(_signum: int, _frame: object) -> None:
        """收到终止信号时退出网关，由 SDK 连接随进程一并关闭。"""
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop_gateway)
    signal.signal(signal.SIGINT, stop_gateway)
    client.start()
    raise SystemExit(0)


if __name__ == "__main__":
    main()
