"""BridgeActionMixin 拆分出的应用职责。"""

from __future__ import annotations

import json
import subprocess
import time
from typing import Optional


from .cards import build_answer_card_json
from .cards import build_task_list_card
from .claude_protocol import conversation_card_content
from .claude_protocol import format_lark_markdown
from .claude_protocol import render_task_progress
from .config import CARD_HISTORY_PAGE_TURNS
from .config import CARD_SUBMIT_DEDUP_SECONDS
from .config import STREAM_CARD_SUMMARY_ID
from .lark_commands import build_lark_create_custom_card_args
from .lark_commands import build_lark_delayed_card_update_args
from .lark_commands import extract_card_id
from .messages import preview_text
from .models import LarkMessage
import uuid


class BridgeActionMixin:
    def _create_custom_card(self, card: dict) -> Optional[str]:
        """创建任意静态交互卡片实体，成功返回 card_id。"""
        # completed 存储自定义卡片创建命令结果。
        completed = subprocess.run(
            build_lark_create_custom_card_args(
                card,
                identity=self.args.reply_identity,
                profile=self.args.lark_profile,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self._log(f"创建自定义卡片失败：{completed.stderr.strip()}")
            return None
        return extract_card_id(completed.stdout)

    def _send_task_list_card(self, message: LarkMessage) -> bool:
        """回复交互式任务列表卡片，支持任务切换和管理。"""
        # current_id 存储当前发送者选中的任务 ID。
        current_id = self.task_manager.current_task_id_for_sender(message.sender_id)
        # card 存储当前任务快照对应的 Card 2.0 JSON。
        card = build_task_list_card(self.task_manager.tasks.values(), current_id)
        # card_id 存储创建成功的任务列表卡片实体 ID。
        card_id = self._create_custom_card(card)
        if card_id is None:
            return False
        return self._send_stream_card(message.message_id, card_id) is not None

    def _update_callback_card(self, token: str, card: dict) -> bool:
        """使用回调 token 延迟更新整张卡片；token 最多可使用两次。"""
        # completed 存储飞书延迟更新接口结果。
        completed = subprocess.run(
            build_lark_delayed_card_update_args(
                token,
                card,
                identity=self.args.reply_identity,
                profile=self.args.lark_profile,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self._log(f"回调卡片更新失败：{completed.stderr.strip()}")
            return False
        return True

    def _handle_card_action(self, event: dict) -> None:
        """处理卡片内对话、新任务、停止、重试、任务管理和本机快捷入口。"""
        self._log(f"收到卡片动作：{json.dumps(event, ensure_ascii=False)}")
        # action_name 存储表单提交按钮的唯一名称。
        action_name = str(event.get("action_name", ""))
        # operator_id 存储点击按钮的飞书用户 open_id。
        operator_id = str(event.get("operator_id", ""))
        # token 存储飞书延迟更新卡片所需的一次性 token。
        token = str(event.get("token", ""))
        if action_name.startswith("chat_send_") and event.get("form_value"):
            # task_id 存储当前输入表单永久绑定的任务 ID。
            task_id = action_name.removeprefix("chat_send_")
            self._handle_card_chat_submit(event, task_id, operator_id)
            return
        if action_name.startswith("rename_") and event.get("form_value"):
            # task_id 存储重命名表单名称中编码的任务 ID。
            task_id = action_name.removeprefix("rename_")
            try:
                # form_value 存储重命名表单提交的字段对象。
                form_value = json.loads(str(event.get("form_value")))
            except json.JSONDecodeError:
                form_value = {}
            # title 存储用户输入的新任务名称。
            title = (
                form_value.get(f"title_{task_id}", "")
                if isinstance(form_value, dict)
                else ""
            )
            self.task_manager.rename_task(task_id, str(title))
            # card 存储重命名后的最新任务列表卡片。
            card = build_task_list_card(
                self.task_manager.tasks.values(),
                self.task_manager.current_task_id_for_sender(operator_id),
            )
            self._update_callback_card(token, card)
            return
        # raw_value 存储按钮或更多菜单选项配置的原始业务参数。
        raw_value = (
            event.get("option")
            if event.get("action_tag") == "overflow"
            else event.get("action_value")
        )
        try:
            # action_value 存储解析后的按钮业务参数。
            action_value = (
                json.loads(raw_value) if isinstance(raw_value, str) else raw_value
            )
        except json.JSONDecodeError:
            action_value = None
        if not isinstance(action_value, dict):
            return
        # action 存储用户点击的业务动作名。
        action = str(action_value.get("action", ""))
        # task_id 存储按钮关联的 Claude 任务 ID。
        task_id = str(action_value.get("task_id", ""))
        # source_message_id 存储最近用户问题消息 ID，重试时会重新读取编辑后的正文。
        source_message_id = self.task_source_messages.get(task_id) or str(
            action_value.get("source_message_id", "")
        )

        if action == "card_chat_submit":
            self._handle_card_chat_submit(event, task_id, operator_id)
            return
        if action in {"history_older", "history_latest"}:
            self._show_history_page(task_id, older=action == "history_older")
            return
        if action == "show_tasks":
            # task_message 存储用于把任务列表回复到当前卡片下方的内部消息。
            task_message = LarkMessage(
                event_id=f"task-list-{uuid.uuid4()}",
                message_id=str(event.get("message_id", "")),
                sender_id=operator_id,
                chat_id=str(event.get("chat_id", "")),
                text="/tasks",
                chat_type="p2p",
            )
            self._send_task_list_card(task_message)
            return
        if action == "new_task":
            self._create_task_card(operator_id, str(event.get("message_id", "")))
            return

        if action == "stop":
            # result 存储停止任务后的用户提示。
            result = self.task_manager.stop_task(task_id)
            self._update_action_result_card(token, task_id, source_message_id, result)
            return
        if action in {"task_use", "task_delete", "task_rename"}:
            if action == "task_use":
                self.task_manager.use_task(operator_id, task_id)
                self._open_existing_task_card(task_id, str(event.get("message_id", "")))
                return
            elif action == "task_delete":
                self.task_manager.close_task(operator_id, task_id)
            else:
                # task 存储要按最近问题自动命名的任务。
                task = self.task_manager.tasks.get(task_id)
                # generated_title 存储从最近问题生成的紧凑任务标题。
                generated_title = (
                    preview_text(task.last_question, limit=24)
                    if task and task.last_question
                    else f"任务 {task_id}"
                )
                self.task_manager.rename_task(task_id, generated_title)
            # card 存储操作后的最新任务列表卡片。
            card = build_task_list_card(
                self.task_manager.tasks.values(),
                self.task_manager.current_task_id_for_sender(operator_id),
            )
            self._update_callback_card(token, card)
            return
        if action in {"open_task", "open_logs", "open_files"}:
            self._open_local_shortcut(action, task_id)
            self._update_action_result_card(
                token, task_id, source_message_id, "已在本机打开。"
            )
            return
        if action in {"retry", "continue", "explain", "document"}:
            self._run_card_followup(action, task_id, operator_id, source_message_id)

    def _handle_card_chat_submit(
        self, event: dict, task_id: str, operator_id: str
    ) -> bool:
        """处理卡片对话表单；event 提供表单值，task_id 固定路由，operator_id 标识用户。"""
        try:
            # form_value 存储卡片表单提交的全部字段值。
            form_value = json.loads(str(event.get("form_value", "")))
        except json.JSONDecodeError:
            form_value = {}
        # form_question 存储点击发送按钮时由表单回传的输入内容。
        form_question = (
            form_value.get(f"chat_input_{task_id}", "")
            if isinstance(form_value, dict)
            else ""
        )
        # question 存储按钮表单值或按 Enter 时 input 回调的输入内容。
        question = form_question or event.get("input_value", "")
        if task_id not in self.task_manager.tasks or not str(question).strip():
            self._log(f"卡片对话提交缺少有效内容 task_id={task_id}")
            return False
        # normalized_question 存储去除首尾空白后的最终问题。
        normalized_question = str(question).strip()
        # now 存储本次卡片提交的单调时钟时间。
        now = time.monotonic()
        # recent_submission 存储同任务最近一次提交，用于识别客户端双回调。
        recent_submission = self.recent_card_submissions.get(task_id)
        if (
            recent_submission is not None
            and recent_submission[0] == normalized_question
            and now - recent_submission[1] <= CARD_SUBMIT_DEDUP_SECONDS
        ):
            # Enter 后紧接按钮回调属于同一次用户操作，忽略可避免 Claude 收到重复问题。
            self._log(f"忽略重复卡片提交 task_id={task_id}")
            return True
        self.recent_card_submissions[task_id] = (normalized_question, now)
        self.task_history_pages[task_id] = 0
        self.task_manager.sender_current_tasks[operator_id] = task_id
        # synthetic_message 存储卡片表单转换出的内部消息，不会产生用户消息气泡。
        synthetic_message = LarkMessage(
            event_id=str(event.get("event_id", f"card-chat-{uuid.uuid4()}")),
            message_id=str(event.get("message_id", "")),
            sender_id=operator_id,
            chat_id=str(event.get("chat_id", "")),
            text=normalized_question,
            chat_type="p2p",
        )
        return self._handle_event_streaming(
            synthetic_message,
            task_id=task_id,
            track_source_message=False,
            clear_input=True,
        )

    def _show_history_page(self, task_id: str, older: bool) -> bool:
        """在同一任务卡内切换历史页；task_id 指定任务，older 为真时向更早一页移动。"""
        # task 存储需要查看历史的 Claude 任务。
        task = self.task_manager.tasks.get(task_id)
        # active_card 存储当前任务活动卡片及下一更新序号。
        active_card = self.task_cards.get(task_id)
        if task is None or active_card is None:
            return False
        # total_pages 存储该任务完整历史可分成的页数。
        total_pages = max(
            1,
            (len(task.conversation_history) + CARD_HISTORY_PAGE_TURNS - 1)
            // CARD_HISTORY_PAGE_TURNS,
        )
        # current_page 存储切换前的倒序页码。
        current_page = self.task_history_pages.get(task_id, 0)
        # target_page 存储边界约束后的目标页码。
        target_page = min(total_pages - 1, current_page + 1) if older else 0
        # card_id、card_message_id 和 sequence 分别存储卡片实体、消息和本次更新序号。
        card_id, card_message_id, sequence = active_card
        # history_content 存储目标页的连续问答正文。
        history_content = conversation_card_content(
            task.conversation_history, page=target_page
        )
        # started_at 存储即时渲染元数据所需的基准时刻，使历史翻页耗时显示为零。
        started_at = time.monotonic()
        # card_content 存储带任务状态元数据的历史页正文。
        card_content = render_task_progress(task, history_content, started_at)
        if not self._stream_card_content(
            card_id, card_content, sequence, element_id=STREAM_CARD_SUMMARY_ID
        ):
            return False
        self.task_history_pages[task_id] = target_page
        self.task_cards[task_id] = (card_id, card_message_id, sequence + 1)
        self._save_task_cards()
        return True

    def _update_action_result_card(
        self,
        token: str,
        task_id: str,
        source_message_id: str,
        result: str,
    ) -> None:
        """把同步按钮动作结果更新回原卡片。"""
        # task 存储按钮关联的任务；任务已删除时使用占位标题。
        task = self.task_manager.tasks.get(task_id)
        # title 存储回调结果卡片标题。
        title = (
            f"{task_id} · {task.title}"
            if task is not None
            else task_id or "Claude 任务"
        )
        # card 存储动作完成后的结果卡片。
        card = build_answer_card_json(
            task_id, source_message_id, result, title, "操作完成"
        )
        self._update_callback_card(token, card)

    def _run_card_followup(
        self,
        action: str,
        task_id: str,
        operator_id: str,
        source_message_id: str,
    ) -> None:
        """把重试、继续、解释或生成文档按钮转换为新的 Claude 任务轮次。"""
        if task_id not in self.task_manager.tasks:
            return
        self.task_manager.sender_current_tasks[operator_id] = task_id
        # task 存储按钮关联的 Claude 任务。
        task = self.task_manager.tasks[task_id]
        # prompts 存储无需读取源消息的按钮后续指令。
        prompts = {
            "continue": "请继续完成刚才的任务，从尚未完成的地方接着做。",
            "explain": f"请用更容易理解的方式解释你刚才的回答：\n\n{task.last_answer}",
            "document": "请把当前任务的结论整理为结构清晰的 Markdown 文档，保存到当前任务工作目录的 output 目录，并在回答中给出文件路径。",
        }
        if action == "retry":
            # detail 存储源消息当前最新内容，支持用户编辑后重新生成。
            detail = self._get_message_detail(source_message_id)
            # question 存储编辑后的源消息正文或上次问题兜底。
            question = (
                detail.get("content")
                if isinstance(detail, dict)
                else task.last_question
            )
            if not isinstance(question, str) or not question.strip():
                question = task.last_question
        else:
            question = prompts[action]
        # synthetic_message 存储按钮触发的内部消息，用同一任务卡片继续展示进度。
        synthetic_message = LarkMessage(
            event_id=f"card-{uuid.uuid4()}",
            message_id=source_message_id,
            sender_id=operator_id,
            chat_id="",
            text=question,
            chat_type="p2p",
        )
        self._handle_event_streaming(
            synthetic_message,
            task_id=task_id,
            track_source_message=False,
        )

    def _open_local_shortcut(self, action: str, task_id: str) -> None:
        """在当前 Mac 打开任务目录、日志目录或生成文件目录。"""
        # task 存储快捷入口关联的任务。
        task = self.task_manager.tasks.get(task_id)
        if task is None:
            return
        # target_paths 存储不同快捷入口对应的本地路径。
        target_paths = {
            "open_task": task.workspace,
            "open_logs": self.log_dir / task_id,
            "open_files": task.workspace / "output",
        }
        # target 存储本次需要在 Finder 中打开的路径。
        target = target_paths[action]
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(target)], check=False)

    def _create_task_card(self, operator_id: str, reply_message_id: str) -> bool:
        """创建独立任务并回复一张空闲流式卡片；operator_id 是用户，reply_message_id 是原卡消息。"""
        # task_title 存储新任务的默认名称。
        task_title = f"任务 {self.task_manager.next_task_number}"
        self.task_manager.create_task(operator_id, task_title)
        # task_id 存储刚创建并切换到的任务 ID。
        task_id = self.task_manager.current_task_id_for_sender(operator_id) or ""
        if not task_id or not reply_message_id:
            return False
        # idle_content 存储新任务卡片尚未收到问题时的提示。
        idle_content = (
            "**新任务已就绪**\n\n在下方输入问题，这张卡片会始终使用自己的独立上下文。"
        )
        # card_id 存储新建的独立流式卡片实体 ID。
        card_id = self._create_stream_card(task_id, "", initial_content=idle_content)
        if card_id is None:
            return False
        # card_message_id 存储发送到飞书后的新卡片消息 ID。
        card_message_id = self._send_stream_card(reply_message_id, card_id)
        if card_message_id is None:
            return False
        # 空闲卡保持流式模式，第一次表单提问即可直接更新该 CardKit 实体。
        self.task_cards[task_id] = (card_id, card_message_id, 1)
        self._save_task_cards()
        return True

    def _open_existing_task_card(self, task_id: str, reply_message_id: str) -> bool:
        """为已有任务回复一张新的活动卡片；task_id 指定任务，reply_message_id 指定任务列表消息。"""
        # task 存储需要重新打开的已有 Claude 任务。
        task = self.task_manager.tasks.get(task_id)
        if task is None or not reply_message_id:
            return False
        # latest_content 存储卡片首次显示的完整可见历史或空任务提示。
        latest_content = conversation_card_content(task.conversation_history)
        # initial_content 存储包含任务身份的卡片初始正文。
        initial_content = f"**{task.task_id} · {task.title}**\n\n{format_lark_markdown(latest_content)}"
        # card_id 存储为已有任务创建的新 CardKit 实体 ID。
        card_id = self._create_stream_card(task_id, "", initial_content=initial_content)
        if card_id is None:
            return False
        # card_message_id 存储新活动任务卡片对应的飞书消息 ID。
        card_message_id = self._send_stream_card(reply_message_id, card_id)
        if card_message_id is None:
            return False
        # 最新打开的卡片成为该任务后续流式更新目标，并保持 streaming_mode。
        self.task_cards[task_id] = (card_id, card_message_id, 1)
        self._save_task_cards()
        return True
