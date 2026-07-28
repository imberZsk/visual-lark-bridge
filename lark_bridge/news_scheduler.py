"""后台调度 AI 新闻抓取、摘要与主动推送。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import NEWS_SCHEDULER_INTERVAL_SECONDS
from .config import NEWS_STATE_LINK_LIMIT
from .news_config import load_news_config
from .news_digest import build_digest_prompt
from .news_digest import format_digest_markdown
from .news_digest import select_unseen_entries
from .news_sources import fetch_all_sources
from .news_summarizer import summarize_news


# NEWS_STATE_FILE 存储新闻去重和末次调度状态文件名。
NEWS_STATE_FILE = "news-state.json"


def due_schedule_key(now: datetime, times: tuple[str, ...], last_run: str) -> str:
    """返回当前分钟应触发的唯一键；非配置时刻或已触发时返回空字符串。"""
    # schedule_key 存储日期与分钟组合，避免同一分钟内重复执行。
    schedule_key = f"{now.date().isoformat()} {now.strftime('%H:%M')}"
    return schedule_key if now.strftime("%H:%M") in times and schedule_key != last_run else ""


class NewsScheduler:
    """管理新闻定时线程及其持久化去重状态。"""

    def __init__(
        self,
        config_path: Path,
        state_dir: Path,
        workspace: Path,
        provider: str,
        codex_model: str,
        send_message: Callable[[str, str], bool],
        log: Callable[[str], None],
    ) -> None:
        """初始化调度器；send_message 接收 chat_id 和 Markdown 正文。"""
        # config_path 存储桌面端统一配置文件路径。
        self.config_path = config_path
        # state_path 存储新闻推送状态文件路径。
        self.state_path = state_dir / NEWS_STATE_FILE
        # workspace 存储新闻摘要 CLI 的工作目录。
        self.workspace = workspace
        # provider 存储当前桌面端选择的 AI 提供方。
        self.provider = provider
        # codex_model 存储可选的 Codex 模型名。
        self.codex_model = codex_model
        # send_message 存储主动消息发送边界函数。
        self.send_message = send_message
        # log 存储桥接日志边界函数。
        self.log = log
        # stop_event 用于中断等待并及时结束线程。
        self.stop_event = threading.Event()
        # thread 存储当前调度后台线程。
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        """启动唯一调度线程，重复调用不会创建第二个线程。"""
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="news-scheduler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """通知调度线程退出并等待回收。"""
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=NEWS_SCHEDULER_INTERVAL_SECONDS + 1)
        self.thread = None

    def _load_state(self) -> tuple[list[str], str]:
        """读取已推送链接和末次调度键，状态损坏时返回空值。"""
        try:
            # payload 存储新闻状态 JSON 根对象。
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return [], ""
        if not isinstance(payload, dict):
            return [], ""
        # links 存储类型有效的历史推送链接。
        raw_links = payload.get("seen_links")
        links = [value for value in raw_links if isinstance(value, str)] if isinstance(raw_links, list) else []
        # last_run 存储最后一次已处理的日期时刻键。
        raw_last_run = payload.get("last_run")
        last_run = raw_last_run if isinstance(raw_last_run, str) else ""
        return links, last_run

    def _save_state(self, seen_links: list[str], last_run: str) -> None:
        """原子保存裁剪后的推送链接和末次调度键。"""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        # payload 存储有界去重状态，避免文件无限增长。
        payload = {"seen_links": seen_links[-NEWS_STATE_LINK_LIMIT:], "last_run": last_run}
        # temporary_path 存储原子替换前的临时文件。
        temporary_path = self.state_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary_path.replace(self.state_path)

    def run_once(self, now: datetime | None = None) -> bool:
        """检查并执行当前分钟的调度；now 仅用于确定性测试。"""
        # config 存储本轮实时读取的新闻配置，使 UI 修改无需重启服务。
        config = load_news_config(self.config_path)
        if not config.runnable:
            return False
        # seen_links 和 last_run 存储本轮开始前的持久化状态。
        seen_links, last_run = self._load_state()
        # current_time 存储本轮调度判断使用的本地时间。
        current_time = now or datetime.now().astimezone()
        # schedule_key 存储本轮唯一执行键。
        schedule_key = due_schedule_key(current_time, config.times, last_run)
        if not schedule_key:
            return False
        # 到点即记为已处理，休眠唤醒或失败后不在同一分钟反复补推。
        self._save_state(seen_links, schedule_key)
        # entries 存储所有可用来源按发布时间排序的新闻。
        entries = fetch_all_sources(config.sources, self.log)
        # selected 存储未推送且落在本次条数上限内的新闻。
        selected = select_unseen_entries(entries, set(seen_links), config.max_items)
        if not selected:
            self.log(f"新闻调度无新条目 schedule={schedule_key}")
            return False
        try:
            # summary 存储 AI 生成的 Markdown 新闻摘要。
            summary = summarize_news(
                self.provider,
                build_digest_prompt(selected),
                self.workspace,
                self.codex_model,
            )
        except Exception as exc:
            self.log(f"新闻摘要失败 schedule={schedule_key}: {exc}")
            return False
        if not self.send_message(config.chat_id, format_digest_markdown(summary)):
            self.log(f"新闻主动推送失败 schedule={schedule_key}")
            return False
        self._save_state(seen_links + [entry.link for entry in selected], schedule_key)
        self.log(f"新闻主动推送完成 schedule={schedule_key} items={len(selected)}")
        return True

    def _run(self) -> None:
        """循环检查配置与当前时刻，异常仅影响单次调度。"""
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:
                self.log(f"新闻调度异常：{exc}")
            self.stop_event.wait(NEWS_SCHEDULER_INTERVAL_SECONDS)
