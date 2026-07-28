"""task manager 模块。"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


from .claude_sessions import ClaudeStreamSession
from .messages import build_help_text
from .messages import parse_bot_command
from .messages import preview_text
from .models import BotCommand
from .models import ClaudeTask


class ClaudeTaskManager:
    """管理同一飞书桥接中的多个独立 Claude 任务会话。"""

    def __init__(
        self,
        workspace_root: Path,
        log_dir: Path,
        system_prompt: str,
        timeout: int,
        session_factory=None,
    ):
        """初始化任务管理器，session_factory 用于创建独立 Claude 会话。"""
        # workspace_root 存储所有任务工作目录的根目录。
        self.workspace_root = workspace_root
        # log_dir 存储所有任务共享的日志根目录。
        self.log_dir = log_dir
        # system_prompt 存储传给每个 Claude 会话的系统提示。
        self.system_prompt = system_prompt
        # timeout 存储每个 Claude 会话单轮等待最终回答前的软提示秒数。
        self.timeout = timeout
        # session_factory 存储创建 Claude 会话对象的工厂。
        self.session_factory = session_factory or ClaudeStreamSession
        # tasks 存储任务 ID 到任务状态的映射。
        self.tasks: dict[str, ClaudeTask] = {}
        # sender_current_tasks 存储每个飞书发送者当前选中的任务 ID。
        self.sender_current_tasks: dict[str, str] = {}
        # next_task_number 存储下一个任务编号。
        self.next_task_number = 1
        # state_path 是任务元数据持久化文件路径，关机重启后据此恢复任务列表和会话 ID。
        self.state_path = log_dir / "tasks-state.json"
        # state_lock 串行化 state 文件读写，避免多线程并发落盘写坏 JSON。
        self.state_lock = threading.Lock()
        # 启动时先尝试从磁盘恢复上次的任务状态，让关机前的任务不丢失。
        self._load_state()

    def _load_state(self) -> None:
        """从 state 文件恢复上次运行的任务元数据；文件不存在或损坏时保持空状态。"""
        if not self.state_path.exists():
            return

        try:
            # raw 存储 state 文件反序列化后的原始 JSON 对象。
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # state 文件读不出或格式坏掉时，宁可从空状态起步，也不让服务启动失败。
            return

        if not isinstance(raw, dict):
            return

        # tasks_data 存储持久化的任务列表，缺失时视为无历史任务。
        tasks_data = raw.get("tasks")
        if isinstance(tasks_data, list):
            for item in tasks_data:
                if not isinstance(item, dict):
                    continue
                # task_id 是持久化任务的短 ID，缺失则跳过这条无效记录。
                task_id = item.get("task_id")
                if not isinstance(task_id, str) or not task_id:
                    continue
                # task 存储从磁盘还原出的任务状态，session 保持 None 等待懒启动恢复。
                # conversation_history 存储已持久化历史；旧状态没有该字段时迁移最近一轮。
                conversation_history = item.get("conversation_history", [])
                if not isinstance(conversation_history, list):
                    conversation_history = []
                if (
                    not conversation_history
                    and item.get("last_question")
                    and item.get("last_answer")
                ):
                    conversation_history = [
                        {
                            "question": item.get("last_question", ""),
                            "answer": item.get("last_answer", ""),
                        }
                    ]
                task = ClaudeTask(
                    task_id=task_id,
                    title=item.get("title", task_id),
                    workspace=self.workspace_root / task_id,
                    session_id=item.get("session_id"),
                    # 恢复后会话尚未拉起，统一标记为“待恢复”提示用户下条消息会续接上下文。
                    status="待恢复" if item.get("session_id") else "未启动",
                    turns=item.get("turns", 0),
                    last_question=item.get("last_question", ""),
                    last_answer=item.get("last_answer", ""),
                    conversation_history=conversation_history,
                    last_error=item.get("last_error", ""),
                    created_at=item.get("created_at", ""),
                    updated_at=item.get("updated_at", ""),
                    lock=threading.RLock(),
                )
                self.tasks[task_id] = task

        # senders 存储持久化的“发送者->当前任务”映射，用来恢复每个人上次选中的任务。
        senders = raw.get("sender_current_tasks")
        if isinstance(senders, dict):
            for sender_id, current_id in senders.items():
                # 只恢复仍然存在的任务，避免指向已被清理的任务 ID。
                if isinstance(current_id, str) and current_id in self.tasks:
                    self.sender_current_tasks[sender_id] = current_id

        # next_number 存储持久化的下一个任务编号，缺省时按已有任务推算避免 ID 冲突。
        next_number = raw.get("next_task_number")
        if isinstance(next_number, int) and next_number >= 1:
            self.next_task_number = next_number
        elif self.tasks:
            # 兜底：用已有任务里最大的编号 +1，防止新任务 ID 撞上已恢复的任务。
            self.next_task_number = max(int(tid[1:]) for tid in self.tasks) + 1

    def _save_state(self) -> None:
        """把当前任务元数据原子写入 state 文件，供下次启动恢复。"""
        # payload 是要落盘的任务元数据快照；session 对象和 lock 不可序列化，只存可恢复字段。
        payload = {
            "next_task_number": self.next_task_number,
            "sender_current_tasks": self.sender_current_tasks,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "session_id": task.session_id,
                    "status": task.status,
                    "turns": task.turns,
                    "last_question": task.last_question,
                    "last_answer": task.last_answer,
                    "conversation_history": task.conversation_history,
                    "last_error": task.last_error,
                    "created_at": task.created_at,
                    "updated_at": task.updated_at,
                }
                for task in self.tasks.values()
            ],
        }
        with self.state_lock:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            # tmp_path 是同目录临时文件，先写它再 rename，保证读到的 state 永远是完整 JSON。
            tmp_path = self.state_path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp_path.replace(self.state_path)

    def stop_all(self) -> None:
        """停止所有已启动的 Claude 任务会话。"""
        for task in self.tasks.values():
            if task.session is None:
                continue
            try:
                task.session.stop()
            except Exception:
                pass

    def current_task_id_for_sender(self, sender_id: str) -> Optional[str]:
        """返回指定发送者当前选中的任务 ID。"""
        return self.sender_current_tasks.get(sender_id)

    def ensure_current_task(self, sender_id: str) -> ClaudeTask:
        """返回发送者当前任务；没有可用任务时自动创建默认任务。"""
        # task_id 存储发送者当前选中的任务 ID。
        task_id = self.sender_current_tasks.get(sender_id)
        if task_id not in self.tasks:
            self.create_task(sender_id, "默认任务")
            task_id = self.sender_current_tasks[sender_id]
        return self.tasks[task_id]

    def stop_task(self, task_id: str) -> str:
        """终止指定任务当前正在执行的 Claude 请求，但保留任务和历史上下文。"""
        # normalized_id 存储规范化后的目标任务 ID。
        normalized_id = task_id.strip().lower()
        if normalized_id not in self.tasks:
            return f"找不到任务：{task_id or '(空)'}"
        # task 存储需要停止的任务对象。
        task = self.tasks[normalized_id]
        if task.session is None or task.status != "思考中":
            return f"任务 {normalized_id} 当前没有正在生成的内容。"
        task.session.stop()
        task.status = "已停止"
        task.updated_at = datetime.now().isoformat(timespec="seconds")
        self._save_state()
        return f"已停止任务 {normalized_id}。"

    def rename_task(self, task_id: str, title: str) -> str:
        """修改指定任务标题；task_id 是任务 ID，title 是新标题。"""
        # normalized_id 存储规范化后的目标任务 ID。
        normalized_id = task_id.strip().lower()
        # normalized_title 存储去除首尾空白后的新标题。
        normalized_title = title.strip()
        if normalized_id not in self.tasks:
            return f"找不到任务：{task_id or '(空)'}"
        if not normalized_title:
            return "新任务名称不能为空。"
        self.tasks[normalized_id].title = normalized_title
        self.tasks[normalized_id].updated_at = datetime.now().isoformat(
            timespec="seconds"
        )
        self._save_state()
        return f"已将任务 {normalized_id} 重命名为：{normalized_title}"

    def handle_text(
        self,
        sender_id: str,
        text: str,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        """处理用户发来的文本：命令走本地控制，普通消息进入当前 Claude 任务。

        on_delta 是可选的流式增量回调，只对进入 Claude 的普通消息和 /ask 生效，
        本地控制命令返回即时文本，不需要流式。
        """
        # command 存储解析出的斜杠命令。
        command = parse_bot_command(text)
        if command is not None:
            return self._handle_command(sender_id, command, on_delta=on_delta)
        return self.ask_current(sender_id, text, on_delta=on_delta)

    def _handle_command(
        self,
        sender_id: str,
        command: BotCommand,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        """执行飞书聊天里的控制命令。"""
        if command.name in {"help", "h", "？", "?"}:
            return build_help_text()
        if command.name == "new":
            return self.create_task(
                sender_id, command.args or f"任务 {self.next_task_number}"
            )
        if command.name in {"tasks", "list", "ls"}:
            return self.list_tasks(sender_id)
        if command.name in {"use", "switch"}:
            return self.use_task(sender_id, command.args)
        if command.name == "status":
            return self.status(sender_id, command.args)
        if command.name == "ask":
            return self.ask_named(sender_id, command.args, on_delta=on_delta)
        if command.name == "close":
            return self.close_task(sender_id, command.args)
        if command.name in {"stop", "cancel"}:
            # task_id 存储用户显式指定或当前选中的待停止任务 ID。
            task_id = command.args or self.sender_current_tasks.get(sender_id, "")
            return self.stop_task(task_id)
        if command.name == "rename":
            # parts 存储任务 ID 和新标题。
            parts = command.args.split(maxsplit=1)
            if len(parts) < 2:
                return "用法：/rename <任务ID> <新名称>"
            return self.rename_task(parts[0], parts[1])
        return f"未知命令：/{command.name}\n\n{build_help_text()}"

    def create_task(self, sender_id: str, title: str) -> str:
        """创建一个新任务并切换为发送者当前任务。"""
        # task_id 存储新任务的短 ID。
        task_id = f"t{self.next_task_number}"
        self.next_task_number += 1
        # now 存储任务创建和更新时间。
        now = datetime.now().isoformat(timespec="seconds")
        # workspace 存储该任务独立工作目录。
        workspace = self.workspace_root / task_id
        # task 存储新建任务状态。
        task = ClaudeTask(
            task_id=task_id,
            title=title.strip() or task_id,
            workspace=workspace,
            created_at=now,
            updated_at=now,
            lock=threading.RLock(),
        )
        self.tasks[task_id] = task
        self.sender_current_tasks[sender_id] = task_id
        # 新建任务后立即落盘，确保关机重启后任务列表和编号不丢。
        self._save_state()
        return f"已创建并切换到任务 {task_id}：{task.title}\n直接继续发消息即可进入这个任务。"

    def list_tasks(self, sender_id: str) -> str:
        """返回当前所有任务的进度列表。"""
        if not self.tasks:
            return "当前还没有任务。发送消息会自动创建 t1，也可以用 /new <任务名>。"

        # current_id 存储当前发送者选中的任务 ID。
        current_id = self.sender_current_tasks.get(sender_id)
        # lines 存储任务列表的每一行。
        lines = ["任务列表："]
        for task_id in sorted(self.tasks, key=lambda value: int(value[1:])):
            # task 存储当前遍历的任务状态。
            task = self.tasks[task_id]
            # marker 标记当前选中的任务。
            marker = "*" if task_id == current_id else " "
            # last_question 存储最近问题预览。
            last_question = (
                preview_text(task.last_question) if task.last_question else "暂无问题"
            )
            lines.append(
                f"{marker} {task.task_id} {task.title} | {task.status} | 轮次 {task.turns} | {last_question}"
            )
        return "\n".join(lines)

    def use_task(self, sender_id: str, task_id: str) -> str:
        """切换指定发送者的当前任务。"""
        # normalized_id 存储规范化后的任务 ID。
        normalized_id = task_id.strip().lower()
        if normalized_id not in self.tasks:
            return f"找不到任务：{task_id or '(空)'}\n用 /tasks 查看可用任务。"
        self.sender_current_tasks[sender_id] = normalized_id
        # task 存储被切换到的任务状态。
        task = self.tasks[normalized_id]
        # 切换当前任务后落盘，确保重启后仍指向同一任务。
        self._save_state()
        return f"已切换到任务 {task.task_id}：{task.title}"

    def status(self, sender_id: str, task_id: str = "") -> str:
        """返回当前任务或指定任务的详细状态。"""
        # target_id 存储要查询的任务 ID。
        target_id = task_id.strip().lower() or self.sender_current_tasks.get(sender_id)
        if not target_id:
            return "当前还没有选中的任务。用 /new <任务名> 创建一个。"
        if target_id not in self.tasks:
            return f"找不到任务：{target_id}\n用 /tasks 查看可用任务。"

        # task 存储要展示状态的任务。
        task = self.tasks[target_id]
        # last_question 存储最近问题展示文本。
        last_question = task.last_question or "暂无"
        # last_answer 存储最近回答展示文本。
        last_answer = (
            preview_text(task.last_answer, limit=80) if task.last_answer else "暂无"
        )
        # last_error 存储最近错误展示文本。
        last_error = f"\n最近错误：{task.last_error}" if task.last_error else ""
        return (
            f"任务 {task.task_id}：{task.title}\n"
            f"状态：{task.status}\n"
            f"轮次：{task.turns}\n"
            f"最近问题：{last_question}\n"
            f"最近回答：{last_answer}"
            f"{last_error}"
        )

    def close_task(self, sender_id: str, task_id: str) -> str:
        """关闭指定任务并停止它的 Claude 会话。"""
        # normalized_id 存储规范化后的任务 ID。
        normalized_id = task_id.strip().lower()
        if not normalized_id:
            normalized_id = self.sender_current_tasks.get(sender_id, "")
        if normalized_id not in self.tasks:
            return f"找不到任务：{normalized_id or '(空)'}\n用 /tasks 查看可用任务。"

        # task 存储要关闭的任务。
        task = self.tasks.pop(normalized_id)
        if task.session is not None:
            task.session.stop()
        for sender, current_id in list(self.sender_current_tasks.items()):
            if current_id == normalized_id:
                self.sender_current_tasks.pop(sender, None)
        # 关闭任务会改变任务集合和当前选中关系，需要立即落盘。
        self._save_state()
        return f"已关闭任务 {task.task_id}：{task.title}"

    def ask_named(
        self,
        sender_id: str,
        args: str,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        """把问题发送给指定任务，参数格式为 '<任务ID> <问题>'。on_delta 为可选流式增量回调。"""
        # parts 存储任务 ID 和问题文本。
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            return "用法：/ask <任务ID> <问题>"
        # task_id 存储目标任务 ID。
        task_id = parts[0].strip().lower()
        # question 存储要发送给 Claude 的问题。
        question = parts[1].strip()
        if task_id not in self.tasks:
            return f"找不到任务：{task_id}\n用 /tasks 查看可用任务。"
        self.sender_current_tasks[sender_id] = task_id
        return self.ask_task(task_id, question, on_delta=on_delta)

    def ask_current(
        self,
        sender_id: str,
        question: str,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        """把普通消息发送给发送者当前任务；没有任务时自动创建默认任务。on_delta 为可选流式增量回调。"""
        # task_id 存储当前发送者选中的任务 ID。
        task_id = self.sender_current_tasks.get(sender_id)
        if task_id not in self.tasks:
            self.create_task(sender_id, "默认任务")
            task_id = self.sender_current_tasks[sender_id]
        return self.ask_task(task_id, question, on_delta=on_delta)

    def ask_task(
        self,
        task_id: str,
        question: str,
        on_delta: Optional[Callable[[str], None]] = None,
    ) -> str:
        """把问题发送到指定 Claude 任务会话并更新任务状态。"""
        # task 存储目标任务状态。
        task = self.tasks[task_id]
        if task.lock is None:
            task.lock = threading.RLock()

        with task.lock:
            if task.session is None:
                # resume 表示该任务已有历史 session_id，重启后应恢复对话上下文而非新建会话。
                resume = bool(task.session_id)
                # session 存储该任务独立 Claude 会话对象，按需启动以减少空任务资源占用。
                session = self.session_factory(
                    workspace=task.workspace,
                    log_dir=self.log_dir / task.task_id,
                    system_prompt=self.system_prompt,
                    timeout=self.timeout,
                    session_id=task.session_id or None,
                    resume=resume,
                )
                session.start()
                task.session = session
                # 回填会话 ID，确保新建会话的 session_id 被持久化，供关机重启后 --resume 续接。
                task.session_id = getattr(session, "session_id", "") or task.session_id
                self._save_state()

            # now 存储任务状态更新时间。
            now = datetime.now().isoformat(timespec="seconds")
            task.status = "思考中"
            task.last_question = question
            task.updated_at = now
            try:
                # answer 存储 Claude 返回的回答文本。
                # 优先带流式回调调用；老式 session（如测试桩）只接受单参数时回退为普通调用。
                if on_delta is not None:
                    try:
                        answer = task.session.ask(question, on_delta=on_delta)
                    except TypeError:
                        answer = task.session.ask(question)
                else:
                    answer = task.session.ask(question)
            except Exception as exc:
                if isinstance(exc, InterruptedError):
                    task.status = "已停止"
                    task.last_error = ""
                else:
                    task.status = "出错"
                    task.last_error = str(exc)
                task.updated_at = datetime.now().isoformat(timespec="seconds")
                # 出错状态也需落盘，方便重启后从 /tasks 看到失败线索。
                self._save_state()
                raise
            task.status = "空闲"
            task.turns += 1
            # 会话恢复失败时底层会生成新 ID，成功回答后必须同步到任务状态供下次重启使用。
            task.session_id = getattr(task.session, "session_id", "") or task.session_id
            task.last_answer = answer
            # completed_turn 存储本轮刚完成的用户问题和 Claude 回答。
            completed_turn = {"question": question, "answer": answer}
            task.conversation_history.append(completed_turn)
            task.last_error = ""
            task.updated_at = datetime.now().isoformat(timespec="seconds")
            # 一轮问答完成后落盘，保存最新轮次和问答内容。
            self._save_state()
            return answer
