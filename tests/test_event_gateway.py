"""验证 Python 飞书事件网关的凭证和事件转换。"""

import asyncio
import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from Crypto.Cipher import AES

from lark_bridge.event_gateway import (
    AES_NONCE_SIZE,
    ReadyAwareClient,
    build_event_handler,
    decrypt_keychain_secret,
    load_lark_master_key,
    load_profile,
    normalize_card_action,
    normalize_message_event,
    render_message_content,
)


class EventGatewayTest(unittest.TestCase):
    """验证网关不依赖真实飞书连接的纯转换逻辑。"""

    def test_load_lark_master_key_decodes_go_keyring_value(self):
        """Keychain 主密钥应按 go-keyring 的双层 Base64 格式解码。"""
        # master_key 存储测试用的 32 字节 AES 主密钥。
        master_key = bytes(range(32))
        # inner_value 存储第二层 Base64 文本。
        inner_value = base64.b64encode(master_key)
        # stored_value 存储模拟 Keychain 返回的 go-keyring 文本。
        stored_value = "go-keyring-base64:" + base64.b64encode(inner_value).decode(
            "ascii"
        )
        # completed 存储 subprocess.run 的模拟返回值。
        completed = SimpleNamespace(stdout=stored_value)

        with mock.patch(
            "lark_bridge.event_gateway.subprocess.run", return_value=completed
        ):
            result = load_lark_master_key()

        self.assertEqual(result, master_key)

    def test_decrypt_keychain_secret_reads_lark_cli_aes_gcm_format(self):
        """安全引用应按 nonce、密文、认证标签的顺序完成 AES-GCM 解密。"""
        # master_key 存储测试加解密共用的 AES-256 密钥。
        master_key = bytes(range(32))
        # nonce 存储固定长度的测试 AES-GCM 随机数。
        nonce = bytes(range(AES_NONCE_SIZE))
        # cipher 存储用于生成 lark-cli 格式密文的 AES-GCM 加密器。
        cipher = AES.new(master_key, AES.MODE_GCM, nonce=nonce)
        # ciphertext 存储测试应用密钥的密文字节。
        ciphertext, auth_tag = cipher.encrypt_and_digest(b"test-app-secret")
        # encrypted 存储完整的 lark-cli 密钥文件内容。
        encrypted = nonce + ciphertext + auth_tag

        with (
            mock.patch(
                "lark_bridge.event_gateway.Path.home", return_value=Path("/test-home")
            ),
            mock.patch("pathlib.Path.read_bytes", return_value=encrypted),
            mock.patch(
                "lark_bridge.event_gateway.load_lark_master_key",
                return_value=master_key,
            ),
        ):
            result = decrypt_keychain_secret("profile/app-secret")

        self.assertEqual(result, "test-app-secret")

    def test_load_profile_supports_environment_secret(self):
        """profile 应支持读取 lark-cli 配置中的环境变量密钥引用。"""
        # config 存储测试用 lark-cli profile 配置。
        config = {
            "apps": [
                {
                    "name": "bridge",
                    "appId": "cli_test",
                    "appSecret": {"source": "env", "id": "TEST_LARK_SECRET"},
                    "brand": "lark",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            # config_path 存储临时 lark-cli 配置文件路径。
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with mock.patch.dict("os.environ", {"TEST_LARK_SECRET": "secret"}):
                profile = load_profile(config_path, "bridge")

        self.assertEqual(profile["app_id"], "cli_test")
        self.assertEqual(profile["app_secret"], "secret")
        self.assertEqual(profile["brand"], "lark")

    def test_render_message_content_extracts_post_text(self):
        """富文本消息应按节点顺序递归提取可见文字。"""
        # content 存储包含两段文字的飞书富文本 JSON。
        content = json.dumps(
            {"content": [[{"tag": "text", "text": "第一段"}, {"text": "第二段"}]]}
        )

        self.assertEqual(render_message_content("post", content), "第一段\n第二段")

    def test_normalize_message_event_preserves_bridge_protocol(self):
        """消息事件应转换为原桥接主进程消费的扁平字段。"""
        # event 存储模拟 Python SDK 消息事件对象。
        event = SimpleNamespace(
            header=SimpleNamespace(event_id="evt_1", create_time="123"),
            event=SimpleNamespace(
                sender=SimpleNamespace(
                    sender_id=SimpleNamespace(open_id="ou_user"),
                    sender_type="user",
                ),
                message=SimpleNamespace(
                    message_id="om_1",
                    create_time="122",
                    chat_id="oc_1",
                    chat_type="p2p",
                    message_type="text",
                    content='{"text":"你好"}',
                ),
            ),
        )

        payload = normalize_message_event(event)

        self.assertEqual(payload["type"], "im.message.receive_v1")
        self.assertEqual(payload["message_id"], "om_1")
        self.assertEqual(payload["sender_id"], "ou_user")
        self.assertEqual(payload["content"], "你好")

    def test_normalize_card_action_preserves_input_and_form_values(self):
        """卡片回调应保留 Enter 输入、动作参数和表单值。"""
        # event 存储模拟 Python SDK 卡片回调对象。
        event = SimpleNamespace(
            header=SimpleNamespace(event_id="evt_card", create_time="123"),
            event=SimpleNamespace(
                operator=SimpleNamespace(open_id="ou_user"),
                token="token_1",
                host="im_message",
                context=SimpleNamespace(
                    open_message_id="om_card", open_chat_id="oc_chat"
                ),
                action=SimpleNamespace(
                    value={"action": "card_chat_submit"},
                    tag="input",
                    name="chat_send",
                    form_value={"field": "value"},
                    input_value="继续处理",
                    option="",
                    options=["a", "b"],
                    checked=True,
                    timezone="Asia/Shanghai",
                ),
            ),
        )

        payload = normalize_card_action(event)

        self.assertEqual(
            json.loads(payload["action_value"]), {"action": "card_chat_submit"}
        )
        self.assertEqual(json.loads(payload["form_value"]), {"field": "value"})
        self.assertEqual(payload["input_value"], "继续处理")
        self.assertEqual(payload["options"], "a,b")

    def test_ready_client_reports_after_successful_connection(self):
        """网关必须等官方 SDK 连接成功后再向父进程报告 ready。"""
        # client 存储绕过 SDK 初始化、只验证连接包装逻辑的测试客户端。
        client = ReadyAwareClient.__new__(ReadyAwareClient)
        # ready_reported 模拟客户端尚未报告首次连接成功。
        client.ready_reported = False
        # stderr 存储网关写给父进程的启动状态文本。
        stderr = io.StringIO()

        with (
            mock.patch(
                "lark_bridge.event_gateway.lark.ws.Client._connect",
                new=mock.AsyncMock(),
            ) as sdk_connect,
            contextlib.redirect_stderr(stderr),
        ):
            asyncio.run(client._connect())

        sdk_connect.assert_awaited_once()
        self.assertEqual(stderr.getvalue(), "[gateway] ready\n")
        self.assertTrue(client.ready_reported)

    def test_event_handler_registers_message_and_card_callbacks(self):
        """单条 WebSocket 连接的分发器应同时注册消息事件和卡片回调。"""
        # handler 存储官方 SDK 构建出的事件分发器。
        handler = build_event_handler()

        self.assertIn("p2.im.message.receive_v1", handler._processorMap)
        self.assertIn("p2.card.action.trigger", handler._callback_processor_map)


if __name__ == "__main__":
    unittest.main()
