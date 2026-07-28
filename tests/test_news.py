"""AI 新闻定时推送功能测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from visual_lark_bridge import NewsEntry
from visual_lark_bridge import NewsScheduler
from visual_lark_bridge import build_digest_prompt
from visual_lark_bridge import build_lark_send_chat_message_args
from visual_lark_bridge import build_news_summarizer_args
from visual_lark_bridge import due_schedule_key
from visual_lark_bridge import load_news_config
from visual_lark_bridge import parse_feed
from visual_lark_bridge import select_unseen_entries
from lark_bridge.bridge_transport import BridgeTransportMixin


class NewsConfigTest(unittest.TestCase):
    """验证桌面配置在 Python 边界的校验与回退。"""

    def test_invalid_fields_are_filtered_or_clamped(self) -> None:
        """非法目标、时刻和 URL 应被丢弃，条数收敛到上限。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # config_path 存储测试用桌面配置文件。
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "news": {
                            "enabled": True,
                            "delivery_type": "webhook",
                            "chat_id": "invalid",
                            "webhook_url": "https://example.com/not-feishu",
                            "times": ["09:07", "25:00", "09:07"],
                            "sources": [
                                {"name": "valid", "url": "https://example.com/rss"},
                                {"name": "bad", "url": "file:///tmp/feed"},
                            ],
                            "max_items": 99,
                        }
                    }
                ),
                encoding="utf-8",
            )
            # config 存储经过校验的新闻配置。
            config = load_news_config(config_path)
        self.assertEqual(config.chat_id, "")
        self.assertEqual(config.delivery_type, "webhook")
        self.assertEqual(config.webhook_url, "")
        self.assertEqual(config.times, ("09:07",))
        self.assertEqual(len(config.sources), 1)
        self.assertEqual(config.max_items, 20)
        self.assertFalse(config.runnable)

    def test_valid_webhook_target_is_runnable_without_chat_id(self) -> None:
        """选择 Webhook 时只要求合法机器人地址，不应继续依赖会话 Chat ID。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # config_path 存储 Webhook 配置测试文件。
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "news": {
                            "enabled": True,
                            "delivery_type": "webhook",
                            "webhook_url": "https://open.feishu.cn/open-apis/bot/v2/hook/test-id",
                            "times": ["09:07"],
                            "sources": [
                                {"name": "A", "url": "https://example.com/rss"}
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_news_config(config_path)

        self.assertTrue(config.runnable)
        self.assertEqual(config.chat_id, "")

    def test_missing_or_broken_file_disables_news(self) -> None:
        """配置文件缺失或损坏时不得启动推送。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # config_path 存储不存在或随后写坏的配置路径。
            config_path = Path(temp_dir) / "config.json"
            self.assertFalse(load_news_config(config_path).enabled)
            config_path.write_text("{broken", encoding="utf-8")
            self.assertFalse(load_news_config(config_path).enabled)


