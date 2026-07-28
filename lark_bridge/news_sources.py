"""抓取并解析 RSS/Atom 新闻源。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.request import Request
from urllib.request import urlopen
from xml.etree import ElementTree

from .config import NEWS_FETCH_TIMEOUT_SECONDS
from .news_config import NewsSource


# NEWS_USER_AGENT 存储 RSS 请求标识，避免部分站点拒绝标准库默认客户端。
NEWS_USER_AGENT = "VisualLarkBridge/0.2 RSS Reader"


@dataclass(frozen=True)
class NewsEntry:
    """描述从 RSS/Atom 归一化后的单条新闻。"""

    title: str
    link: str
    published: str
    source: str


def local_name(tag: str) -> str:
    """移除 XML 命名空间并返回标签本地名。"""
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element: ElementTree.Element, names: set[str]) -> str:
    """返回 element 首个匹配子节点的非空文本。"""
    for child in element:
        if local_name(child.tag) in names and child.text and child.text.strip():
            return child.text.strip()
    return ""


def entry_link(element: ElementTree.Element) -> str:
    """读取 RSS 文本链接或 Atom href 链接。"""
    for child in element:
        if local_name(child.tag) != "link":
            continue
        # href 存储 Atom link 节点的链接属性。
        href = child.attrib.get("href", "").strip()
        if href and child.attrib.get("rel", "alternate") in {"", "alternate"}:
            return href
        if child.text and child.text.strip():
            return child.text.strip()
    return ""


def parse_feed(data: bytes, source_name: str) -> list[NewsEntry]:
    """把 RSS/Atom 字节流解析成新闻列表；source_name 标识来源。"""
    try:
        # root 存储 XML feed 根节点。
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return []
    # entry_elements 存储 RSS item 或 Atom entry 节点。
    entry_elements = [
        element for element in root.iter() if local_name(element.tag) in {"item", "entry"}
    ]
    # entries 存储标题和链接齐全的归一化结果。
    entries: list[NewsEntry] = []
    for element in entry_elements:
        # title 存储当前条目的可见标题。
        title = child_text(element, {"title"})
        # link 存储当前条目的原文地址。
        link = entry_link(element)
        if not title or not link:
            continue
        # published 存储 RSS/Atom 可能使用的发布时间字段原文。
        published = child_text(element, {"pubdate", "published", "updated", "date"})
        entries.append(NewsEntry(title=title, link=link, published=published, source=source_name))
    return entries


def published_timestamp(value: str) -> float:
    """把常见 RSS/Atom 日期转换为排序时间戳，无法识别时返回零。"""
    if not value:
        return 0.0
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, OverflowError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0


def fetch_source(source: NewsSource) -> list[NewsEntry]:
    """抓取单个信息源并返回解析结果；source 提供名称和 URL。"""
    # request 存储带明确客户端标识的 RSS HTTP 请求。
    request = Request(source.url, headers={"User-Agent": NEWS_USER_AGENT})
    with urlopen(request, timeout=NEWS_FETCH_TIMEOUT_SECONDS) as response:
        return parse_feed(response.read(), source.name)


def fetch_all_sources(
    sources: tuple[NewsSource, ...], on_error: Callable[[str], None]
) -> list[NewsEntry]:
    """依次抓取所有来源；单源失败通过 on_error 记录且不影响其他来源。"""
    # entries 存储全部成功来源的新闻条目。
    entries: list[NewsEntry] = []
    for source in sources:
        try:
            entries.extend(fetch_source(source))
        except Exception as exc:
            on_error(f"抓取新闻源失败 source={source.name}: {exc}")
    return sorted(entries, key=lambda item: published_timestamp(item.published), reverse=True)
