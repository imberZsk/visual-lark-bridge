"""CardBuilderTest 职责测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from visual_lark_bridge import (
    ClaudeTaskManager,
    DEFAULT_LARK_PROFILE,
    DEFAULT_PROCESSING_TEXT,
    STREAM_CARD_META_ID,
    STREAM_CARD_SUMMARY_ID,
    answer_card_actions,
    build_lark_consume_args,
    build_task_list_card,
    build_lark_create_card_args,
    build_lark_finish_stream_args,
    build_lark_send_card_args,
    extract_card_id,
    extract_assistant_text,
    extract_streaming_assistant_text,
    conversation_card_content,
)

from test_helpers import FakeClaudeSession


class CardBuilderTest(unittest.TestCase):
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

    def test_build_lark_create_card_args_opens_streaming_mode(self):
        """建卡命令应走 cardkit v1，且卡片 JSON 打开 streaming_mode、带正文元素 ID。"""
        # args 是建卡命令行数组，profile 固定为桥接机器人。
        args = build_lark_create_card_args(profile=DEFAULT_LARK_PROFILE)

        self.assertEqual(
            args[:6],
            [
                "lark-cli",
                "--profile",
                DEFAULT_LARK_PROFILE,
                "api",
                "POST",
                "/open-apis/cardkit/v1/cards",
            ],
        )
        # data_index 是 --data 参数值在 argv 中的位置。
        data_index = args.index("--data") + 1
        # payload 是建卡请求体，data 字段是卡片 JSON 字符串。
        payload = json.loads(args[data_index])
        self.assertEqual(payload["type"], "card_json")
        # card 是解析后的卡片 JSON，用来断言流式模式和元素 ID。
        card = json.loads(payload["data"])
        self.assertTrue(card["config"]["streaming_mode"])
        # 首个元素是独立的元数据头，建卡时为空，避免其变化打断正文流式前缀。
        self.assertEqual(
            card["body"]["elements"][0]["element_id"], STREAM_CARD_META_ID
        )
        # 第二个元素是对话正文，建卡时显示处理占位文本。
        self.assertEqual(
            card["body"]["elements"][1]["element_id"], STREAM_CARD_SUMMARY_ID
        )
        self.assertEqual(
            card["body"]["elements"][1]["content"], DEFAULT_PROCESSING_TEXT
        )
        # component_tags 存储卡片全部顶层组件类型，用于确认没有多余折叠全文区。
        component_tags = [element["tag"] for element in card["body"]["elements"]]
        self.assertNotIn("collapsible_panel", component_tags)

    def test_build_lark_send_card_args_references_card_id(self):
        """发卡命令应以 interactive 类型回复，并用 card_id 引用已建卡片实体。"""
        # args 是发送卡片消息的命令行数组。
        args = build_lark_send_card_args(
            "om_abc", "card_123", profile=DEFAULT_LARK_PROFILE
        )

        self.assertIn("+messages-reply", args)
        self.assertIn("interactive", args)
        # content_index 是 --content 参数值在 argv 中的位置。
        content_index = args.index("--content") + 1
        # content 是卡片消息内容，data.card_id 指向已建卡片。
        content = json.loads(args[content_index])
        self.assertEqual(content["type"], "card")
        self.assertEqual(content["data"]["card_id"], "card_123")

    def test_build_lark_finish_stream_args_closes_streaming_mode(self):
        """定稿命令应 PATCH 卡片 settings，把 streaming_mode 关掉并带 sequence。"""
        # args 是卡片定稿的命令行数组。
        args = build_lark_finish_stream_args(
            "card_123", 9, profile=DEFAULT_LARK_PROFILE
        )

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

    def test_answer_actions_use_three_equal_core_buttons(self):
        """回答操作应只保留三枚等宽核心按钮。"""
        # actions 存储回答卡片的紧凑操作栏。
        actions = answer_card_actions("t1", "om_1")
        # columns 存储三枚等宽按钮。
        columns = actions[0]["columns"]

        self.assertEqual(len(actions), 1)
        self.assertEqual(len(columns), 3)
        self.assertEqual(columns[0]["elements"][0]["text"]["content"], "所有任务")
        self.assertEqual(columns[1]["elements"][0]["text"]["content"], "停止")
        self.assertEqual(columns[2]["elements"][0]["text"]["content"], "新任务")
        self.assertTrue(
            all(column["elements"][0]["size"] == "small" for column in columns)
        )

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
        history = [{"question": f"问题{i}", "answer": f"回答{i}"} for i in range(20)]
        # content 存储裁剪后的最近对话正文。
        content = conversation_card_content(history)

        self.assertNotIn("问题0\n", content)
        self.assertIn("问题19", content)
        self.assertIn("第 1/5 页", content)

    def test_conversation_content_can_open_older_history_page(self):
        """较早页应显示前一组问答，支持用户在固定高度窗口中回看历史。"""
        # history 存储十轮可分页的模拟问答。
        history = [{"question": f"问题{i}", "answer": f"回答{i}"} for i in range(10)]
        # content 存储从最新向前数第二页的问答正文。
        content = conversation_card_content(history, page=1)

        self.assertIn("问题2", content)
        self.assertIn("问题5", content)
        self.assertNotIn("问题9", content)
        self.assertIn("第 2/3 页", content)

    def test_build_task_list_card_keeps_management_actions_collapsed(self):
        """任务中心默认只展示打开和管理，避免每个任务展开低频操作。"""
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
        self.assertIn("task_use", actions)
        self.assertIn("task_manage", actions)
        self.assertNotIn("stop", actions)
        self.assertNotIn("task_delete", actions)
        self.assertFalse(
            any(element.get("tag") == "form" for element in card["body"]["elements"])
        )

    def test_build_task_list_card_expands_only_selected_task_management(self):
        """点击管理后只展开目标任务的重命名、停止和删除操作。"""
        with tempfile.TemporaryDirectory() as tmp:
            # manager 存储带两个任务的测试任务管理器。
            manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            manager.create_task("ou_user", "任务一")
            manager.create_task("ou_user", "任务二")
            # card 存储仅展开 t1 管理区域的任务中心卡片。
            card = build_task_list_card(
                manager.tasks.values(), "t2", managed_task_id="t1"
            )

        # actions 存储展开后所有按钮动作名。
        actions = [
            column["elements"][0]["behaviors"][0]["value"]["action"]
            for element in card["body"]["elements"]
            if element.get("tag") == "column_set"
            for column in element["columns"]
        ]
        self.assertEqual(actions.count("stop"), 1)
        self.assertEqual(actions.count("task_delete"), 1)
        self.assertEqual(
            sum(element.get("tag") == "form" for element in card["body"]["elements"]),
            1,
        )

    def test_build_task_list_card_paginates_large_task_collection(self):
        """任务超过单页数量时仅渲染五项并提供翻页按钮。"""
        with tempfile.TemporaryDirectory() as tmp:
            # manager 存储超过一页的模拟任务集合。
            manager = ClaudeTaskManager(
                workspace_root=Path(tmp) / "workspace",
                log_dir=Path(tmp) / "logs",
                system_prompt="测试提示",
                timeout=5,
                session_factory=FakeClaudeSession,
            )
            for index in range(7):
                manager.create_task("ou_user", f"任务 {index + 1}")
            # card 存储第一页任务中心卡片。
            card = build_task_list_card(manager.tasks.values(), "t7")

        # markdown_elements 存储当前页的任务摘要 Markdown 元素。
        markdown_elements = [
            element
            for element in card["body"]["elements"]
            if element.get("tag") == "markdown"
        ]
        self.assertEqual(len(markdown_elements), 5)
        self.assertEqual(card["header"]["title"]["content"], "任务中心 · 7")

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
            text = extract_streaming_assistant_text(
                log_path, "2026-06-28T00:00:00.000Z"
            )

            self.assertEqual(text, "正在整理")
            self.assertIsNone(
                extract_assistant_text(log_path, "2026-06-28T00:00:00.000Z")
            )


if __name__ == "__main__":
    unittest.main()
