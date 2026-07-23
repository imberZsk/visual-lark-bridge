"""BridgeAppTest 职责测试。"""

import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

from lark_ai_bridge import (
    BridgeApp,
    ClaudeTaskManager,
    LarkMessage,
    DEFAULT_LARK_PROFILE,
    DEFAULT_PROCESSING_TEXT,
)

from test_helpers import BlockingClaudeSession, FakeClaudeSession, RecordingBridgeApp


class BridgeAppTest(unittest.TestCase):
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
            task.session = FakeClaudeSession(
                task.workspace, Path(tmp) / "logs", "测试提示", 5
            )
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
            message = LarkMessage(
                "evt", "om_source", "ou_user", "oc_chat", "旧内容", "p2p", "file"
            )
            with (
                mock.patch.object(
                    app,
                    "_get_message_detail",
                    side_effect=[
                        {"content": "更新后的问题 file_abc", "reply_to": "om_quote"},
                        {"content": "被引用的回答"},
                    ],
                ),
                mock.patch.object(
                    app, "_download_message_resources", return_value=("/tmp/file.pdf",)
                ),
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


if __name__ == "__main__":
    unittest.main()
