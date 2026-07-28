"""组合桥接应用的状态、事件、卡片动作与传输职责。"""

from __future__ import annotations

import threading
from pathlib import Path


from .bridge_state import BridgeStateMixin
from .bridge_events import BridgeEventMixin
from .bridge_actions import BridgeActionMixin
from .bridge_transport import BridgeTransportMixin


from .config import DEFAULT_EVENT_GATEWAY
from .config import DEFAULT_LARK_CONFIG
from .consumers import LarkGatewayConsumer
from .task_manager import ClaudeTaskManager
from .claude_stream_session import ClaudeStreamSession
from .codex_session import CodexSession
from .news_scheduler import NewsScheduler
import argparse


class BridgeApp(
    BridgeStateMixin, BridgeEventMixin, BridgeActionMixin, BridgeTransportMixin
):
    def __init__(self, args: argparse.Namespace):
        """根据命令行参数初始化桥接应用。"""
        # args 保存命令行参数配置。
        self.args = args
        # log_dir 是桥接应用所有运行日志的目录。
        self.log_dir = Path(args.log_dir).expanduser().resolve()
        # processed_event_ids 保存已处理飞书事件 ID，避免重复回复。
        self.processed_event_ids: set[str] = set()
        # task_manager 管理多个独立 Claude 任务窗口。
        # session_factory 根据桌面端选择创建 Claude 或 Codex 会话。
        session_factory = ClaudeStreamSession if getattr(args, "provider", "claude") == "claude" else CodexSession
        self.task_manager = ClaudeTaskManager(
            workspace_root=Path(args.workspace).expanduser().resolve(),
            log_dir=self.log_dir,
            system_prompt=args.system_prompt,
            timeout=args.claude_timeout,
            session_factory=session_factory,
        )
        # consumer 管理同时包含普通消息和卡片回调的官方 SDK 单长连接。
        self.consumer = LarkGatewayConsumer(
            gateway_path=Path(getattr(args, "event_gateway", DEFAULT_EVENT_GATEWAY))
            .expanduser()
            .resolve(),
            config_path=Path(getattr(args, "lark_config", DEFAULT_LARK_CONFIG))
            .expanduser()
            .resolve(),
            profile=args.lark_profile,
            log_dir=self.log_dir,
        )
        # bridge_log_path 是桥接服务自身的运行日志文件。
        self.bridge_log_path = self.log_dir / "bridge.log"
        # worker_threads 存储正在后台处理 Claude 长任务的线程。
        self.worker_threads: list[threading.Thread] = []
        # worker_threads_lock 保护后台线程列表的增删读取。
        self.worker_threads_lock = threading.Lock()
        # card_state_path 存储任务与 CardKit 实体映射的持久化文件路径。
        self.card_state_path = self.log_dir / "cards-state.json"
        # task_cards 存储每个任务复用的流式卡片实体与消息 ID，减少重复消息。
        self.task_cards: dict[str, tuple[str, str, int]] = self._load_task_cards()
        # task_source_messages 存储每个任务最近一次用户源消息 ID，供重试读取编辑后的内容。
        self.task_source_messages: dict[str, str] = {}
        # task_history_pages 存储每张活动任务卡当前查看的历史页，零表示最新页。
        self.task_history_pages: dict[str, int] = {}
        # recent_card_submissions 存储任务最近一次提交的内容与时间，用于合并 Enter 和按钮重复回调。
        self.recent_card_submissions: dict[str, tuple[str, float]] = {}
        # news_scheduler 存储可选的 AI 新闻后台调度器；未传配置路径时保持禁用。
        news_config_value = getattr(args, "news_config", "")
        self.news_scheduler = (
            NewsScheduler(
                config_path=Path(news_config_value).expanduser().resolve(),
                state_dir=self.log_dir,
                workspace=self.task_manager.workspace_root,
                provider=getattr(args, "provider", "claude"),
                codex_model=getattr(args, "codex_model", ""),
                send_message=self._send_chat_message,
                log=self._log,
            )
            if news_config_value
            else None
        )
