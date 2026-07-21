import errno
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

from lark_ai_bridge import (
    BotCommand,
    BridgeApp,
    ClaudeInteractiveSession,
    ClaudeTaskManager,
    LarkMessage,
    DEFAULT_LARK_PROFILE,
    DEFAULT_PROCESSING_TEXT,
    STREAM_CARD_SUMMARY_ID,
    answer_card_actions,
    answer_card_content_elements,
    answer_card_input_form,
    build_lark_consume_args,
    build_lark_gateway_args,
    build_task_list_card,
    build_help_text,
    build_lark_create_card_args,
    build_lark_finish_stream_args,
    build_lark_profile_list_args,
    build_lark_reply_args,
    build_lark_replace_element_args,
    build_lark_send_card_args,
    build_lark_stream_content_args,
    build_stdin_keeper_args,
    build_lark_update_message_args,
    default_base_dir,
    extract_card_id,
    extract_sent_message_id,
    extract_assistant_text,
    extract_streaming_assistant_text,
    ensure_workspace_instruction_files,
    find_jsonl_containing_text,
    compact_stream_preview,
    conversation_card_content,
    friendly_tool_phase,
    format_pty_submission,
    normalize_lark_event,
    parse_bot_command,
    parse_claude_stream_event,
    parse_lark_profile_names,
    project_log_dir_for_cwd,
    should_accept_trust_prompt,
    should_show_processing_placeholder,
    workspace_instruction_text,
)


class FakeClaudeSession:
    """测试用 Claude 会话，记录输入并返回确定性回复。"""

    def __init__(self, workspace, log_dir, system_prompt, timeout, session_id=None, resume=False):
        """初始化假会话，参数与真实 ClaudeInteractiveSession 保持一致。"""
        # workspace 存储测试传入的任务工作目录。
        self.workspace = workspace
        # log_dir 存储测试传入的任务日志目录。
        self.log_dir = log_dir
        # system_prompt 存储测试传入的系统提示。
        self.system_prompt = system_prompt
        # timeout 存储测试传入的超时时间。
        self.timeout = timeout
        # session_id 存储测试传入的会话 ID；持久化恢复时会带上历史 ID，未传则生成一个占位值。
        self.session_id = session_id or "fake-session-id"
        # resume 记录本次是否按恢复模式启动，供断言持久化续接逻辑使用。
        self.resume = resume
        # started 记录 start 是否被调用。
        self.started = False
        # stopped 记录 stop 是否被调用。
        self.stopped = False
        # questions 存储所有 ask 收到的问题文本。
        self.questions = []

    def start(self):
        """记录测试会话已启动。"""
        self.started = True

    def stop(self):
        """记录测试会话已停止。"""
        self.stopped = True

    def ask(self, message):
        """返回可预测的测试回答。"""
        self.questions.append(message)
        return f"回复:{message}"


class RecordingBridgeApp(BridgeApp):
    """测试用桥接应用，记录飞书发送和编辑动作而不调用 lark-cli。"""

    def __init__(self, args):
        """初始化记录型桥接应用，args 与真实 BridgeApp 保持一致。"""
        super().__init__(args)
        # sent_replies 存储桥接尝试发送的飞书回复。
        self.sent_replies = []
        # updated_messages 存储桥接尝试编辑的飞书消息。
        self.updated_messages = []

    def _send_reply(self, message_id, text):
        """记录一次飞书回复，并返回可被后续编辑的模拟消息 ID。"""
        self.sent_replies.append((message_id, text))
        return "om_processing"

    def _update_message(self, message_id, text):
        """记录一次飞书消息编辑，并返回成功。"""
        self.updated_messages.append((message_id, text))
        return True


class BlockingClaudeSession:
    """测试用阻塞 Claude 会话，用来模拟长时间执行中的任务。"""

    # started 在 ask 进入阻塞等待时置位，测试用它确认后台任务已开始。
    started = threading.Event()
    # release 在测试允许长任务结束时置位，避免测试依赖真实耗时。
    release = threading.Event()

    @classmethod
    def reset(cls):
        """重置类级同步事件，确保不同测试之间互不影响。"""
        cls.started = threading.Event()
        cls.release = threading.Event()

    def __init__(self, workspace, log_dir, system_prompt, timeout, session_id=None, resume=False):
        """初始化阻塞会话，参数与真实 ClaudeInteractiveSession 保持一致。"""
        # workspace 存储测试传入的任务工作目录。
        self.workspace = workspace
        # log_dir 存储测试传入的任务日志目录。
        self.log_dir = log_dir
        # system_prompt 存储测试传入的系统提示。
        self.system_prompt = system_prompt
        # timeout 存储测试传入的超时时间。
        self.timeout = timeout
        # session_id 存储测试传入的会话 ID；持久化恢复时会带上历史 ID，未传则生成一个占位值。
        self.session_id = session_id or "fake-session-id"
        # resume 记录本次是否按恢复模式启动。
        self.resume = resume
        # started_flag 记录 start 是否被调用。
        self.started_flag = False
        # stopped_flag 记录 stop 是否被调用。
        self.stopped_flag = False
        # questions 存储所有 ask 收到的问题文本。
        self.questions = []

    def start(self):
        """记录测试会话已启动。"""
        self.started_flag = True

    def stop(self):
        """记录测试会话已停止。"""
        self.stopped_flag = True

    def ask(self, message):
        """阻塞等待测试释放后返回可预测回答。"""
        self.questions.append(message)
        BlockingClaudeSession.started.set()
        if not BlockingClaudeSession.release.wait(timeout=2):
            raise TimeoutError("测试阻塞会话没有被释放")
        return f"回复:{message}"