class NewsWebhookTransportTest(unittest.TestCase):
    """验证飞书自定义机器人请求体与成功响应兼容逻辑。"""

    @mock.patch("lark_bridge.bridge_transport.urllib.request.urlopen")
    def test_network_failure_does_not_log_webhook_url(self, urlopen: mock.Mock) -> None:
        """HTTP 异常即使携带请求地址，桥接日志也不得输出 Webhook 凭据。"""
        # webhook_url 存储测试用且会出现在 HTTPError 文本中的机器人地址。
        webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/private-test-id"
        urlopen.side_effect = urllib.error.HTTPError(
            webhook_url, 500, "failed", {}, None
        )
        # log 存储失败链路产生的安全日志。
        log = mock.Mock()
        # transport 存储调用 mixin 方法所需的最小应用边界。
        transport = SimpleNamespace(args=SimpleNamespace(dry_run=False), _log=log)

        sent = BridgeTransportMixin._send_webhook_message(
            transport, webhook_url, "新闻摘要"
        )

        self.assertFalse(sent)
        self.assertNotIn(
            webhook_url, " ".join(str(call) for call in log.call_args_list)
        )

    @mock.patch("lark_bridge.bridge_transport.urllib.request.urlopen")
    def test_sends_text_payload_without_logging_webhook_url(
        self, urlopen: mock.Mock
    ) -> None:
        """Webhook 通知应发送 UTF-8 文本请求，日志不得泄露完整凭据地址。"""
        # response 存储模拟的飞书 Webhook 成功响应上下文。
        response = mock.MagicMock()
        response.read.return_value = b'{"StatusCode":0,"StatusMessage":"success"}'
        urlopen.return_value.__enter__.return_value = response
        # log 存储传输层产生的日志内容。
        log = mock.Mock()
        # transport 存储调用 mixin 方法所需的最小应用边界。
        transport = SimpleNamespace(args=SimpleNamespace(dry_run=False), _log=log)
        # webhook_url 存储测试用飞书机器人地址。
        webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test-webhook-id"

        sent = BridgeTransportMixin._send_webhook_message(
            transport, webhook_url, "新闻摘要"
        )

        self.assertTrue(sent)
        # request 存储实际交给 urllib 的请求对象。
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, webhook_url)
        self.assertIn("新闻摘要", request.data.decode("utf-8"))
        self.assertNotIn(
            webhook_url, " ".join(str(call) for call in log.call_args_list)
        )


