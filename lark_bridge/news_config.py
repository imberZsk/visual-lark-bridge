"""读取并校验桌面端新闻推送配置。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .config import DEFAULT_NEWS_MAX_ITEMS
from .config import NEWS_MAX_ITEMS_LIMIT


# NEWS_TIME_PATTERN 存储每日推送时刻允许的 24 小时格式。
NEWS_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
# NEWS_WEBHOOK_PATTERN 存储允许的飞书自定义机器人 Webhook 地址格式。
NEWS_WEBHOOK_PATTERN = re.compile(
    r"^https://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9-]+$", re.IGNORECASE
)


@dataclass(frozen=True)
class NewsSource:
    """描述一个 RSS/Atom 信息源；name 用于摘要标识，url 用于抓取。"""

    name: str
    url: str


@dataclass(frozen=True)
class NewsConfig:
    """描述调度器可执行的新闻配置。"""

    enabled: bool = False
    delivery_type: str = "chat"
    chat_id: str = ""
    webhook_url: str = ""
    times: tuple[str, ...] = ()
    sources: tuple[NewsSource, ...] = ()
    max_items: int = DEFAULT_NEWS_MAX_ITEMS

    @property
    def runnable(self) -> bool:
        """配置启用且目标、时刻和来源齐全时返回真。"""
        # has_destination 标记所选通知方式是否已经配置对应目标。
        has_destination = (
            bool(self.webhook_url)
            if self.delivery_type == "webhook"
            else bool(self.chat_id)
        )
        return bool(self.enabled and has_destination and self.times and self.sources)


def is_http_url(value: str) -> bool:
    """判断 value 是否是包含主机名的 HTTP(S) URL。"""
    # parsed_url 存储 URL 拆解结果，用于拒绝缺少域名的伪地址。
    parsed_url = urlparse(value)
    return parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc)


def parse_news_config(payload: object) -> NewsConfig:
    """把未知 JSON 值收敛为安全的新闻配置，非法字段回落默认值。"""
    # source 存储可安全读取的 news 对象。
    source = payload if isinstance(payload, dict) else {}
    # chat_id 存储校验后的飞书目标会话 ID。
    raw_chat_id = source.get("chat_id")
    chat_id = raw_chat_id.strip() if isinstance(raw_chat_id, str) else ""
    if not chat_id.startswith("oc_"):
        chat_id = ""
    # delivery_type 存储显式选择的通知方式，未知值回落到兼容旧配置的会话通知。
    delivery_type = "webhook" if source.get("delivery_type") == "webhook" else "chat"
    # webhook_url 存储格式有效的飞书自定义机器人地址。
    raw_webhook_url = source.get("webhook_url")
    webhook_url = raw_webhook_url.strip() if isinstance(raw_webhook_url, str) else ""
    if not NEWS_WEBHOOK_PATTERN.fullmatch(webhook_url):
        webhook_url = ""
    # times 存储去重并排序后的有效每日时刻。
    raw_times = source.get("times")
    times = (
        tuple(
            sorted(
                {
                    value.strip()
                    for value in raw_times
                    if isinstance(value, str)
                    and NEWS_TIME_PATTERN.fullmatch(value.strip())
                }
            )
        )
        if isinstance(raw_times, list)
        else ()
    )
    # sources 存储名称和 URL 均有效的信息源。
    parsed_sources: list[NewsSource] = []
    raw_sources = source.get("sources")
    if isinstance(raw_sources, list):
        for index, item in enumerate(raw_sources, start=1):
            if not isinstance(item, dict):
                continue
            # source_url 存储当前候选来源去除空白后的地址。
            raw_url = item.get("url")
            source_url = raw_url.strip() if isinstance(raw_url, str) else ""
            if not is_http_url(source_url):
                continue
            # source_name 存储 UI 名称，空名称使用稳定的序号回落值。
            raw_name = item.get("name")
            source_name = raw_name.strip() if isinstance(raw_name, str) else ""
            parsed_sources.append(
                NewsSource(source_name or f"信息源 {index}", source_url)
            )
    # max_items 存储收敛到允许区间内的单次条目上限。
    raw_max_items = source.get("max_items")
    max_items = (
        raw_max_items if isinstance(raw_max_items, int) else DEFAULT_NEWS_MAX_ITEMS
    )
    max_items = min(max(max_items, 1), NEWS_MAX_ITEMS_LIMIT)
    return NewsConfig(
        enabled=source.get("enabled") is True,
        delivery_type=delivery_type,
        chat_id=chat_id,
        webhook_url=webhook_url,
        times=times,
        sources=tuple(parsed_sources),
        max_items=max_items,
    )


def load_news_config(config_path: Path) -> NewsConfig:
    """从桌面端 config.json 读取 news 字段，文件异常时禁用推送。"""
    try:
        # payload 存储桌面配置文件的 JSON 根对象。
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return NewsConfig()
    return parse_news_config(payload.get("news") if isinstance(payload, dict) else None)
