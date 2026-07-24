"""构造回答卡片与任务列表卡片的数据结构。"""

from __future__ import annotations

from typing import Optional


from .claude_protocol import answer_card_content_elements
from .messages import preview_text
from .models import ClaudeTask
from .config import TASK_LIST_PAGE_SIZE
from typing import Iterable
import re


def answer_card_actions(task_id: str, source_message_id: str) -> list[dict]:
    """构造紧凑回答操作栏；task_id 和 source_message_id 用于回调定位上下文。"""
    # base_value 存储所有按钮共享的任务上下文。
    base_value = {"task_id": task_id, "source_message_id": source_message_id}
    # primary_specs 存储始终可见的高频按钮文案、动作和样式。
    primary_specs = [
        ("所有任务", "show_tasks", "primary_filled"),
        ("停止", "stop", "danger"),
        ("新任务", "new_task", "default"),
    ]
    # columns 存储三枚等宽核心按钮，避免菜单按钮与普通按钮尺寸不一致。
    columns: list[dict] = []
    for label, action, button_type in primary_specs:
        # button 存储当前高频操作按钮配置。
        button = {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": button_type,
            "size": "small",
            "width": "fill",
            "behaviors": [
                {"type": "callback", "value": {**base_value, "action": action}}
            ],
        }
        columns.append(
            {"tag": "column", "width": "weighted", "weight": 1, "elements": [button]}
        )
    return [
        {
            "tag": "column_set",
            "flex_mode": "none",
            "horizontal_spacing": "small",
            "columns": columns,
        }
    ]


def answer_card_input_form(task_id: str) -> dict:
    """构造支持 Enter 发送的独立输入组件；task_id 用于把回调绑定到指定任务。"""
    # safe_task_id 存储可安全用于飞书组件 name 和 20 字符 element_id 的任务标识。
    safe_task_id = re.sub(r"[^A-Za-z0-9_]", "_", task_id or "new")[:10]
    return {
        "tag": "input",
        "element_id": f"chat_form_{safe_task_id}",
        "name": f"chat_input_{safe_task_id}",
        # default_value 显式写为空，CardKit 替换组件时才能清除客户端残留输入。
        "default_value": "",
        "input_type": "text",
        "max_length": 1000,
        "width": "fill",
        "placeholder": {"tag": "plain_text", "content": "输入后按 Enter 发送"},
        "behaviors": [
            {
                "type": "callback",
                "value": {"action": "card_chat_submit", "task_id": task_id},
            }
        ],
    }


def build_answer_card_json(
    task_id: str,
    source_message_id: str,
    content: str,
    title: str,
    status: str,
    error: bool = False,
) -> dict:
    """构造可用于回调更新的完整回答卡片 JSON。"""
    # template 存储卡片标题区域的颜色模板。
    template = "red" if error else "blue"
    return {
        "schema": "2.0",
        "config": {"streaming_mode": False},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": status},
            "template": template,
            "icon": {"tag": "standard_icon", "token": "myai_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "medium",
            "elements": [
                *answer_card_content_elements(content),
                answer_card_input_form(task_id),
                *answer_card_actions(task_id, source_message_id),
            ],
        },
    }


