"""ClaudeTest 职责测试。"""

import errno
import json
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

from visual_lark_bridge import (
    ClaudeInteractiveSession,
    ClaudeTaskManager,
    answer_card_input_form,
    build_lark_replace_element_args,
    extract_assistant_text,
    find_jsonl_containing_text,
    compact_stream_preview,
    friendly_tool_phase,
    format_pty_submission,
    parse_claude_stream_event,
    project_log_dir_for_cwd,
    should_accept_trust_prompt,
)

from test_helpers import FakeClaudeSession


class ClaudeTest(unittest.TestCase):
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
            log_path.write_text(
                json.dumps(interim, ensure_ascii=False) + "\n", encoding="utf-8"
            )

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
            log_path.write_text(
                json.dumps(interim, ensure_ascii=False) + "\n", encoding="utf-8"
            )
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
                mock.patch.object(
                    session, "_ask_once", side_effect=[eio_error, "新会话回答"]
                ) as ask_once,
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

    def test_project_log_dir_for_cwd_matches_claude_path_encoding(self):
        """Claude 项目日志目录应按绝对路径里的斜杠替换为短横线。"""
        # workspace_path 存储不包含开发者个人信息的模拟工作区绝对路径。
        workspace_path = Path(
            "/Users/example/projects/lark-claude-bridge/claude-workspace"
        )
        # log_dir 存储 Claude 对模拟工作区编码后的项目日志目录。
        log_dir = project_log_dir_for_cwd(workspace_path)

        self.assertEqual(
            log_dir,
            Path.home()
            / ".claude"
            / "projects"
            / "-Users-example-projects-lark-claude-bridge-claude-workspace",
        )

    def test_should_accept_trust_prompt_detects_compact_tui_text(self):
        """Claude TUI 首屏被清洗后没有空格时，也应识别为信任确认。"""
        screen = (
            "Quicksafetycheck:Isthisaprojectyoucreatedoroneyoutrust? Entertoconfirm"
        )

        self.assertTrue(should_accept_trust_prompt(screen))

    def test_should_accept_trust_prompt_detects_external_import_prompt(self):
        """Claude 请求允许导入上级说明文件时，也应识别为可确认页。"""
        # screen 存储 Claude TUI 清洗后的外部说明文件授权提示。
        screen = "Allow external CLAUDE.mdfileimports? External imports:/Users/example/project/AGENTS.md"

        self.assertTrue(should_accept_trust_prompt(screen))

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
        answer_text, thinking_text, display_text, session_id = (
            parse_claude_stream_event(
                thinking_payload,
                "",
                "",
            )
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
        _, _, retry_display, _ = parse_claude_stream_event(
            retry_payload, answer_text, thinking_text
        )
        self.assertEqual(retry_display, "Claude 服务繁忙，正在重试（第 2 次）...")

        # tool_payload 存储模拟的 Claude 工具调用开始事件。
        tool_payload = {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "Bash"},
            },
        }
        _, _, tool_display, _ = parse_claude_stream_event(
            tool_payload, answer_text, thinking_text
        )
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
        self.assertEqual(serialized_form["default_value"], "")

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
