"""CardInteractionTest 职责测试。"""

import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace

from lark_ai_bridge import (
    BridgeApp,
    LarkMessage,
    DEFAULT_LARK_PROFILE,
    STREAM_CARD_SUMMARY_ID,
)


class CardInteractionTest(unittest.TestCase):
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

            def record_stream(
                card_id, content, sequence, element_id=STREAM_CARD_SUMMARY_ID
            ):
                """记录卡片正文更新；card_id、content、sequence 和 element_id 对应 CardKit 更新参数。"""
                streamed_contents.append((content, sequence, element_id))
                return True

            def answer_with_delta(task_id, question, on_delta=None):
                """模拟 Claude 先推送增量再返回终稿；task_id 和 question 标识本轮任务与问题。"""
                if on_delta is not None:
                    on_delta("新回答增量")
                return "新回答终稿"

            with (
                mock.patch("lark_bridge.bridge_events.STREAM_MIN_INTERVAL", 0),
                mock.patch.object(
                    app, "_stream_card_content", side_effect=record_stream
                ),
                mock.patch.object(
                    app, "_replace_card_element", return_value=True
                ) as replace_element,
                mock.patch.object(
                    app.task_manager, "ask_task", side_effect=answer_with_delta
                ),
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
            with mock.patch.object(
                app, "_handle_event_streaming", return_value=True
            ) as streaming:
                app._handle_card_action(
                    {
                        "event_id": "evt_form",
                        "action_name": f"chat_send_{first_task_id}",
                        "form_value": json.dumps(
                            {f"chat_input_{first_task_id}": "继续任务一"}
                        ),
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
        self.assertEqual(
            app.task_manager.current_task_id_for_sender("ou_user"), first_task_id
        )

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
            with mock.patch.object(
                app, "_handle_event_streaming", return_value=True
            ) as streaming:
                app._handle_card_action(
                    {
                        "event_id": "evt_callback_form",
                        "action_name": "",
                        "action_value": json.dumps(
                            {"action": "card_chat_submit", "task_id": task_id}
                        ),
                        "form_value": json.dumps(
                            {f"chat_input_{task_id}": "从卡片继续"}
                        ),
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

    def test_card_chat_submit_accepts_enter_input_value_and_deduplicates_button_callback(
        self,
    ):
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
            with mock.patch.object(
                app, "_handle_event_streaming", return_value=True
            ) as streaming:
                app._handle_card_action(
                    {
                        "event_id": "evt_enter",
                        "action_value": json.dumps(
                            {"action": "card_chat_submit", "task_id": task_id}
                        ),
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
                        "form_value": json.dumps(
                            {f"chat_input_{task_id}": "按回车发送"}
                        ),
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
                mock.patch.object(
                    app, "_create_stream_card", return_value="card_new"
                ) as create_card,
                mock.patch.object(
                    app, "_send_stream_card", return_value="om_new_card"
                ) as send_card,
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
            with mock.patch.object(
                app, "_send_task_list_card", return_value=True
            ) as send_list:
                app._handle_card_action(
                    {
                        "event_id": "evt_tasks_button",
                        "action_value": json.dumps(
                            {"action": "show_tasks", "task_id": "t1"}
                        ),
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
                mock.patch.object(
                    app, "_create_stream_card", return_value="card_opened"
                ) as create_card,
                mock.patch.object(
                    app, "_send_stream_card", return_value="om_opened"
                ) as send_card,
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
            option = json.dumps(
                {"action": "retry", "task_id": task_id, "source_message_id": "om_1"}
            )
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


if __name__ == "__main__":
    unittest.main()
