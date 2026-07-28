"""BridgeEventMixin 拆分出的应用职责。"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from dataclasses import replace
from typing import Optional


from .cards import answer_card_input_form
from .claude_protocol import conversation_card_content
from .claude_protocol import friendly_error_message
from .claude_protocol import render_task_meta
from .config import DEFAULT_PROCESSING_TEXT
from .config import STREAM_CARD_META_ID
from .config import STREAM_CARD_SUMMARY_ID
from .config import STREAM_HEARTBEAT_INTERVAL
from .config import STREAM_MIN_INTERVAL
from .lark_commands import build_lark_message_get_args
from .lark_commands import build_lark_resource_download_args
from .lark_commands import ensure_lark_profile_exists
from .messages import ensure_workspace_instruction_files
from .messages import normalize_lark_event
from .messages import parse_bot_command
from .messages import should_show_processing_placeholder
from .messages import suggest_task_title
from .models import LarkMessage
import re


class BridgeEventMixin:
    def run(self) -> None:
        """启动桥接服务并持续处理飞书消息事件。"""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        ensure_workspace_instruction_files(self.task_manager.workspace_root)
        ensure_lark_profile_exists(self.args.lark_profile)
        self._log("启动飞书事件监听")
        self.consumer.start()
        if self.news_scheduler is not None:
            self.news_scheduler.start()
            self._log("AI 新闻调度已启动")
        self._log("消息与卡片按钮监听已就绪")
        self._log("桥接已就绪，等待飞书消息")

        try:
            for event in self.consumer.events():
                if event.get("type") == "card.action.trigger":
                    # worker_thread 存储当前卡片动作的后台处理线程，保证网关事件循环不被业务阻塞。
                    worker_thread = threading.Thread(
                        target=self._handle_card_action, args=(event,), daemon=True
                    )
                    with self.worker_threads_lock:
                        self.worker_threads.append(worker_thread)
                    worker_thread.start()
                    continue
                # worker_thread 存储本事件如需后台处理时创建的线程。
                worker_thread = self._dispatch_event(event)
                if self.args.once:
                    if worker_thread is not None:
                        worker_thread.join()
                    break
        finally:
            if self.news_scheduler is not None:
                self.news_scheduler.stop()
            self.consumer.stop()
            self.task_manager.stop_all()

    def _get_message_detail(self, message_id: str) -> Optional[dict]:
        """读取飞书消息的最新内容，支持引用关系和编辑后的正文。"""
        # completed 存储消息读取命令结果。
        completed = subprocess.run(
            build_lark_message_get_args(
                message_id,
                identity=self.args.reply_identity,
                profile=self.args.lark_profile,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self._log(
                f"读取消息失败 message_id={message_id}: {completed.stderr.strip()}"
            )
            return None
        try:
            # payload 存储消息读取响应对象。
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None
        # data 存储响应中的业务数据。
        data = payload.get("data") if isinstance(payload, dict) else None
        # messages 存储批量消息读取结果列表。
        messages = data.get("messages") if isinstance(data, dict) else None
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            return messages[0]
        return None

    def _download_message_resources(
        self, message: LarkMessage, content: str
    ) -> tuple[str, ...]:
        """下载图片、文件、语音和视频资源，返回可交给 Claude 的本机绝对路径。"""
        # resource_keys 存储消息正文中提取到的飞书资源键并保持原顺序去重。
        resource_keys = list(
            dict.fromkeys(re.findall(r"(?:img|file)_[A-Za-z0-9_-]+", content))
        )
        # downloaded_paths 存储成功下载的资源绝对路径。
        downloaded_paths: list[str] = []
        # runtime_root 存储附件安全落盘的运行根目录。
        runtime_root = self.log_dir.parent
        for file_key in resource_keys:
            # resource_type 存储飞书下载接口要求的 image 或 file 类型。
            resource_type = "image" if file_key.startswith("img_") else "file"
            # relative_output 存储符合 lark-cli 安全限制的相对输出路径。
            relative_output = f"attachments/{message.message_id}/{file_key}"
            (runtime_root / "attachments" / message.message_id).mkdir(
                parents=True, exist_ok=True
            )
            # completed 存储单个附件下载命令结果。
            completed = subprocess.run(
                build_lark_resource_download_args(
                    message.message_id,
                    file_key,
                    resource_type,
                    relative_output,
                    identity=self.args.reply_identity,
                    profile=self.args.lark_profile,
                ),
                cwd=runtime_root,
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                self._log(f"附件下载失败 {file_key}: {completed.stderr.strip()}")
                continue
            # matches 存储下载命令可能自动补扩展名后的实际文件路径。
            matches = sorted(
                (runtime_root / "attachments" / message.message_id).glob(f"{file_key}*")
            )
            if matches:
                downloaded_paths.append(str(matches[-1].resolve()))
        return tuple(downloaded_paths)

    def _enrich_message(self, message: LarkMessage) -> LarkMessage:
        """补充消息最新正文、引用内容和媒体附件路径。"""
        if self.args.dry_run:
            return message
        # detail 存储飞书当前最新的消息详情。
        detail = self._get_message_detail(message.message_id)
        if detail is None:
            return message
        # latest_content 存储用户编辑后的最新消息正文。
        latest_content = detail.get("content")
        if not isinstance(latest_content, str) or not latest_content.strip():
            latest_content = message.text
        # reply_to 存储被当前消息引用回复的消息 ID。
        reply_to = detail.get("reply_to")
        # quoted_text 存储引用消息的人类可读正文。
        quoted_text = ""
        if isinstance(reply_to, str) and reply_to:
            # quoted_detail 存储引用目标消息详情。
            quoted_detail = self._get_message_detail(reply_to)
            if isinstance(quoted_detail, dict) and isinstance(
                quoted_detail.get("content"), str
            ):
                quoted_text = quoted_detail["content"].strip()
        # attachment_paths 存储当前消息下载成功的媒体附件。
        attachment_paths = self._download_message_resources(message, latest_content)
        # prompt_text 存储最终交给 Claude 的文本、引用和附件说明。
        prompt_text = latest_content.strip()
        if quoted_text:
            prompt_text += f"\n\n[用户引用的消息]\n{quoted_text}"
        if attachment_paths:
            prompt_text += "\n\n[飞书附件，已下载到本机]\n" + "\n".join(
                attachment_paths
            )
        return replace(
            message,
            text=prompt_text,
            attachment_paths=attachment_paths,
            quoted_text=quoted_text,
        )

    def _dispatch_event(self, event: dict) -> Optional[threading.Thread]:
        """按消息类型分发事件：长耗时 Claude 问答后台执行，控制命令同步执行。"""
        self._prune_worker_threads()
        # message 是用于判断处理策略的标准化飞书消息；None 走普通处理路径。
        message = normalize_lark_event(event)
        if message is None or not should_show_processing_placeholder(message.text):
            self._handle_event(event)
            return None

        # worker_thread 是负责处理本条长耗时消息的后台线程。
        worker_thread = threading.Thread(
            target=self._handle_event,
            args=(event,),
            daemon=True,
        )
        with self.worker_threads_lock:
            self.worker_threads.append(worker_thread)
        worker_thread.start()
        return worker_thread

    def _prune_worker_threads(self) -> None:
        """清理已结束的后台处理线程，避免长时间运行时列表无限增长。"""
        with self.worker_threads_lock:
            # active_threads 存储仍在处理 Claude 长任务的后台线程。
            active_threads = [
                worker_thread
                for worker_thread in self.worker_threads
                if worker_thread.is_alive()
            ]
            self.worker_threads = active_threads

    def _handle_event(self, event: dict) -> None:
        """处理单条飞书事件：去重、询问 Claude、回复原消息。"""
        self._log(f"收到原始飞书事件：{json.dumps(event, ensure_ascii=False)}")
        # message 是标准化后的飞书文本消息；None 表示无需处理。
        message = normalize_lark_event(event)
        if message is None:
            return

        # enrich_message 补充编辑后的正文、引用消息和本地附件路径。
        message = self._enrich_message(message)

        if message.event_id in self.processed_event_ids:
            return
        self.processed_event_ids.add(message.event_id)

        self._log(
            f"收到消息 {message.message_id} from={message.sender_id}: {message.text}"
        )
        # /tasks 使用交互式任务列表卡片，不再返回纯文本列表。
        command = parse_bot_command(message.text)
        if (
            command is not None
            and command.name in {"tasks", "list", "ls"}
            and not self.args.dry_run
        ):
            self._send_task_list_card(message)
            return
        if command is None:
            # task_title 存储本条普通飞书消息自动创建的新任务标题。
            task_title = suggest_task_title(
                message.text, self.task_manager.next_task_number
            )
            self.task_manager.create_task(message.sender_id, task_title)
        # should_show_placeholder 标记本轮是否会进入耗时 Claude 问答。
        should_show_placeholder = should_show_processing_placeholder(message.text)

        # 长耗时问答优先走流式卡片，让飞书端逐字冒出回答；dry-run（测试）或建卡/发卡失败时回退文本路径。
        if should_show_placeholder and not self.args.dry_run:
            if self._handle_event_streaming(message):
                return

        # processing_message_id 存储已发出的“AI思考中”占位回复消息 ID。
        processing_message_id: Optional[str] = None
        if should_show_placeholder:
            processing_message_id = self._send_reply(
                message.message_id, DEFAULT_PROCESSING_TEXT
            )

        try:
            # answer 是命令处理结果或 Claude 对当前飞书消息生成的回复文本。
            answer = self.task_manager.handle_text(message.sender_id, message.text)
        except Exception as exc:
            answer = friendly_error_message(exc)
            self._log(f"Claude 处理失败：{exc}")

        if processing_message_id:
            # 占位消息已发送时优先编辑同一条消息，降低飞书里刷屏感。
            if self._update_message(processing_message_id, answer):
                return
            self._log(f"占位消息 {processing_message_id} 更新失败，改为补发最终回复")

        self._reply(message.message_id, answer)

    def _handle_event_streaming(
        self,
        message: LarkMessage,
        task_id: str = "",
        track_source_message: bool = True,
        clear_input: bool = False,
    ) -> bool:
        """用流式卡片处理一条长耗时消息：建卡→发卡→逐字追加→收尾定稿。

        返回 True 表示流式卡片路径已完整处理本条消息（含把最终答案定稿到卡片），
        调用方无需再走文本回退；task_id 可强制绑定卡片任务，track_source_message 控制是否记录消息源，
        clear_input 表示首帧显示后清空独立输入组件。
        """
        # task 存储本条消息明确绑定或根据发送者选中的 Claude 任务。
        task = (
            self.task_manager.tasks.get(task_id)
            if task_id
            else self.task_manager.ensure_current_task(message.sender_id)
        )
        if task is None:
            return False
        self.task_history_pages[task.task_id] = 0
        if track_source_message:
            self.task_source_messages[task.task_id] = message.message_id
        # existing_card 存储同一任务上次创建的卡片，存在时直接复用以减少重复消息。
        existing_card = self.task_cards.get(task.task_id)
        if existing_card is None:
            # card_id 是本轮新建的流式卡片实体 ID。
            card_id = self._create_stream_card(task.task_id, message.message_id)
            if card_id is None:
                self._log("建卡失败，回退到文本占位路径")
                return False
            # card_message_id 是发送到飞书后的交互卡片消息 ID。
            card_message_id = self._send_stream_card(message.message_id, card_id)
            if card_message_id is None:
                self._log(f"发卡失败 card_id={card_id}，回退到文本占位路径")
                return False
            # sequence 存储新卡片第一次内容更新应使用的序号。
            sequence = 1
        else:
            card_id, card_message_id, sequence = existing_card

        # previous_history 存储进入本轮前的已完成对话，最终落盘后仍用此快照避免重复当前轮。
        previous_history = list(task.conversation_history)
        # sequence 是该活动卡片生命周期内持续递增的更新序号；卡片保持流式模式，无需重复开启。
        # last_push 记录上次成功更新的时间，用于节流。
        last_push = 0.0
        # latest_body 存储心跳刷新时需要保留的最新 Claude 可见内容。
        latest_body = DEFAULT_PROCESSING_TEXT
        # started_at 存储本轮任务开始的单调时钟时间。
        started_at = time.monotonic()
        # update_lock 串行化 token 回调与心跳线程的卡片更新。
        update_lock = threading.Lock()
        # heartbeat_stop 用于最终答案产生后停止心跳线程。
        heartbeat_stop = threading.Event()

        def push_progress(
            body: str,
            force: bool = False,
        ) -> None:
            """更新当前回答；元数据头与对话正文分别写入不同元素。

            正文元素 md_summary 始终按“历史 + 当前轮”累计，历史部分作为稳定前缀不会回退，
            飞书只对新增的当前轮尾部做逐字流式；易变的元数据头单独写入 md_meta，其每帧变化
            不再打断正文的公共前缀 diff，因此第二轮及以后不会把上一轮已完成内容重新流式重播。
            force 只跳过节流，不改变展示结构。
            """
            nonlocal sequence, last_push, latest_body
            with update_lock:
                latest_body = body
                # now 存储本次尝试更新卡片的时刻。
                now = time.monotonic()
                if not force and now - last_push < STREAM_MIN_INTERVAL:
                    return
                # meta_content 存储独立的任务元数据头（阶段·耗时·模型·上下文）。
                meta_content = render_task_meta(task, started_at)
                # conversation_body 始终包含同一份历史与本轮累计正文，历史前缀保持稳定。
                conversation_body = conversation_card_content(
                    previous_history, message.text, body, paginate=False
                )
                # 先更新元数据元素，再更新正文元素；两者各自使用独立且严格递增的序号。
                if self._stream_card_content(
                    card_id,
                    meta_content,
                    sequence,
                    element_id=STREAM_CARD_META_ID,
                ):
                    sequence += 1
                if self._stream_card_content(
                    card_id,
                    conversation_body,
                    sequence,
                    element_id=STREAM_CARD_SUMMARY_ID,
                ):
                    sequence += 1
                    last_push = now

        def heartbeat() -> None:
            """长任务无新 token 时定时刷新耗时，避免用户误以为卡住。"""
            while not heartbeat_stop.wait(STREAM_HEARTBEAT_INTERVAL):
                push_progress(latest_body, force=True)

        def on_delta(full_text: str) -> None:
            """接收 Claude 实时文本并刷新同一张任务卡片。"""
            push_progress(full_text)

        # heartbeat_thread 存储本轮任务的状态心跳线程。
        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        push_progress(DEFAULT_PROCESSING_TEXT, force=True)
        if clear_input:
            # empty_input 存储没有 default_value 的独立输入组件，替换后客户端输入立即清空。
            empty_input = answer_card_input_form(task.task_id)
            if self._replace_card_element(
                card_id, empty_input["element_id"], empty_input, sequence
            ):
                sequence += 1
        # had_error 标记最终卡片是否需要使用错误样式和重试提示。
        had_error = False
        try:
            # answer 存储 Claude 对本条消息生成的最终完整回答。
            answer = self.task_manager.ask_task(
                task.task_id, message.text, on_delta=on_delta
            )
        except Exception as exc:
            had_error = True
            answer = friendly_error_message(exc)
            self._log(f"任务 {task.task_id} 执行失败：{exc}")
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=2)

        push_progress(answer, force=True)
        # 卡片保持 streaming_mode，后续表单提问才能继续流式更新同一 CardKit 实体。
        self.task_cards[task.task_id] = (card_id, card_message_id, sequence)
        self._save_task_cards()
        if had_error:
            self._log(
                f"任务 {task.task_id} 已展示友好失败卡片 card_message_id={card_message_id}"
            )
        return True