def build_task_list_card(
    tasks: Iterable[ClaudeTask],
    current_id: Optional[str],
    page: int = 0,
    managed_task_id: str = "",
) -> dict:
    """构造分页任务中心卡片；page 指定页码，managed_task_id 指定展开管理项。"""
    # sorted_tasks 存储按任务编号倒序排列的任务，新任务优先展示。
    sorted_tasks = sorted(tasks, key=lambda task: int(task.task_id[1:]), reverse=True)
    # total_pages 存储任务中心总页数，空列表也保持一页。
    total_pages = max(
        1, (len(sorted_tasks) + TASK_LIST_PAGE_SIZE - 1) // TASK_LIST_PAGE_SIZE
    )
    # current_page 存储边界约束后的当前页码。
    current_page = min(max(page, 0), total_pages - 1)
    # page_start 存储当前页在完整任务列表中的起始位置。
    page_start = current_page * TASK_LIST_PAGE_SIZE
    # visible_tasks 存储当前页实际展示的任务集合。
    visible_tasks = sorted_tasks[page_start : page_start + TASK_LIST_PAGE_SIZE]
    # elements 存储任务列表卡片的所有正文元素。
    elements: list[dict] = []
    for task in visible_tasks:
        # current_marker 标记当前用户正在使用的任务。
        current_marker = " · 当前" if task.task_id == current_id else ""
        elements.append(
            {
                "tag": "markdown",
                "content": (
                    f"**{task.title}{current_marker}**\n"
                    f"{task.task_id} · {task.status} · {task.turns} 轮\n"
                    f"{preview_text(task.last_question, limit=42) if task.last_question else '尚未开始'}"
                ),
            }
        )
        # base_value 存储当前任务按钮共享的任务 ID。
        base_value = {"task_id": task.task_id}
        # task_actions 存储任务行始终可见的打开和管理按钮。
        task_actions = [
            ("打开", "task_use", "primary_filled"),
            ("管理", "task_manage", "default"),
        ]
        # action_columns 存储 Card 2.0 按钮分栏。
        action_columns: list[dict] = []
        for label, action, button_type in task_actions:
            # button 存储当前任务操作按钮。
            button = {
                "tag": "button",
                "text": {"tag": "plain_text", "content": label},
                "type": button_type,
                "width": "fill",
                "size": "small",
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {
                            **base_value,
                            "action": action,
                            "page": current_page,
                        },
                    }
                ],
            }
            action_columns.append(
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [button],
                }
            )
        elements.append(
            {
                "tag": "column_set",
                "flex_mode": "none",
                "horizontal_spacing": "small",
                "columns": action_columns,
            }
        )
        if task.task_id == managed_task_id:
            # rename_field_name 存储当前展开任务重命名表单的唯一字段名。
            rename_field_name = f"title_{task.task_id}"
            elements.append(
                {
                    "tag": "form",
                    "name": f"rename_form_{task.task_id}",
                    "direction": "horizontal",
                    "elements": [
                        {
                            "tag": "input",
                            "name": rename_field_name,
                            "default_value": task.title,
                            "placeholder": {
                                "tag": "plain_text",
                                "content": "输入新任务名称",
                            },
                            "required": True,
                            "width": "fill",
                        },
                        {
                            "tag": "column_set",
                            "columns": [
                                {
                                    "tag": "column",
                                    "width": "auto",
                                    "elements": [
                                        {
                                            "tag": "button",
                                            "name": f"rename_{task.task_id}",
                                            "text": {
                                                "tag": "plain_text",
                                                "content": "重命名",
                                            },
                                            "form_action_type": "submit",
                                            "type": "primary",
                                            "behaviors": [
                                                {
                                                    "type": "callback",
                                                    "value": {
                                                        "action": "task_rename_submit",
                                                        "task_id": task.task_id,
                                                    },
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                }
            )
            # management_actions 存储低频停止和删除操作，仅在用户点管理后展示。
            management_actions = []
            for label, action, button_type in [
                ("停止任务", "stop", "default"),
                ("删除任务", "task_delete", "danger"),
            ]:
                # management_button 存储当前低频管理按钮配置。
                management_button = {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": label},
                    "type": button_type,
                    "size": "small",
                    "width": "fill",
                    "behaviors": [
                        {
                            "type": "callback",
                            "value": {
                                "action": action,
                                "task_id": task.task_id,
                                "page": current_page,
                                "surface": "task_center",
                            },
                        }
                    ],
                }
                if action == "task_delete":
                    management_button["confirm"] = {
                        "title": {"tag": "plain_text", "content": "删除任务"},
                        "text": {
                            "tag": "plain_text",
                            "content": f"确认删除 {task.title}？",
                        },
                    }
                management_actions.append(
                    {
                        "tag": "column",
                        "width": "weighted",
                        "weight": 1,
                        "elements": [management_button],
                    }
                )
            elements.append(
                {
                    "tag": "column_set",
                    "horizontal_spacing": "small",
                    "columns": management_actions,
                }
            )
        elements.append({"tag": "hr"})
    if not elements:
        elements.append(
            {
                "tag": "markdown",
                "content": "当前还没有任务。发送消息即可创建新对话。",
            }
        )
    if sorted_tasks:
        # pagination_columns 存储任务中心上一页、页码和下一页控制区。
        pagination_columns = []
        for label, target_page, disabled in [
            ("上一页", current_page - 1, current_page == 0),
            (f"{current_page + 1} / {total_pages}", current_page, True),
            ("下一页", current_page + 1, current_page >= total_pages - 1),
        ]:
            # pagination_button 存储当前翻页按钮配置。
            pagination_button = {
                "tag": "button",
                "text": {"tag": "plain_text", "content": label},
                "size": "small",
                "width": "fill",
                "disabled": disabled,
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {"action": "task_page", "page": target_page},
                    }
                ],
            }
            pagination_columns.append(
                {
                    "tag": "column",
                    "width": "weighted",
                    "weight": 1,
                    "elements": [pagination_button],
                }
            )
        elements.append(
            {
                "tag": "column_set",
                "horizontal_spacing": "small",
                "columns": pagination_columns,
            }
        )
    return {
        "schema": "2.0",
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"任务中心 · {len(sorted_tasks)}",
            },
            "template": "blue",
            "icon": {"tag": "standard_icon", "token": "todo_colorful"},
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "vertical_spacing": "medium",
            "elements": elements,
        },
    }
