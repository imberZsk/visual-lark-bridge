"""CoreTest 职责测试。"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from visual_lark_bridge import (
    BotCommand,
    DEFAULT_LARK_PROFILE,
    STREAM_CARD_SUMMARY_ID,
    answer_card_content_elements,
    answer_card_input_form,
    build_lark_consume_args,
    build_lark_gateway_args,
    build_help_text,
    build_lark_profile_list_args,
    build_lark_reply_args,
    build_lark_stream_content_args,
    build_stdin_keeper_args,
    build_lark_update_message_args,
    default_base_dir,
    extract_sent_message_id,
    ensure_workspace_instruction_files,
    normalize_lark_event,
    parse_bot_command,
    parse_lark_profile_names,
    should_show_processing_placeholder,
    workspace_instruction_text,
)


class CoreTest(unittest.TestCase):
    def test_default_lark_profile_comes_from_environment(self):
        """模块默认 profile 应读取本机环境，避免发布代码绑定开发者个人 App ID。"""
        # module_dir 存储桥接模块所在目录，供隔离子进程导入当前待测代码。
        module_dir = default_base_dir()
        # child_env 存储隔离子进程使用的环境变量副本和测试 profile。
        child_env = {**os.environ, "LARK_PROFILE": "test-open-source-profile"}
        # completed 存储子进程导入模块后输出的默认 profile。
        completed = subprocess.run(
            [
                "python3",
                "-c",
                "import visual_lark_bridge; print(visual_lark_bridge.DEFAULT_LARK_PROFILE)",
            ],
            cwd=module_dir,
            env=child_env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "test-open-source-profile")

    def test_default_base_dir_follows_module_location_after_move(self):
        """默认目录应跟随脚本所在目录，避免移动脚本后仍写旧路径。"""
        base_dir = default_base_dir()

        # expected_dir 按被测模块文件实际所在目录动态推导，移动项目目录后仍成立，避免硬编码绝对路径。
        expected_dir = (
            Path(default_base_dir.__globals__["__file__"]).resolve().parent.parent
        )
        self.assertEqual(base_dir, expected_dir)

    def test_normalize_lark_event_accepts_text_message(self):
        """应从飞书文本事件里提取消息 ID、正文和发送人。"""
        event = {
            "event_id": "evt_1",
            "message_id": "om_abc",
            "message_type": "text",
            "content": "你好",
            "sender_id": "ou_user",
            "chat_type": "p2p",
            "chat_id": "oc_chat",
        }

        message = normalize_lark_event(event)

        self.assertEqual(message.message_id, "om_abc")
        self.assertEqual(message.text, "你好")
        self.assertEqual(message.sender_id, "ou_user")
        self.assertEqual(message.chat_id, "oc_chat")

    def test_normalize_lark_event_accepts_image_message(self):
        """图片消息应保留资源标记并送入后续附件下载流程。"""
        event = {
            "event_id": "evt_1",
            "message_id": "om_abc",
            "message_type": "image",
            "content": "[图片]",
            "sender_id": "ou_user",
        }

        # message 存储归一化后的图片消息。
        message = normalize_lark_event(event)
        self.assertIsNotNone(message)
        self.assertEqual(message.message_type, "image")

    def test_build_lark_reply_args_uses_argv_not_shell_string(self):
        """回复命令应以 argv 形式传参，避免消息内容被 shell 解释。"""
        args = build_lark_reply_args("om_abc", "hello; rm -rf /")

        self.assertEqual(
            args[:4], ["lark-cli", "im", "+messages-reply", "--message-id"]
        )
        self.assertIn("hello; rm -rf /", args)
        self.assertIn("--as", args)
        self.assertIn("bot", args)

    def test_build_lark_reply_args_can_pin_profile(self):
        """回复命令应能显式指定 lark-cli profile，避免误用当前默认机器人。"""
        args = build_lark_reply_args("om_abc", "你好", profile=DEFAULT_LARK_PROFILE)

        self.assertEqual(args[:3], ["lark-cli", "--profile", DEFAULT_LARK_PROFILE])
        self.assertIn("+messages-reply", args)

    def test_build_lark_update_message_args_uses_official_update_api(self):
        """占位回复替换应使用飞书官方编辑消息接口和文本消息体。"""
        # args 存储编辑机器人占位消息的 lark-cli 原生 API 参数。
        args = build_lark_update_message_args(
            "om_reply", "完成", profile=DEFAULT_LARK_PROFILE
        )
        # data_index 存储 --data 后面 JSON 字符串所在的位置。
        data_index = args.index("--data") + 1
        # data 存储解析后的原生 API 请求体。
        data = json.loads(args[data_index])

        self.assertEqual(args[:3], ["lark-cli", "--profile", DEFAULT_LARK_PROFILE])
        self.assertIn("api", args)
        self.assertIn("PUT", args)
        self.assertIn("/open-apis/im/v1/messages/om_reply", args)
        self.assertEqual(data["msg_type"], "text")
        self.assertEqual(json.loads(data["content"]), {"text": "完成"})

    def test_extract_sent_message_id_reads_reply_output(self):
        """应从 lark-cli 发送回复后的 JSON 输出中提取新消息 ID。"""
        # output 存储 lark-cli im +messages-reply 成功后的简化输出。
        output = json.dumps({"code": 0, "data": {"message_id": "om_new_reply"}})

        self.assertEqual(extract_sent_message_id(output), "om_new_reply")

    def test_should_show_processing_placeholder_for_long_running_turns(self):
        """普通消息和 /ask 应展示 AI 思考中，控制命令不展示。"""
        self.assertTrue(should_show_processing_placeholder("你好"))
        self.assertTrue(should_show_processing_placeholder("/ask t1 继续排查"))
        self.assertFalse(should_show_processing_placeholder("/help"))
        self.assertFalse(should_show_processing_placeholder("/tasks"))

    def test_build_lark_consume_args_can_pin_profile(self):
        """事件监听命令应能显式指定 lark-cli profile，确保监听正确机器人。"""
        # args 存储带 profile 覆盖的事件监听命令参数。
        args = build_lark_consume_args("bot", profile=DEFAULT_LARK_PROFILE)

        self.assertEqual(args[:3], ["lark-cli", "--profile", DEFAULT_LARK_PROFILE])
        self.assertIn("im.message.receive_v1", args)

    def test_build_lark_gateway_args_uses_single_official_sdk_process(self):
        """事件网关命令应同时获得入口、配置和 profile，供单长连接注册两类事件。"""
        # gateway_path 存储测试用 Python 网关入口路径。
        gateway_path = Path("/runtime/lark_bridge/event_gateway.py")
        # config_path 存储测试用 lark-cli 配置路径。
        config_path = Path("/home/user/.lark-cli/config.json")

        # args 存储构造出的单长连接网关命令。
        args = build_lark_gateway_args(gateway_path, config_path, DEFAULT_LARK_PROFILE)

        self.assertEqual(args[0], sys.executable)
        self.assertEqual(args[1], str(gateway_path))
        self.assertIn(str(config_path), args)
        self.assertIn(DEFAULT_LARK_PROFILE, args)

    def test_build_lark_gateway_args_runs_packaged_sidecar_directly(self):
        """打包后的网关二进制应直接执行，不能再交给 Python 解释器。"""
        # gateway_path 存储测试用独立网关可执行文件路径。
        gateway_path = Path("/runtime/lark-event-gateway")
        # config_path 存储测试用 lark-cli 配置路径。
        config_path = Path("/home/user/.lark-cli/config.json")

        # args 存储独立网关的启动命令。
        args = build_lark_gateway_args(gateway_path, config_path, DEFAULT_LARK_PROFILE)

        self.assertEqual(args[0], str(gateway_path))
        self.assertNotIn(sys.executable, args)

    def test_build_lark_profile_list_args(self):
        """profile 预检应使用 lark-cli profile list 读取本机已配置机器人。"""
        # args 存储 profile 列表命令参数。
        args = build_lark_profile_list_args()

        self.assertEqual(args, ["lark-cli", "profile", "list"])

    def test_parse_lark_profile_names_reads_json_profile_list(self):
        """应从 lark-cli profile list 的 JSON 输出中解析 profile 名称。"""
        # output 存储 lark-cli profile list 返回的 JSON 文本。
        output = json.dumps(
            [
                {"name": "cli_aaad1bbaa2b9dbd6", "appId": "cli_aaad1bbaa2b9dbd6"},
                {"name": DEFAULT_LARK_PROFILE, "appId": DEFAULT_LARK_PROFILE},
            ]
        )

        # names 存储解析出的 profile 名称集合。
        names = parse_lark_profile_names(output)

        self.assertEqual(names, {"cli_aaad1bbaa2b9dbd6", DEFAULT_LARK_PROFILE})

    def test_build_stdin_keeper_args_matches_reference_bot_pattern(self):
        """事件消费应使用永不 EOF 的 stdin 保持 lark-cli 长连接。"""
        # args 存储 stdin 保活命令参数。
        args = build_stdin_keeper_args()

        self.assertEqual(args, ["tail", "-f", "/dev/null"])

    def test_parse_bot_command_reads_slash_command_and_args(self):
        """应能把飞书里的斜杠命令解析成命令名和参数文本。"""
        # command 存储解析后的 bot 命令对象。
        command = parse_bot_command(" /new 写周报 ")

        self.assertEqual(command, BotCommand(name="new", args="写周报"))

    def test_parse_bot_command_ignores_plain_message(self):
        """普通消息不应被误判为控制命令。"""
        # command 存储普通文本解析结果。
        command = parse_bot_command("你好")

        self.assertIsNone(command)

    def test_build_help_text_lists_task_commands(self):
        """帮助文案应列出多任务常用命令。"""
        # help_text 存储展示给飞书用户的帮助内容。
        help_text = build_help_text()

        self.assertIn("/new", help_text)
        self.assertIn("/tasks", help_text)
        self.assertIn("/status", help_text)

    def test_workspace_instruction_text_describes_feishu_context(self):
        """Claude 工作区说明应写明飞书入口和通用安全边界，不得包含开发者个人路径。"""
        # instruction 存储要写入 CLAUDE.md 的通用工作区说明文本。
        instruction = workspace_instruction_text()

        self.assertIn("飞书", instruction)
        self.assertIn("明确授权", instruction)
        self.assertNotIn("/Users/", instruction)
        self.assertNotIn("ai-lab", instruction)

    def test_workspace_instruction_only_creates_supported_file_and_preserves_custom_content(
        self,
    ):
        """工作区初始化只创建 CLAUDE.md，且不得覆盖用户已经维护的本机说明。"""
        with tempfile.TemporaryDirectory() as tmp:
            # workspace_root 存储隔离测试使用的 Claude 工作区目录。
            workspace_root = Path(tmp) / "workspace"
            ensure_workspace_instruction_files(workspace_root)
            # instruction_path 存储 Claude Code 实际识别的说明文件路径。
            instruction_path = workspace_root / "CLAUDE.md"
            instruction_path.write_text("用户自定义说明", encoding="utf-8")
            ensure_workspace_instruction_files(workspace_root)

            self.assertEqual(
                instruction_path.read_text(encoding="utf-8"), "用户自定义说明"
            )
            self.assertFalse((workspace_root / "CLUADE.md").exists())

    def test_build_lark_stream_content_args_carries_sequence(self):
        """流式追加命令应 PUT 到卡片元素 content 接口，请求体带递增 sequence。"""
        # args 是流式追加文本的命令行数组。
        args = build_lark_stream_content_args(
            "card_123", "你好", 5, profile=DEFAULT_LARK_PROFILE
        )

        self.assertIn("PUT", args)
        self.assertIn(
            f"/open-apis/cardkit/v1/cards/card_123/elements/{STREAM_CARD_SUMMARY_ID}/content",
            args,
        )
        # data_index 是 --data 参数值在 argv 中的位置。
        data_index = args.index("--data") + 1
        # payload 是流式追加请求体，content 是累计全文，sequence 保序。
        payload = json.loads(args[data_index])
        self.assertEqual(payload["content"], "你好")
        self.assertEqual(payload["sequence"], 5)

    def test_answer_content_uses_single_markdown_without_collapsible_panel(self):
        """回答卡片应只使用单个正文，不再创建鸡肋的完整内容折叠面板。"""
        # content 存储超过旧版折叠阈值的模拟完整回答。
        content = "摘要。\n\n" + "完整内容" * 300
        # elements 存储回答卡片的正文元素。
        elements = answer_card_content_elements(content)

        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["element_id"], STREAM_CARD_SUMMARY_ID)
        self.assertEqual(elements[0]["content"], content)

    def test_answer_input_uses_standalone_callback_for_enter_submit(self):
        """卡片输入必须脱离 form，飞书才会在 Enter 时返回 input_value。"""
        # input_element 存储任务 t2 对应的独立输入组件。
        input_element = answer_card_input_form("t2")

        self.assertEqual(input_element["tag"], "input")
        self.assertEqual(input_element["element_id"], "chat_form_t2")
        self.assertEqual(input_element["name"], "chat_input_t2")
        self.assertEqual(input_element["input_type"], "text")
        self.assertEqual(input_element["behaviors"][0]["type"], "callback")
        self.assertEqual(
            input_element["behaviors"][0]["value"]["action"], "card_chat_submit"
        )


if __name__ == "__main__":
    unittest.main()