class NewsSourceTest(unittest.TestCase):
    """验证 RSS 与 Atom 解析边界。"""

    def test_parses_rss_and_skips_entries_without_required_fields(self) -> None:
        """RSS 仅保留同时包含标题和链接的 item。"""
        # feed 存储包含有效、缺链接和未知字段的 RSS 样本。
        feed = b"""<rss><channel>
        <item><title>First</title><link>https://example.com/1</link><pubDate>Mon, 28 Jul 2026 09:00:00 GMT</pubDate><extra>x</extra></item>
        <item><title>Missing link</title></item>
        </channel></rss>"""
        self.assertEqual(
            parse_feed(feed, "RSS"),
            [
                NewsEntry(
                    title="First",
                    link="https://example.com/1",
                    published="Mon, 28 Jul 2026 09:00:00 GMT",
                    source="RSS",
                )
            ],
        )

    def test_parses_namespaced_atom_and_handles_malformed_xml(self) -> None:
        """Atom 命名空间和 href 链接应被识别，畸形 XML 返回空列表。"""
        # atom 存储带默认命名空间的 Atom 样本。
        atom = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <title>Atom item</title><link rel="alternate" href="https://example.com/a"/><updated>2026-07-28T09:00:00Z</updated>
        </entry></feed>"""
        self.assertEqual(parse_feed(atom, "Atom")[0].link, "https://example.com/a")
        self.assertEqual(parse_feed(b"<rss>", "Broken"), [])
        self.assertEqual(parse_feed(b"<rss><channel/></rss>", "Empty"), [])


class NewsDigestTest(unittest.TestCase):
    """验证去重与不可信输入提示边界。"""

    def test_selects_unseen_unique_entries_with_limit(self) -> None:
        """历史链接和本轮重复链接均不得再次进入摘要。"""
        # entries 存储含历史项与本轮重复项的候选新闻。
        entries = [
            NewsEntry("old", "https://e/old", "", "A"),
            NewsEntry("new", "https://e/new", "", "A"),
            NewsEntry("duplicate", "https://e/new", "", "B"),
            NewsEntry("next", "https://e/next", "", "A"),
        ]
        # selected 存储实际进入本轮摘要的新闻。
        selected = select_unseen_entries(entries, {"https://e/old"}, 2)
        self.assertEqual([item.title for item in selected], ["new", "next"])
        self.assertIn("<external-rss>", build_digest_prompt(selected))


class NewsCommandTest(unittest.TestCase):
    """验证外部 CLI 均使用参数数组构造。"""

    def test_builds_active_lark_send_command(self) -> None:
        """主动发送应携带目标 chat_id、Markdown 和指定 profile。"""
        # args 存储主动发送参数数组。
        args = build_lark_send_chat_message_args(
            "oc_target", "## digest", profile="team-bot"
        )
        self.assertEqual(args[:3], ["lark-cli", "--profile", "team-bot"])
        self.assertIn("+messages-send", args)
        self.assertEqual(args[args.index("--chat-id") + 1], "oc_target")

    def test_builds_claude_and_codex_summarizer_commands(self) -> None:
        """两种 provider 应生成各自的非交互命令并保留模型配置。"""
        # claude_args 存储 Claude 摘要参数。
        claude_args = build_news_summarizer_args("claude", "prompt")
        # codex_args 存储 Codex 摘要参数。
        codex_args = build_news_summarizer_args("codex", "prompt", "gpt-test")
        self.assertEqual(claude_args[:2], ["claude", "--print"])
        self.assertEqual(codex_args[:3], ["codex", "exec", "--full-auto"])
        self.assertIn("gpt-test", codex_args)


class NewsSchedulerTest(unittest.TestCase):
    """验证调度幂等、状态恢复和成功推送链路。"""

    def test_due_key_matches_current_or_recent_missed_schedule(self) -> None:
        """同一分钟不得重复执行，服务离线后应补发六小时内错过的最近时刻。"""
        # now 存储固定调度时间。
        now = datetime(2026, 7, 28, 9, 7)
        self.assertEqual(due_schedule_key(now, ("09:07",), ""), "2026-07-28 09:07")
        self.assertEqual(due_schedule_key(now, ("09:07",), "2026-07-28 09:07"), "")
        self.assertEqual(due_schedule_key(now, ("18:07",), ""), "")
        self.assertEqual(
            due_schedule_key(datetime(2026, 7, 29, 0, 10), ("23:50",), ""),
            "2026-07-28 23:50",
        )
        self.assertEqual(due_schedule_key(datetime(2026, 7, 29, 7), ("23:50",), ""), "")

    @mock.patch("lark_bridge.news_scheduler.summarize_news", return_value="摘要")
    @mock.patch("lark_bridge.news_scheduler.fetch_all_sources")
    def test_successful_run_sends_once_and_persists_seen_links(
        self, fetch_all_sources: mock.Mock, summarize_news: mock.Mock
    ) -> None:
        """成功推送后同一分钟不得重复，链接应写入有界状态。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # root 存储本测试隔离的配置、状态和工作目录。
            root = Path(temp_dir)
            # config_path 存储可运行的新闻配置。
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "news": {
                            "enabled": True,
                            "chat_id": "oc_target",
                            "times": ["09:07"],
                            "sources": [
                                {"name": "A", "url": "https://example.com/rss"}
                            ],
                            "max_items": 5,
                        }
                    }
                ),
                encoding="utf-8",
            )
            fetch_all_sources.return_value = [
                NewsEntry("new", "https://e/new", "", "A")
            ]
            # send_message 记录主动推送调用。
            send_message = mock.Mock(return_value=True)
            # scheduler 存储待执行的新闻调度器。
            scheduler = NewsScheduler(
                config_path,
                root,
                root / "workspace",
                "claude",
                "",
                send_message,
                mock.Mock(),
            )
            # now 存储两次调用共用的同一分钟。
            now = datetime(2026, 7, 28, 9, 7)
            self.assertTrue(scheduler.run_once(now))
            self.assertFalse(scheduler.run_once(now))
            # state 存储成功推送后的持久化去重状态。
            state = json.loads((root / "news-state.json").read_text(encoding="utf-8"))
        send_message.assert_called_once()
        summarize_news.assert_called_once()
        self.assertEqual(state["seen_links"], ["https://e/new"])

    @mock.patch(
        "lark_bridge.news_scheduler.summarize_news", return_value="Webhook 摘要"
    )
    @mock.patch("lark_bridge.news_scheduler.fetch_all_sources")
    def test_webhook_delivery_uses_selected_channel(
        self, fetch_all_sources: mock.Mock, summarize_news: mock.Mock
    ) -> None:
        """选择 Webhook 后调度器只能调用 Webhook 发送边界，不得误发到会话。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # root 存储 Webhook 调度测试的配置和状态目录。
            root = Path(temp_dir)
            # webhook_url 存储测试用合法飞书机器人地址。
            webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/test-webhook-id"
            (root / "config.json").write_text(
                json.dumps(
                    {
                        "news": {
                            "enabled": True,
                            "delivery_type": "webhook",
                            "webhook_url": webhook_url,
                            "times": ["09:07"],
                            "sources": [
                                {"name": "A", "url": "https://example.com/rss"}
                            ],
                            "max_items": 5,
                        }
                    }
                ),
                encoding="utf-8",
            )
            fetch_all_sources.return_value = [
                NewsEntry("new", "https://e/new", "", "A")
            ]
            # send_chat 和 send_webhook 分别记录两种通知边界的调用。
            send_chat = mock.Mock(return_value=True)
            send_webhook = mock.Mock(return_value=True)
            # scheduler 存储选择 Webhook 的待执行调度器。
            scheduler = NewsScheduler(
                root / "config.json",
                root,
                root,
                "claude",
                "",
                send_chat,
                mock.Mock(),
                send_webhook,
            )
            self.assertTrue(scheduler.run_once(datetime(2026, 7, 28, 9, 7)))

        send_chat.assert_not_called()
        send_webhook.assert_called_once()
        self.assertEqual(send_webhook.call_args.args[0], webhook_url)

    @mock.patch(
        "lark_bridge.news_scheduler.summarize_news",
        side_effect=[RuntimeError("temporary"), "重试成功"],
    )
    @mock.patch("lark_bridge.news_scheduler.fetch_all_sources")
    def test_failed_summary_does_not_mark_schedule_complete(
        self, fetch_all_sources: mock.Mock, summarize_news: mock.Mock
    ) -> None:
        """摘要临时失败后不得提前完成该时刻，下一轮检查应继续尝试并成功发送。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # root 存储失败重试测试的配置和状态目录。
            root = Path(temp_dir)
            # config_path 存储可运行的新闻配置。
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "news": {
                            "enabled": True,
                            "chat_id": "oc_target",
                            "times": ["23:50"],
                            "sources": [
                                {"name": "A", "url": "https://example.com/rss"}
                            ],
                            "max_items": 5,
                        }
                    }
                ),
                encoding="utf-8",
            )
            fetch_all_sources.return_value = [
                NewsEntry("new", "https://e/new", "", "A")
            ]
            # send_message 记录失败重试后真正发生的主动推送。
            send_message = mock.Mock(return_value=True)
            # scheduler 存储待验证失败恢复行为的调度器。
            scheduler = NewsScheduler(
                config_path,
                root,
                root / "workspace",
                "claude",
                "",
                send_message,
                mock.Mock(),
            )
            # now 存储错过 23:50 后仍处于补发窗口的当前时间。
            now = datetime(2026, 7, 29, 0, 10)
            self.assertFalse(scheduler.run_once(now))
            self.assertFalse((root / "news-state.json").exists())
            self.assertTrue(scheduler.run_once(now))

        self.assertEqual(summarize_news.call_count, 2)
        send_message.assert_called_once()

    def test_broken_state_is_treated_as_empty(self) -> None:
        """损坏状态文件不得让调度器崩溃。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # root 存储损坏状态测试目录。
            root = Path(temp_dir)
            (root / "news-state.json").write_text("{broken", encoding="utf-8")
            # scheduler 存储仅用于读取状态的调度器。
            scheduler = NewsScheduler(
                root / "config.json", root, root, "claude", "", mock.Mock(), mock.Mock()
            )
            self.assertEqual(scheduler._load_state(), ([], ""))


if __name__ == "__main__":
    unittest.main()