class LarkClaudeBridgeTest(unittest.TestCase):
    """验证桥接脚本里不依赖外部服务的核心解析逻辑。"""

    def test_default_lark_profile_comes_from_environment(self):
        """模块默认 profile 应读取本机环境，避免发布代码绑定开发者个人 App ID。"""
        # module_dir 存储桥接模块所在目录，供隔离子进程导入当前待测代码。
        module_dir = Path(default_base_dir.__globals__["__file__"]).resolve().parent
        # child_env 存储隔离子进程使用的环境变量副本和测试 profile。
        child_env = {**os.environ, "LARK_PROFILE": "test-open-source-profile"}
        # completed 存储子进程导入模块后输出的默认 profile。
        completed = subprocess.run(
            ["python3", "-c", "import lark_ai_bridge; print(lark_ai_bridge.DEFAULT_LARK_PROFILE)"],
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
        expected_dir = Path(default_base_dir.__globals__["__file__"]).resolve().parent
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

    def test_extract_assistant_text_reads_latest_assistant_message(self):
        """应从 Claude Code JSONL 中读取指定时间后的最后一条 assistant 文本。"""
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "session.jsonl"
            older = {
                "timestamp": "2026-06-28T00:00:00.000Z",
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "旧回答"}]},
            }
            newer = {
                "timestamp": "2026-06-28T00:00:03.000Z",
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "你好！"},
                        {"type": "tool_use", "name": "TodoWrite"},
                    ]
                },
            }
            log_path.write_text(
                json.dumps(older, ensure_ascii=False)
                + "\n"
                + json.dumps(newer, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )

            text = extract_assistant_text(
                log_path,
                since_iso="2026-06-28T00:00:01.000Z",
            )

        self.assertEqual(text, "你好！")

    def test_extract_assistant_text_ignores_tool_use_interim_text(self):
        """工具调用前的阶段性 assistant 文本不应被当作最终飞书回复。"""
        with tempfile.TemporaryDirectory() as tmp:
            # log_path 存储模拟 Claude Code JSONL 会话日志的位置。
            log_path = Path(tmp) / "session.jsonl"
            # interim 存储会继续触发工具调用的阶段性 assistant 文本。
            interim = {
                "timestamp": "2026-06-28T00:00:02.000Z",
                "type": "assistant",
                "message": {
                    "stop_reason": "tool_use",
                    "content": [{"type": "text", "text": "先找一下相关代码。"}],
                },
            }
            # final 存储工具执行完成后的最终 assistant 文本。
            final = {
                "timestamp": "2026-06-28T00:00:05.000Z",
                "type": "assistant",
                "message": {
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "已修复并验证。"}],
                },
            }
            log_path.write_text(
                json.dumps(interim, ensure_ascii=False)
                + "\n"
                + json.dumps(final, ensure_ascii=False)
                + "\n",
                encoding="utf-8",
            )

            # text 存储从日志中提取到的可回复飞书的最终文本。
            text = extract_assistant_text(
                log_path,
                since_iso="2026-06-28T00:00:01.000Z",
            )

        self.assertEqual(text, "已修复并验证。")

    def test_extract_assistant_text_waits_when_only_interim_text_exists(self):
        """如果当前只有 tool_use 阶段性文本，应继续等待而不是提前回复。"""
        with tempfile.TemporaryDirectory() as tmp:
            # log_path 存储模拟 Claude Code JSONL 会话日志的位置。
            log_path = Path(tmp) / "session.jsonl"
            # interim 存储会继续触发工具调用的阶段性 assistant 文本。
            interim = {
                "timestamp": "2026-06-28T00:00:02.000Z",
                "type": "assistant",
                "message": {
                    "stop_reason": "tool_use",
                    "content": [{"type": "text", "text": "先找一下相关代码。"}],
                },
            }
            log_path.write_text(json.dumps(interim, ensure_ascii=False) + "\n", encoding="utf-8")

            # text 存储从日志中提取到的可回复飞书的最终文本。
            text = extract_assistant_text(
                log_path,
                since_iso="2026-06-28T00:00:01.000Z",
            )

        self.assertIsNone(text)

    def test_wait_for_answer_treats_timeout_as_soft_until_final_text_arrives(self):
        """超过软等待时间但 Claude 仍在工作时，应继续等最终 end_turn 文本。"""
        with tempfile.TemporaryDirectory() as tmp:
            # log_path 存储模拟 Claude Code JSONL 会话日志的位置。
            log_path = Path(tmp) / "session.jsonl"
            # interim 存储会继续触发工具调用的阶段性 assistant 文本。
            interim = {
                "timestamp": "2026-06-28T00:00:02.000Z",
                "type": "assistant",
                "message": {
                    "stop_reason": "tool_use",
                    "content": [{"type": "text", "text": "先找一下相关代码。"}],
                },
            }
            log_path.write_text(json.dumps(interim, ensure_ascii=False) + "\n", encoding="utf-8")
            # session 存储使用极短软等待时间的 Claude 会话对象。
            session = ClaudeInteractiveSession(
                workspace=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=0.05,
            )
            session.session_log = log_path
            session.max_wait_after_soft_timeout = 1.0

            def append_final_answer():
                """延迟写入最终 assistant 文本，模拟长任务稍后完成。"""
                time.sleep(0.15)
                # final 存储工具执行完成后的最终 assistant 文本。
                final = {
                    "timestamp": "2026-06-28T00:00:05.000Z",
                    "type": "assistant",
                    "message": {
                        "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": "已修复并验证。"}],
                    },
                }
                with log_path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps(final, ensure_ascii=False) + "\n")

            # writer 存储负责稍后写入最终答案的测试线程。
            writer = threading.Thread(target=append_final_answer)
            writer.start()
            try:
                # text 存储等待函数最终提取到的飞书回复文本。
                text = session._wait_for_answer("2026-06-28T00:00:01.000Z")
            finally:
                writer.join(timeout=1)

        self.assertEqual(text, "已修复并验证。")

    def test_ask_restarts_without_resume_when_old_session_pty_returns_eio(self):
        """旧会话因工作目录迁移失效时，应新建会话并重试当前问题。"""
        with tempfile.TemporaryDirectory() as tmp:
            # session 存储模拟恢复旧会话的交互式 Claude 会话。
            session = ClaudeInteractiveSession(
                workspace=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_id="missing-session-id",
                resume=True,
            )
            session.fd = 123
            # eio_error 模拟 Claude 因找不到旧会话退出后 PTY 返回的系统错误。
            eio_error = OSError(errno.EIO, "Input/output error")
            with (
                mock.patch.object(session, "_ask_once", side_effect=[eio_error, "新会话回答"]) as ask_once,
                mock.patch.object(session, "stop") as stop,
                mock.patch.object(session, "start") as start,
            ):
                # answer 存储自动降级到新会话后的回答。
                answer = session.ask("你好")

        self.assertEqual(answer, "新会话回答")
        self.assertFalse(session.resume)
        self.assertNotEqual(session.session_id, "missing-session-id")
        self.assertEqual(ask_once.call_count, 2)
        stop.assert_called_once_with()
        start.assert_called_once_with()

    def test_find_jsonl_containing_text_locates_marked_session(self):
        """应能按本轮唯一标记在 Claude 日志树中定位会话文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            # root 存储隔离测试使用的 Claude 项目日志根目录。
            root = Path(tmp)
            # log_dir 存储模拟的单个 Claude 项目日志目录。
            log_dir = root / "-Users-example"
            log_dir.mkdir()
            # log_path 存储包含本轮唯一标记的模拟 Claude 会话日志。
            log_path = log_dir / "session.jsonl"
            log_path.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": "问题\n[LARK_BRIDGE_TURN:test-marker]",
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            found = find_jsonl_containing_text(root, "LARK_BRIDGE_TURN:test-marker")

        self.assertEqual(found, log_path)

    def test_format_pty_submission_uses_bracketed_paste_and_carriage_return(self):
        """多行内容应通过 bracketed paste 输入，提交回车由调用方单独发送。"""
        payload = format_pty_submission("第一行\n第二行")

        self.assertTrue(payload.startswith(b"\x1b[200~"))
        self.assertIn("第一行\n第二行".encode("utf-8"), payload)
        self.assertTrue(payload.endswith(b"\x1b[201~"))

    def test_build_lark_reply_args_uses_argv_not_shell_string(self):
        """回复命令应以 argv 形式传参，避免消息内容被 shell 解释。"""
        args = build_lark_reply_args("om_abc", "hello; rm -rf /")

        self.assertEqual(args[:4], ["lark-cli", "im", "+messages-reply", "--message-id"])
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
        args = build_lark_update_message_args("om_reply", "完成", profile=DEFAULT_LARK_PROFILE)
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

    def test_build_lark_consume_args_supports_card_actions(self):
        """事件消费者应能订阅卡片按钮回调。"""
        # args 存储卡片回调事件监听命令。
        args = build_lark_consume_args(
            "bot",
            profile=DEFAULT_LARK_PROFILE,
            event_key="card.action.trigger",
        )

        self.assertIn("card.action.trigger", args)
        self.assertNotIn("im.message.receive_v1", args)

    def test_build_lark_gateway_args_uses_single_official_sdk_process(self):
        """事件网关命令应同时获得入口、配置和 profile，供单长连接注册两类事件。"""
        # gateway_path 存储测试用 Node 网关入口路径。
        gateway_path = Path("/runtime/lark_event_gateway.cjs")
        # config_path 存储测试用 lark-cli 配置路径。
        config_path = Path("/home/user/.lark-cli/config.json")

        # args 存储构造出的单长连接网关命令。
        args = build_lark_gateway_args(gateway_path, config_path, DEFAULT_LARK_PROFILE)

        self.assertEqual(args[0], "node")
        self.assertEqual(args[1], str(gateway_path))
        self.assertIn(str(config_path), args)
        self.assertIn(DEFAULT_LARK_PROFILE, args)

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

    def test_workspace_instruction_only_creates_supported_file_and_preserves_custom_content(self):
        """工作区初始化只创建 CLAUDE.md，且不得覆盖用户已经维护的本机说明。"""
        with tempfile.TemporaryDirectory() as tmp:
            # workspace_root 存储隔离测试使用的 Claude 工作区目录。
            workspace_root = Path(tmp) / "workspace"
            ensure_workspace_instruction_files(workspace_root)
            # instruction_path 存储 Claude Code 实际识别的说明文件路径。
            instruction_path = workspace_root / "CLAUDE.md"
            instruction_path.write_text("用户自定义说明", encoding="utf-8")
            ensure_workspace_instruction_files(workspace_root)

            self.assertEqual(instruction_path.read_text(encoding="utf-8"), "用户自定义说明")
            self.assertFalse((workspace_root / "CLUADE.md").exists())

    def test_task_manager_creates_default_task_for_plain_message(self):
        """用户直接发消息时应自动创建默认任务并转给该任务会话。"""
        with tempfile.TemporaryDirectory() as tmp:
            # manager 存储使用假 Claude 会话的任务管理器。
            manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )

            # answer 存储普通消息得到的任务回复。
            answer = manager.handle_text("ou_user", "你好")

            self.assertEqual(answer, "回复:你好")
            self.assertIn("t1", manager.tasks)
            self.assertEqual(manager.current_task_id_for_sender("ou_user"), "t1")

    def test_task_manager_new_tasks_are_separate_windows(self):
        """多个任务应各自持有独立 Claude 会话。"""
        with tempfile.TemporaryDirectory() as tmp:
            # manager 存储使用假 Claude 会话的任务管理器。
            manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )

            # first_reply 存储创建第一个任务的命令回复。
            first_reply = manager.handle_text("ou_user", "/new 周报")
            # second_reply 存储创建第二个任务的命令回复。
            second_reply = manager.handle_text("ou_user", "/new 排查")
            # tasks_reply 存储任务列表命令回复。
            tasks_reply = manager.handle_text("ou_user", "/tasks")

            self.assertIn("t1", first_reply)
            self.assertIn("t2", second_reply)
            self.assertIn("周报", tasks_reply)
            self.assertIn("排查", tasks_reply)
            self.assertEqual(manager.tasks["t1"].session, None)
            self.assertEqual(manager.tasks["t2"].session, None)

    def test_task_manager_use_switches_current_task(self):
        """use 命令应切换当前用户后续普通消息进入的任务。"""
        with tempfile.TemporaryDirectory() as tmp:
            # manager 存储使用假 Claude 会话的任务管理器。
            manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            manager.handle_text("ou_user", "/new 周报")
            manager.handle_text("ou_user", "/new 排查")

            # use_reply 存储切换任务命令的回复。
            use_reply = manager.handle_text("ou_user", "/use t1")
            # answer 存储切换后普通消息的回复。
            answer = manager.handle_text("ou_user", "继续")

            self.assertIn("已切换", use_reply)
            self.assertEqual(answer, "回复:继续")
            self.assertEqual(manager.tasks["t1"].last_question, "继续")
            self.assertEqual(manager.tasks["t2"].last_question, "")

    def test_task_manager_stop_task_terminates_running_session(self):
        """停止任务应终止当前会话并保留任务记录。"""
        with tempfile.TemporaryDirectory() as tmp:
            # manager 存储测试任务管理器。
            manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            manager.create_task("ou_user", "长任务")
            # task 存储需要模拟为正在运行的任务。
            task = manager.tasks["t1"]
            task.session = FakeClaudeSession(task.workspace, Path(tmp) / "logs", "测试提示", 5)
            task.status = "思考中"

            # result 存储停止任务后的提示。
            result = manager.stop_task("t1")

        self.assertIn("已停止", result)
        self.assertTrue(task.session.stopped)
        self.assertEqual(task.status, "已停止")

    def test_enrich_message_adds_latest_content_quote_and_attachments(self):
        """消息富化应读取编辑后的正文、引用内容和附件路径。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储非 dry-run 桥接应用配置。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=False,
                once=False,
            )
            # app 存储用于测试消息富化的桥接应用。
            app = BridgeApp(args)
            # message 存储模拟的飞书文件消息。
            message = LarkMessage("evt", "om_source", "ou_user", "oc_chat", "旧内容", "p2p", "file")
            with (
                mock.patch.object(
                    app,
                    "_get_message_detail",
                    side_effect=[
                        {"content": "更新后的问题 file_abc", "reply_to": "om_quote"},
                        {"content": "被引用的回答"},
                    ],
                ),
                mock.patch.object(app, "_download_message_resources", return_value=("/tmp/file.pdf",)),
            ):
                # enriched 存储富化后的桥接消息。
                enriched = app._enrich_message(message)

        self.assertIn("更新后的问题", enriched.text)
        self.assertIn("被引用的回答", enriched.text)
        self.assertIn("/tmp/file.pdf", enriched.text)

    def test_task_manager_status_reports_progress(self):
        """status 命令应展示当前任务轮次和最近问题。"""
        with tempfile.TemporaryDirectory() as tmp:
            # manager 存储使用假 Claude 会话的任务管理器。
            manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            manager.handle_text("ou_user", "/new 周报")
            manager.handle_text("ou_user", "今天做了什么")

            # status_reply 存储当前任务状态命令的回复。
            status_reply = manager.handle_text("ou_user", "/status")

            self.assertIn("t1", status_reply)
            self.assertIn("周报", status_reply)
            self.assertIn("轮次：1", status_reply)
            self.assertIn("今天做了什么", status_reply)

    def test_task_manager_ask_routes_to_named_task(self):
        """ask 命令应能把消息发送给指定任务并切换到该任务。"""
        with tempfile.TemporaryDirectory() as tmp:
            # manager 存储使用假 Claude 会话的任务管理器。
            manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            manager.handle_text("ou_user", "/new 周报")
            manager.handle_text("ou_user", "/new 排查")

            # answer 存储指定任务 ask 命令的回复。
            answer = manager.handle_text("ou_user", "/ask t1 总结一下")

            self.assertEqual(answer, "回复:总结一下")
            self.assertEqual(manager.current_task_id_for_sender("ou_user"), "t1")
            self.assertEqual(manager.tasks["t1"].last_question, "总结一下")

    def test_task_manager_persists_and_restores_tasks_across_restart(self):
        """任务元数据应落盘，重启后新管理器能恢复任务列表、轮次和会话 ID。"""
        with tempfile.TemporaryDirectory() as tmp:
            # log_dir 存储两个管理器共享的日志目录，state 文件就写在这里。
            log_dir = Path(tmp) / "logs"
            # workspace_root 存储两个管理器共享的任务工作目录根。
            workspace_root = Path(tmp) / "workspace"
            # first 存储关机前那次运行的任务管理器。
            first = ClaudeTaskManager(
                workspace_root=workspace_root,
                log_dir=log_dir,
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            first.handle_text("ou_user", "/new 周报")
            first.handle_text("ou_user", "记一下进度")

            # saved_session_id 存储落盘前 t1 的会话 ID，用来断言重启后能还原同一个会话。
            saved_session_id = first.tasks["t1"].session_id
            self.assertTrue(saved_session_id)
            self.assertTrue((log_dir / "tasks-state.json").exists())

            # second 存储模拟关机重启后新建的任务管理器，构造时会自动从 state 恢复。
            second = ClaudeTaskManager(
                workspace_root=workspace_root,
                log_dir=log_dir,
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )

            self.assertIn("t1", second.tasks)
            self.assertEqual(second.tasks["t1"].title, "周报")
            self.assertEqual(second.tasks["t1"].turns, 1)
            self.assertEqual(second.tasks["t1"].session_id, saved_session_id)
            self.assertEqual(
                second.tasks["t1"].conversation_history,
                [{"question": "记一下进度", "answer": "回复:记一下进度"}],
            )
            # 恢复后会话对象尚未拉起，应保持懒启动状态等待下条消息续接。
            self.assertIsNone(second.tasks["t1"].session)
            self.assertEqual(second.current_task_id_for_sender("ou_user"), "t1")
            # next_task_number 应恢复到关机前的值，避免新任务 ID 撞车。
            self.assertEqual(second.next_task_number, first.next_task_number)

    def test_task_manager_resumes_claude_session_after_restart(self):
        """恢复的任务再次提问时，应以 resume 模式带着原会话 ID 拉起 Claude。"""
        with tempfile.TemporaryDirectory() as tmp:
            # log_dir 存储两个管理器共享的日志目录。
            log_dir = Path(tmp) / "logs"
            # workspace_root 存储两个管理器共享的任务工作目录根。
            workspace_root = Path(tmp) / "workspace"
            # first 存储关机前那次运行的任务管理器。
            first = ClaudeTaskManager(
                workspace_root=workspace_root,
                log_dir=log_dir,
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            first.handle_text("ou_user", "第一次提问")
            # saved_session_id 存储关机前的会话 ID，重启续接时应原样传给 Claude。
            saved_session_id = first.tasks["t1"].session_id

            # second 存储模拟重启后的任务管理器。
            second = ClaudeTaskManager(
                workspace_root=workspace_root,
                log_dir=log_dir,
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            second.handle_text("ou_user", "重启后继续问")

            # restored_session 存储恢复后懒启动出来的假会话，用来断言 resume 入参。
            restored_session = second.tasks["t1"].session
            self.assertIsNotNone(restored_session)
            self.assertTrue(restored_session.resume)
            self.assertEqual(restored_session.session_id, saved_session_id)

    def test_bridge_replaces_processing_placeholder_for_plain_message(self):
        """普通消息应先发 AI 思考中，再把同一条占位消息编辑为 Claude 回答。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储测试桥接应用需要的命令行参数。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=True,
            )
            # app 存储不会真实调用飞书的记录型桥接应用。
            app = RecordingBridgeApp(args)
            # task_manager 存储使用假 Claude 会话的任务管理器。
            task_manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            app.task_manager = task_manager
            # event 存储模拟的飞书文本消息事件。
            event = {
                "event_id": "evt_1",
                "message_id": "om_user",
                "message_type": "text",
                "content": "你好",
                "sender_id": "ou_user",
                "chat_id": "oc_chat",
                "chat_type": "p2p",
            }

            app._handle_event(event)

        self.assertEqual(app.sent_replies, [("om_user", DEFAULT_PROCESSING_TEXT)])
        self.assertEqual(app.updated_messages, [("om_processing", "回复:你好")])

    def test_bridge_dispatch_keeps_control_commands_responsive_during_long_task(self):
        """长任务后台执行时，/tasks 这类控制命令仍应能立即返回状态。"""
        BlockingClaudeSession.reset()
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储测试桥接应用需要的命令行参数。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=False,
            )
            # app 存储不会真实调用飞书的记录型桥接应用。
            app = RecordingBridgeApp(args)
            # task_manager 存储使用阻塞 Claude 会话的任务管理器。
            task_manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=BlockingClaudeSession,
            )
            app.task_manager = task_manager
            # long_event 存储模拟的长耗时普通飞书消息事件。
            long_event = {
                "event_id": "evt_long",
                "message_id": "om_long",
                "message_type": "text",
                "content": "请做一个长任务",
                "sender_id": "ou_user",
                "chat_id": "oc_chat",
                "chat_type": "p2p",
            }
            # tasks_event 存储长任务期间查询任务列表的控制命令事件。
            tasks_event = {
                "event_id": "evt_tasks",
                "message_id": "om_tasks",
                "message_type": "text",
                "content": "/tasks",
                "sender_id": "ou_user",
                "chat_id": "oc_chat",
                "chat_type": "p2p",
            }

            app._dispatch_event(long_event)
            self.assertTrue(BlockingClaudeSession.started.wait(timeout=1))
            app._handle_event(tasks_event)
            # tasks_reply 存储 /tasks 命令即时返回的回复文本。
            tasks_reply = app.sent_replies[-1][1]
            BlockingClaudeSession.release.set()
            for worker_thread in app.worker_threads:
                worker_thread.join(timeout=2)

        self.assertIn("任务列表", tasks_reply)
        self.assertIn("思考中", tasks_reply)
        self.assertIn(("om_long", DEFAULT_PROCESSING_TEXT), app.sent_replies)
        self.assertIn(("om_processing", "回复:请做一个长任务"), app.updated_messages)

    def test_project_log_dir_for_cwd_matches_claude_path_encoding(self):
        """Claude 项目日志目录应按真实规则编码绝对路径中的斜杠与空格。"""
        # workspace_path 存储不包含开发者个人信息的模拟工作区绝对路径。
        workspace_path = Path("/Users/example/Library/Application Support/lark-ai-bridge/claude-workspace")
        # log_dir 存储 Claude 对模拟工作区编码后的项目日志目录。
        log_dir = project_log_dir_for_cwd(workspace_path)

        self.assertEqual(
            log_dir,
            Path.home()
            / ".claude"
            / "projects"
            / "-Users-example-Library-Application-Support-lark-ai-bridge-claude-workspace",
        )

    def test_should_accept_trust_prompt_detects_compact_tui_text(self):
        """Claude TUI 首屏被清洗后没有空格时，也应识别为信任确认。"""
        screen = "Quicksafetycheck:Isthisaprojectyoucreatedoroneyoutrust? Entertoconfirm"

        self.assertTrue(should_accept_trust_prompt(screen))

    def test_should_accept_trust_prompt_detects_external_import_prompt(self):
        """Claude 请求允许导入上级说明文件时，也应识别为可确认页。"""
        # screen 存储 Claude TUI 清洗后的外部说明文件授权提示。
        screen = "Allow external CLAUDE.mdfileimports? External imports:/Users/example/project/AGENTS.md"

        self.assertTrue(should_accept_trust_prompt(screen))

    def test_build_lark_create_card_args_opens_streaming_mode(self):
        """建卡命令应走 cardkit v1，且卡片 JSON 打开 streaming_mode、带正文元素 ID。"""
        # args 是建卡命令行数组，profile 固定为桥接机器人。
        args = build_lark_create_card_args(profile=DEFAULT_LARK_PROFILE)

        self.assertEqual(args[:6], ["lark-cli", "--profile", DEFAULT_LARK_PROFILE, "api", "POST", "/open-apis/cardkit/v1/cards"])
        # data_index 是 --data 参数值在 argv 中的位置。
        data_index = args.index("--data") + 1
        # payload 是建卡请求体，data 字段是卡片 JSON 字符串。
        payload = json.loads(args[data_index])
        self.assertEqual(payload["type"], "card_json")
        # card 是解析后的卡片 JSON，用来断言流式模式和元素 ID。
        card = json.loads(payload["data"])
        self.assertTrue(card["config"]["streaming_mode"])
        self.assertEqual(card["body"]["elements"][0]["element_id"], STREAM_CARD_SUMMARY_ID)
        self.assertEqual(card["body"]["elements"][0]["content"], DEFAULT_PROCESSING_TEXT)
        # component_tags 存储卡片全部顶层组件类型，用于确认没有多余折叠全文区。
        component_tags = [element["tag"] for element in card["body"]["elements"]]
        self.assertNotIn("collapsible_panel", component_tags)

    def test_build_lark_send_card_args_references_card_id(self):
        """发卡命令应以 interactive 类型回复，并用 card_id 引用已建卡片实体。"""
        # args 是发送卡片消息的命令行数组。
        args = build_lark_send_card_args("om_abc", "card_123", profile=DEFAULT_LARK_PROFILE)

        self.assertIn("+messages-reply", args)
        self.assertIn("interactive", args)
        # content_index 是 --content 参数值在 argv 中的位置。
        content_index = args.index("--content") + 1
        # content 是卡片消息内容，data.card_id 指向已建卡片。
        content = json.loads(args[content_index])
        self.assertEqual(content["type"], "card")
        self.assertEqual(content["data"]["card_id"], "card_123")

    def test_build_lark_stream_content_args_carries_sequence(self):
        """流式追加命令应 PUT 到卡片元素 content 接口，请求体带递增 sequence。"""
        # args 是流式追加文本的命令行数组。
        args = build_lark_stream_content_args("card_123", "你好", 5, profile=DEFAULT_LARK_PROFILE)

        self.assertIn("PUT", args)
        self.assertIn(f"/open-apis/cardkit/v1/cards/card_123/elements/{STREAM_CARD_SUMMARY_ID}/content", args)
        # data_index 是 --data 参数值在 argv 中的位置。
        data_index = args.index("--data") + 1
        # payload 是流式追加请求体，content 是累计全文，sequence 保序。
        payload = json.loads(args[data_index])
        self.assertEqual(payload["content"], "你好")
        self.assertEqual(payload["sequence"], 5)

    def test_build_lark_finish_stream_args_closes_streaming_mode(self):
        """定稿命令应 PATCH 卡片 settings，把 streaming_mode 关掉并带 sequence。"""
        # args 是卡片定稿的命令行数组。
        args = build_lark_finish_stream_args("card_123", 9, profile=DEFAULT_LARK_PROFILE)

        self.assertIn("PATCH", args)
        self.assertIn("/open-apis/cardkit/v1/cards/card_123/settings", args)
        # data_index 是 --data 参数值在 argv 中的位置。
        data_index = args.index("--data") + 1
        # payload 是定稿请求体，settings 里关闭流式模式。
        payload = json.loads(args[data_index])
        # settings 是飞书接口要求的 JSON 字符串，需要二次解析后断言配置。
        settings = json.loads(payload["settings"])
        self.assertFalse(settings["config"]["streaming_mode"])
        self.assertEqual(payload["sequence"], 9)

    def test_parse_claude_stream_event_emits_thinking_tool_and_text_updates(self):
        """stream-json 解析应实时展示思考、工具状态，并在正文开始后累计正文。"""
        # thinking_payload 存储模拟的 Claude 思考 token 事件。
        thinking_payload = {
            "type": "stream_event",
            "session_id": "session-1",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "thinking_delta", "thinking": "正在检查目录"},
            },
        }
        # answer_text 存储解析后累计的最终正文。
        answer_text, thinking_text, display_text, session_id = parse_claude_stream_event(
            thinking_payload,
            "",
            "",
        )
        self.assertEqual(display_text, "思考中：\n正在检查目录")
        self.assertEqual(session_id, "session-1")

        # retry_payload 存储模拟的 Claude 上游服务重试状态。
        retry_payload = {
            "type": "system",
            "subtype": "api_retry",
            "attempt": 2,
            "session_id": "session-1",
        }
        _, _, retry_display, _ = parse_claude_stream_event(retry_payload, answer_text, thinking_text)
        self.assertEqual(retry_display, "Claude 服务繁忙，正在重试（第 2 次）...")

        # tool_payload 存储模拟的 Claude 工具调用开始事件。
        tool_payload = {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "Bash"},
            },
        }
        _, _, tool_display, _ = parse_claude_stream_event(tool_payload, answer_text, thinking_text)
        self.assertEqual(tool_display, "正在使用工具：Bash...")

        # first_text_payload 存储模拟的第一个最终正文 token。
        first_text_payload = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "当前目录"},
            },
        }
        answer_text, thinking_text, display_text, _ = parse_claude_stream_event(
            first_text_payload,
            answer_text,
            thinking_text,
        )
        self.assertEqual(display_text, "当前目录")

        # second_text_payload 存储模拟的后续最终正文 token。
        second_text_payload = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "是 t1"},
            },
        }
        answer_text, _, display_text, _ = parse_claude_stream_event(
            second_text_payload,
            answer_text,
            thinking_text,
        )
        self.assertEqual(answer_text, "当前目录是 t1")
        self.assertEqual(display_text, "当前目录是 t1")

    def test_friendly_tool_phase_maps_common_tools(self):
        """常见 Claude 工具应转换为可理解的任务阶段。"""
        self.assertEqual(friendly_tool_phase("WebSearch"), "搜索中")
        self.assertEqual(friendly_tool_phase("Read"), "读取文件")
        self.assertEqual(friendly_tool_phase("Bash"), "执行命令")

    def test_compact_stream_preview_keeps_latest_tail(self):
        """长流式内容应压缩中段，同时保留开头状态和最新输出。"""
        # content 存储模拟的超长流式任务正文。
        content = "任务状态开头\n" + "中间内容" * 200 + "\n最新输出结尾"
        # preview 存储默认可见的紧凑流式预览。
        preview = compact_stream_preview(content)

        self.assertTrue(preview.startswith("任务状态开头"))
        self.assertIn("中间内容已收起", preview)
        self.assertTrue(preview.endswith("最新输出结尾"))

    def test_answer_content_uses_single_markdown_without_collapsible_panel(self):
        """回答卡片应只使用单个正文，不再创建鸡肋的完整内容折叠面板。"""
        # content 存储超过旧版折叠阈值的模拟完整回答。
        content = "摘要。\n\n" + "完整内容" * 300
        # elements 存储回答卡片的正文元素。
        elements = answer_card_content_elements(content)

        self.assertEqual(len(elements), 1)
        self.assertEqual(elements[0]["element_id"], STREAM_CARD_SUMMARY_ID)
        self.assertEqual(elements[0]["content"], content)

    def test_answer_actions_use_one_compact_row_and_overflow(self):
        """回答操作应只占一行，并把低频动作收入更多菜单。"""
        # actions 存储回答卡片的紧凑操作栏。
        actions = answer_card_actions("t1", "om_1")
        # columns 存储停止、继续和更多菜单三列。
        columns = actions[0]["columns"]
        # overflow 存储第三列中的更多操作组件。
        overflow = columns[2]["elements"][0]
        # menu_actions 存储更多菜单各选项编码的业务动作名。
        menu_actions = [json.loads(option["value"])["action"] for option in overflow["options"]]

        self.assertEqual(len(actions), 1)
        self.assertEqual(len(columns), 3)
        self.assertEqual(columns[0]["elements"][0]["text"]["content"], "所有任务")
        self.assertEqual(columns[1]["elements"][0]["text"]["content"], "停止")
        self.assertEqual(overflow["tag"], "overflow")
        self.assertIn("continue", menu_actions)
        self.assertIn("retry", menu_actions)
        self.assertIn("document", menu_actions)

    def test_answer_input_uses_standalone_callback_for_enter_submit(self):
        """卡片输入必须脱离 form，飞书才会在 Enter 时返回 input_value。"""
        # input_element 存储任务 t2 对应的独立输入组件。
        input_element = answer_card_input_form("t2")

        self.assertEqual(input_element["tag"], "input")
        self.assertEqual(input_element["element_id"], "chat_form_t2")
        self.assertEqual(input_element["name"], "chat_input_t2")
        self.assertEqual(input_element["input_type"], "text")
        self.assertEqual(input_element["behaviors"][0]["type"], "callback")
        self.assertEqual(input_element["behaviors"][0]["value"]["action"], "card_chat_submit")

    def test_replace_element_args_serialize_empty_form_and_sequence(self):
        """清空输入应使用 CardKit 替换组件接口，并携带完整表单和递增序号。"""
        # form 存储可通过 CardKit 替换的独立输入组件。
        form = answer_card_input_form("t2")
        # args 存储 CardKit 更新组件命令参数。
        args = build_lark_replace_element_args("card_1", "chat_form_t2", form, 9)
        # payload 存储更新组件接口的请求体。
        payload = json.loads(args[args.index("--data") + 1])
        # serialized_form 存储请求体中二次序列化后的完整表单。
        serialized_form = json.loads(payload["element"])

        self.assertIn("/cards/card_1/elements/chat_form_t2", args[3])
        self.assertEqual(payload["sequence"], 9)
        self.assertEqual(serialized_form["element_id"], "chat_form_t2")
        self.assertNotIn("default_value", serialized_form)

    def test_streaming_card_clears_input_and_hides_history_until_final_frame(self):
        """卡片续问应清空输入，且流式帧只显示本轮内容，定稿时才恢复历史。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储流式卡片回归测试所需的桥接应用配置。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=False,
            )
            # app 存储被测桥接应用，并复用一张已有任务卡模拟第二轮提问。
            app = BridgeApp(args)
            app.task_manager.create_task("ou_user", "连续对话")
            # task_id 存储新建连续对话任务的唯一标识。
            task_id = app.task_manager.current_task_id_for_sender("ou_user")
            # task 存储已有一轮历史的目标 Claude 任务。
            task = app.task_manager.tasks[task_id]
            task.conversation_history = [{"question": "旧问题", "answer": "旧回答"}]
            app.task_cards[task.task_id] = ("card_existing", "om_existing", 7)
            # message 存储用户从卡片输入框提交的新一轮问题。
            message = LarkMessage(
                event_id="evt_second_turn",
                message_id="om_existing",
                text="新问题",
                sender_id="ou_user",
                chat_id="oc_chat",
                chat_type="p2p",
            )
            # streamed_contents 存储每一帧写入卡片正文的内容与序号。
            streamed_contents = []

            def record_stream(card_id, content, sequence, element_id=STREAM_CARD_SUMMARY_ID):
                """记录卡片正文更新；card_id、content、sequence 和 element_id 对应 CardKit 更新参数。"""
                streamed_contents.append((content, sequence, element_id))
                return True

            def answer_with_delta(task_id, question, on_delta=None):
                """模拟 Claude 先推送增量再返回终稿；task_id 和 question 标识本轮任务与问题。"""
                if on_delta is not None:
                    on_delta("新回答增量")
                return "新回答终稿"

            with (
                mock.patch("lark_ai_bridge.STREAM_MIN_INTERVAL", 0),
                mock.patch.object(app, "_stream_card_content", side_effect=record_stream),
                mock.patch.object(app, "_replace_card_element", return_value=True) as replace_element,
                mock.patch.object(app.task_manager, "ask_task", side_effect=answer_with_delta),
                mock.patch.object(app, "_save_task_cards"),
            ):
                # handled 标记本轮是否完整走完流式卡片路径。
                handled = app._handle_event_streaming(
                    message,
                    task_id=task.task_id,
                    track_source_message=False,
                    clear_input=True,
                )

        self.assertTrue(handled)
        # interim_contents 存储初始状态帧和 Claude 增量帧，二者都不应重复旧历史。
        interim_contents = [item[0] for item in streamed_contents[:-1]]
        self.assertTrue(all("旧问题" not in content for content in interim_contents))
        self.assertTrue(all("旧回答" not in content for content in interim_contents))
        self.assertIn("新问题", streamed_contents[1][0])
        self.assertIn("新回答增量", streamed_contents[1][0])
        # final_content 存储定稿帧，完成后应恢复旧历史并保留本轮终稿。
        final_content = streamed_contents[-1][0]
        self.assertIn("旧问题", final_content)
        self.assertIn("旧回答", final_content)
        self.assertIn("新问题", final_content)
        self.assertIn("新回答终稿", final_content)
        replace_element.assert_called_once()
        # cleared_input 存储用于替换原输入框的空白 CardKit 输入组件。
        cleared_input = replace_element.call_args.args[2]
        self.assertEqual(cleared_input["element_id"], f"chat_form_{task.task_id}")
        self.assertNotIn("default_value", cleared_input)

    def test_conversation_content_shows_history_and_current_turn(self):
        """卡片正文应同时显示之前的问答和正在处理的当前轮次。"""
        # history 存储已经完成的两轮任务对话。
        history = [
            {"question": "第一个问题", "answer": "第一个回答"},
            {"question": "第二个问题", "answer": "第二个回答"},
        ]
        # content 存储历史和当前第三轮组成的连续对话。
        content = conversation_card_content(history, "第三个问题", "正在回答")

        self.assertIn("第一个问题", content)
        self.assertIn("第二个回答", content)
        self.assertIn("第三个问题", content)
        self.assertIn("正在回答", content)
        self.assertLess(content.index("第一个问题"), content.index("第三个问题"))

    def test_conversation_content_hides_oldest_turns_when_history_is_too_long(self):
        """最新历史页应限制轮数并提示当前倒序页码。"""
        # history 存储超过卡片展示轮数的模拟对话。
        history = [
            {"question": f"问题{i}", "answer": f"回答{i}"}
            for i in range(20)
        ]
        # content 存储裁剪后的最近对话正文。
        content = conversation_card_content(history)

        self.assertNotIn("问题0\n", content)
        self.assertIn("问题19", content)
        self.assertIn("第 1/5 页", content)

    def test_conversation_content_can_open_older_history_page(self):
        """较早页应显示前一组问答，支持用户在固定高度窗口中回看历史。"""
        # history 存储十轮可分页的模拟问答。
        history = [
            {"question": f"问题{i}", "answer": f"回答{i}"}
            for i in range(10)
        ]
        # content 存储从最新向前数第二页的问答正文。
        content = conversation_card_content(history, page=1)

        self.assertIn("问题2", content)
        self.assertIn("问题5", content)
        self.assertNotIn("问题9", content)
        self.assertIn("第 2/3 页", content)

    def test_each_plain_lark_message_creates_a_new_task(self):
        """连续发送普通飞书消息时，每条消息都应进入新任务和新卡片上下文。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储测试普通消息自动新建任务所需的桥接配置。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=False,
            )
            # app 存储记录两条普通消息处理结果的桥接应用。
            app = RecordingBridgeApp(args)
            # task_manager 存储使用假 Claude 会话的多任务管理器。
            task_manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            app.task_manager = task_manager
            # first_event 存储第一条普通飞书消息事件。
            first_event = {
                "event_id": "evt_first",
                "message_id": "om_first",
                "message_type": "text",
                "content": "第一个问题",
                "sender_id": "ou_user",
                "chat_id": "oc_chat",
                "chat_type": "p2p",
            }
            # second_event 存储第二条普通飞书消息事件。
            second_event = {
                "event_id": "evt_second",
                "message_id": "om_second",
                "message_type": "text",
                "content": "第二个问题",
                "sender_id": "ou_user",
                "chat_id": "oc_chat",
                "chat_type": "p2p",
            }
            app._handle_event(first_event)
            app._handle_event(second_event)

        self.assertEqual(list(task_manager.tasks), ["t1", "t2"])
        self.assertEqual(task_manager.tasks["t1"].last_question, "第一个问题")
        self.assertEqual(task_manager.tasks["t2"].last_question, "第二个问题")

    def test_card_chat_submit_routes_to_bound_task(self):
        """从旧卡提交问题时应进入该卡绑定的任务，而不是当前选中的另一任务。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储测试卡片表单回调所需的桥接应用配置。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=False,
            )
            # app 存储用于验证卡片任务隔离的桥接应用。
            app = BridgeApp(args)
            app.task_manager.create_task("ou_user", "任务一")
            # first_task_id 存储第一张卡片永久绑定的任务 ID。
            first_task_id = app.task_manager.current_task_id_for_sender("ou_user")
            app.task_manager.create_task("ou_user", "任务二")
            with mock.patch.object(app, "_handle_event_streaming", return_value=True) as streaming:
                app._handle_card_action(
                    {
                        "event_id": "evt_form",
                        "action_name": f"chat_send_{first_task_id}",
                        "form_value": json.dumps({f"chat_input_{first_task_id}": "继续任务一"}),
                        "operator_id": "ou_user",
                        "message_id": "om_card_one",
                        "chat_id": "oc_chat",
                    }
                )

        # routed_message 存储表单回调转换出的内部消息。
        routed_message = streaming.call_args.args[0]
        self.assertEqual(routed_message.text, "继续任务一")
        self.assertEqual(streaming.call_args.kwargs["task_id"], first_task_id)
        self.assertFalse(streaming.call_args.kwargs["track_source_message"])
        self.assertTrue(streaming.call_args.kwargs["clear_input"])
        self.assertEqual(app.task_manager.current_task_id_for_sender("ou_user"), first_task_id)

    def test_card_chat_submit_works_without_action_name(self):
        """SDK 未返回按钮 name 时，应从显式 callback value 识别表单提交。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储测试 callback value 表单提交所需的桥接配置。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=False,
            )
            # app 存储用于验证无 action_name 表单回调的桥接应用。
            app = BridgeApp(args)
            app.task_manager.create_task("ou_user", "回调任务")
            # task_id 存储表单显式绑定的任务 ID。
            task_id = app.task_manager.current_task_id_for_sender("ou_user")
            app.task_cards[task_id] = ("card_active", "om_active_card", 12)
            with mock.patch.object(app, "_handle_event_streaming", return_value=True) as streaming:
                app._handle_card_action(
                    {
                        "event_id": "evt_callback_form",
                        "action_name": "",
                        "action_value": json.dumps({"action": "card_chat_submit", "task_id": task_id}),
                        "form_value": json.dumps({f"chat_input_{task_id}": "从卡片继续"}),
                        "operator_id": "ou_user",
                        "message_id": "om_active_card",
                        "chat_id": "oc_chat",
                    }
                )

        # submitted_message 存储 callback value 路径生成的内部消息。
        submitted_message = streaming.call_args.args[0]
        self.assertEqual(submitted_message.text, "从卡片继续")
        self.assertEqual(streaming.call_args.kwargs["task_id"], task_id)
        self.assertTrue(streaming.call_args.kwargs["clear_input"])
        self.assertEqual(app.task_cards[task_id], ("card_active", "om_active_card", 12))

    def test_card_chat_submit_accepts_enter_input_value_and_deduplicates_button_callback(self):
        """Enter 输入回调应发送 input_value，并忽略紧随其后的同内容按钮回调。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储测试 Enter 提交与重复回调去重所需配置。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=False,
            )
            # app 存储用于验证两种提交路径合并的桥接应用。
            app = BridgeApp(args)
            app.task_manager.create_task("ou_user", "Enter 任务")
            # task_id 存储输入组件永久绑定的任务 ID。
            task_id = app.task_manager.current_task_id_for_sender("ou_user")
            with mock.patch.object(app, "_handle_event_streaming", return_value=True) as streaming:
                app._handle_card_action(
                    {
                        "event_id": "evt_enter",
                        "action_value": json.dumps({"action": "card_chat_submit", "task_id": task_id}),
                        "input_value": "按回车发送",
                        "operator_id": "ou_user",
                        "message_id": "om_card",
                        "chat_id": "oc_chat",
                    }
                )
                app._handle_card_action(
                    {
                        "event_id": "evt_button_after_enter",
                        "action_name": f"chat_send_{task_id}",
                        "form_value": json.dumps({f"chat_input_{task_id}": "按回车发送"}),
                        "operator_id": "ou_user",
                        "message_id": "om_card",
                        "chat_id": "oc_chat",
                    }
                )

        self.assertEqual(streaming.call_count, 1)
        # submitted_message 存储 Enter 回调转换出的内部消息。
        submitted_message = streaming.call_args.args[0]
        self.assertEqual(submitted_message.text, "按回车发送")
        self.assertTrue(streaming.call_args.kwargs["clear_input"])

    def test_create_task_card_sends_new_independent_card(self):
        """新任务按钮应回复新卡片并保留独立的任务到卡片映射。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储测试新任务卡片创建所需的桥接应用配置。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=False,
            )
            # app 存储用于验证新任务卡片创建的桥接应用。
            app = BridgeApp(args)
            with (
                mock.patch.object(app, "_create_stream_card", return_value="card_new") as create_card,
                mock.patch.object(app, "_send_stream_card", return_value="om_new_card") as send_card,
            ):
                # created 标记新任务卡片流程是否完成。
                created = app._create_task_card("ou_user", "om_old_card")

        # task_id 存储新任务按钮刚创建的任务 ID。
        task_id = app.task_manager.current_task_id_for_sender("ou_user")
        self.assertTrue(created)
        create_card.assert_called_once()
        send_card.assert_called_once_with("om_old_card", "card_new")
        self.assertEqual(app.task_cards[task_id], ("card_new", "om_new_card", 1))

    def test_show_tasks_button_replies_with_task_list(self):
        """每张回答卡的所有任务按钮应另外发送任务列表，而不是替换当前卡。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储测试所有任务按钮所需的桥接应用配置。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=False,
            )
            # app 存储用于验证任务列表入口的桥接应用。
            app = BridgeApp(args)
            with mock.patch.object(app, "_send_task_list_card", return_value=True) as send_list:
                app._handle_card_action(
                    {
                        "event_id": "evt_tasks_button",
                        "action_value": json.dumps({"action": "show_tasks", "task_id": "t1"}),
                        "operator_id": "ou_user",
                        "message_id": "om_answer_card",
                        "chat_id": "oc_chat",
                    }
                )

        # task_message 存储按钮回调生成的任务列表内部消息。
        task_message = send_list.call_args.args[0]
        self.assertEqual(task_message.message_id, "om_answer_card")
        self.assertEqual(task_message.text, "/tasks")

    def test_open_existing_task_sends_new_active_card(self):
        """任务列表点击打开时应回复已有任务的新活动卡片，并保留列表卡。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储测试打开已有任务卡片所需的桥接应用配置。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=False,
            )
            # app 存储用于验证已有任务重新打开的桥接应用。
            app = BridgeApp(args)
            app.task_manager.create_task("ou_user", "已有任务")
            # task_id 存储需要从任务列表打开的已有任务 ID。
            task_id = app.task_manager.current_task_id_for_sender("ou_user")
            with (
                mock.patch.object(app, "_create_stream_card", return_value="card_opened") as create_card,
                mock.patch.object(app, "_send_stream_card", return_value="om_opened") as send_card,
            ):
                # opened 标记已有任务活动卡片是否创建成功。
                opened = app._open_existing_task_card(task_id, "om_task_list")

        self.assertTrue(opened)
        create_card.assert_called_once()
        send_card.assert_called_once_with("om_task_list", "card_opened")
        self.assertEqual(app.task_cards[task_id], ("card_opened", "om_opened", 1))

    def test_task_card_mapping_survives_bridge_restart(self):
        """服务重启后应恢复任务的 CardKit 实体和序号，让旧卡仍可继续对话。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储两次桥接应用实例共享的测试目录配置。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=False,
            )
            # first_app 存储重启前的桥接应用实例。
            first_app = BridgeApp(args)
            first_app.task_manager.create_task("ou_user", "持久卡片")
            # task_id 存储需要跨重启恢复卡片映射的任务 ID。
            task_id = first_app.task_manager.current_task_id_for_sender("ou_user")
            first_app.task_cards[task_id] = ("card_saved", "om_saved", 17)
            first_app._save_task_cards()
            # second_app 存储模拟服务重启后的新桥接应用实例。
            second_app = BridgeApp(args)

        self.assertEqual(second_app.task_cards[task_id], ("card_saved", "om_saved", 17))

    def test_overflow_callback_reads_selected_option(self):
        """更多菜单回调应从 option 字段解析动作并执行对应后续任务。"""
        with tempfile.TemporaryDirectory() as tmp:
            # args 存储测试卡片回调所需的桥接应用配置。
            args = SimpleNamespace(
                log_dir=str(Path(tmp) / "logs"),
                workspace=str(Path(tmp) / "workspace"),
                system_prompt="测试提示",
                claude_timeout=5,
                lark_identity="bot",
                lark_profile=DEFAULT_LARK_PROFILE,
                reply_identity="bot",
                dry_run=True,
                once=False,
            )
            # app 存储用于解析更多菜单回调的桥接应用。
            app = BridgeApp(args)
            app.task_manager.create_task("ou_user", "菜单任务")
            # task_id 存储更多菜单动作关联的测试任务 ID。
            task_id = app.task_manager.current_task_id_for_sender("ou_user")
            # option 存储飞书 overflow 回调返回的选项值。
            option = json.dumps({"action": "retry", "task_id": task_id, "source_message_id": "om_1"})
            with mock.patch.object(app, "_run_card_followup") as followup:
                app._handle_card_action(
                    {
                        "action_tag": "overflow",
                        "option": option,
                        "operator_id": "ou_user",
                        "token": "token_1",
                    }
                )

        followup.assert_called_once_with("retry", task_id, "ou_user", "om_1")

    def test_build_task_list_card_contains_management_actions(self):
        """任务列表卡片应包含切换、停止、重命名和删除动作。"""
        with tempfile.TemporaryDirectory() as tmp:
            # manager 存储带一个默认任务的测试任务管理器。
            manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            manager.create_task("ou_user", "示例任务")
            # card 存储生成的任务列表卡片。
            card = build_task_list_card(manager.tasks.values(), "t1")

        # actions 存储任务列表中所有按钮的动作名。
        actions = [
            column["elements"][0]["behaviors"][0]["value"]["action"]
            for element in card["body"]["elements"]
            if element.get("tag") == "column_set"
            for column in element["columns"]
        ]
        self.assertEqual(actions, ["task_use", "stop", "task_delete"])
        self.assertTrue(any(element.get("tag") == "form" for element in card["body"]["elements"]))

    def test_extract_card_id_reads_create_card_output(self):
        """应从建卡响应 JSON 里读取 data.card_id。"""
        # output 是模拟的 lark-cli 建卡 stdout。
        output = json.dumps({"ok": True, "data": {"card_id": "7660000000000000000"}})

        self.assertEqual(extract_card_id(output), "7660000000000000000")

    def test_extract_streaming_assistant_text_reads_interim_block(self):
        """增量提取应读取未终稿的中间 assistant 文本，供流式卡片先行显示。"""
        with tempfile.TemporaryDirectory() as tmp:
            # log_path 是模拟的 Claude 会话 JSONL 文件。
            log_path = Path(tmp) / "session.jsonl"
            # interim 是一条 stop_reason 非 end_turn 的中间 assistant 行。
            interim = {
                "type": "assistant",
                "timestamp": "2026-06-28T00:00:01.000Z",
                "message": {
                    "stop_reason": "tool_use",
                    "content": [{"type": "text", "text": "正在整理"}],
                },
            }
            log_path.write_text(json.dumps(interim) + "\n", encoding="utf-8")

            # text 是增量提取到的中间文本；普通提取应因未终稿而拿不到。
            text = extract_streaming_assistant_text(log_path, "2026-06-28T00:00:00.000Z")

            self.assertEqual(text, "正在整理")
            self.assertIsNone(extract_assistant_text(log_path, "2026-06-28T00:00:00.000Z"))

    def test_ask_task_forwards_on_delta_to_session(self):
        """普通消息带流式回调时，ask_task 应把 on_delta 透传给会话的 ask。"""
        # captured 存储会话 ask 收到的 on_delta，用来断言透传成功。
        captured = {}

        class StreamingSession(FakeClaudeSession):
            """记录 on_delta 是否被透传的测试会话。"""

            def ask(self, message, on_delta=None):
                """记录透传进来的流式回调并调用它一次。"""
                captured["on_delta"] = on_delta
                if on_delta is not None:
                    on_delta("增量")
                return f"回复:{message}"

        with tempfile.TemporaryDirectory() as tmp:
            # manager 是使用支持流式的假会话的任务管理器。
            manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=StreamingSession,
            )
            # deltas 存储回调收到的增量文本。
            deltas = []
            answer = manager.handle_text("ou_user", "你好", on_delta=deltas.append)

        self.assertEqual(answer, "回复:你好")
        self.assertIsNotNone(captured["on_delta"])
        self.assertEqual(deltas, ["增量"])

    def test_ask_task_falls_back_when_session_rejects_on_delta(self):
        """会话 ask 只接受单参数时，ask_task 应回退为不带 on_delta 的调用。"""
        with tempfile.TemporaryDirectory() as tmp:
            # manager 使用只接受单参数 ask 的旧式假会话。
            manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            # 带上 on_delta 也应正常返回，不因 TypeError 抛出。
            answer = manager.handle_text("ou_user", "你好", on_delta=lambda text: None)

        self.assertEqual(answer, "回复:你好")


if __name__ == "__main__":
    unittest.main()
