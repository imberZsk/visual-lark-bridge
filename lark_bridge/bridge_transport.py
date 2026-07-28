"""BridgeTransportMixin 拆分出的应用职责。"""

from __future__ import annotations

import subprocess
from typing import Optional


from .config import DEFAULT_PROCESSING_TEXT
from .config import DRY_RUN_MESSAGE_ID
from .config import STREAM_CARD_SUMMARY_ID
from .lark_commands import build_lark_create_card_args
from .lark_commands import build_lark_finish_stream_args
from .lark_commands import build_lark_replace_element_args
from .lark_commands import build_lark_reply_args
from .lark_commands import build_lark_send_card_args
from .lark_commands import build_lark_send_chat_message_args
from .lark_commands import build_lark_stream_content_args
from .lark_commands import build_lark_stream_mode_args
from .lark_commands import build_lark_update_message_args
from .lark_commands import extract_card_id
from .lark_commands import extract_sent_message_id
from datetime import datetime


class BridgeTransportMixin:
    def _send_chat_message(self, chat_id: str, markdown: str) -> bool:
        """向指定会话主动发送 Markdown；chat_id 不依赖任何源消息。"""
        if self.args.dry_run:
            self._log(f"[dry-run] 将主动推送到 {chat_id}: {markdown}")
            return True
        # completed 存储主动发送命令结果。
        completed = subprocess.run(
            build_lark_send_chat_message_args(
                chat_id,
                markdown,
                identity=self.args.reply_identity,
                profile=self.args.lark_profile,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self._log(
                f"主动推送失败 code={completed.returncode} stderr={completed.stderr.strip()}"
            )
            return False
        return True

    def _create_stream_card(
        self,
        task_id: str = "",
        source_message_id: str = "",
        initial_content: str = DEFAULT_PROCESSING_TEXT,
    ) -> Optional[str]:
        """创建流式卡片；任务参数用于回调，initial_content 是建卡时显示的正文。"""
        # completed 保存创建卡片命令的执行结果。
        completed = subprocess.run(
            build_lark_create_card_args(
                identity=self.args.reply_identity,
                profile=self.args.lark_profile,
                task_id=task_id,
                source_message_id=source_message_id,
                initial_content=initial_content,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self._log(
                f"创建卡片失败 code={completed.returncode} stderr={completed.stderr.strip()}"
            )
            return None
        # card_id 是从创建卡片响应里解析出的卡片实体 ID。
        card_id = extract_card_id(completed.stdout)
        if card_id is None:
            self._log(f"创建卡片响应无 card_id：{completed.stdout.strip()}")
            return None
        self._log(f"已创建流式卡片 card_id={card_id}")
        return card_id

    def _send_stream_card(self, message_id: str, card_id: str) -> Optional[str]:
        """回复引用流式卡片的消息，成功返回新消息 ID。"""
        # completed 保存发送卡片消息命令的执行结果。
        completed = subprocess.run(
            build_lark_send_card_args(
                message_id,
                card_id,
                identity=self.args.reply_identity,
                profile=self.args.lark_profile,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self._log(
                f"发送卡片消息失败 code={completed.returncode} stderr={completed.stderr.strip()}"
            )
            return None
        self._log(f"已发送流式卡片消息 card_id={card_id}: {completed.stdout.strip()}")
        return extract_sent_message_id(completed.stdout)

    def _stream_card_content(
        self,
        card_id: str,
        content: str,
        sequence: int,
        element_id: str = STREAM_CARD_SUMMARY_ID,
    ) -> bool:
        """把内容覆盖写入指定卡片元素；element_id 是目标元素 ID，成功返回 True。"""
        # completed 保存流式文本更新命令的执行结果。
        completed = subprocess.run(
            build_lark_stream_content_args(
                card_id,
                content,
                sequence,
                element_id=element_id,
                identity=self.args.reply_identity,
                profile=self.args.lark_profile,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self._log(
                f"流式追加失败 seq={sequence} code={completed.returncode} stderr={completed.stderr.strip()}"
            )
            return False
        return True

    def _replace_card_element(
        self,
        card_id: str,
        element_id: str,
        element: dict,
        sequence: int,
    ) -> bool:
        """替换指定 CardKit 组件；element 是完整组件，sequence 是本次更新序号。"""
        # completed 存储 CardKit 组件替换命令的执行结果。
        try:
            completed = subprocess.run(
                build_lark_replace_element_args(
                    card_id,
                    element_id,
                    element,
                    sequence,
                    identity=self.args.reply_identity,
                    profile=self.args.lark_profile,
                ),
                text=True,
                capture_output=True,
                check=False,
                timeout=5,
            )
        except subprocess.TimeoutExpired:
            # 清空输入属于辅助体验，超时后继续执行 Claude，不能阻塞用户的主任务。
            self._log(f"替换卡片组件超时 element_id={element_id} seq={sequence}")
            return False
        if completed.returncode != 0:
            self._log(
                f"替换卡片组件失败 element_id={element_id} seq={sequence} "
                f"code={completed.returncode} stderr={completed.stderr.strip()}"
            )
            return False
        return True

    def _finish_stream_card(self, card_id: str, sequence: int) -> bool:
        """关闭卡片流式模式给本轮回答定稿，成功返回 True。"""
        # completed 保存卡片定稿命令的执行结果。
        completed = subprocess.run(
            build_lark_finish_stream_args(
                card_id,
                sequence,
                identity=self.args.reply_identity,
                profile=self.args.lark_profile,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self._log(
                f"卡片定稿失败 code={completed.returncode} stderr={completed.stderr.strip()}"
            )
            return False
        self._log(f"已给流式卡片定稿 card_id={card_id}")
        return True

    def _set_stream_mode(self, card_id: str, sequence: int, enabled: bool) -> bool:
        """切换卡片流式模式；enabled 为真时允许复用已定稿任务卡片。"""
        # completed 存储卡片流式模式更新命令结果。
        completed = subprocess.run(
            build_lark_stream_mode_args(
                card_id,
                sequence,
                enabled,
                identity=self.args.reply_identity,
                profile=self.args.lark_profile,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self._log(
                f"切换卡片流式模式失败 enabled={enabled}: {completed.stderr.strip()}"
            )
            return False
        return True

    def _reply(self, message_id: str, answer: str) -> None:
        """调用 lark-cli 将 Claude 回答回复到原飞书消息。"""
        self._send_reply(message_id, answer)

    def _send_reply(self, message_id: str, text: str) -> Optional[str]:
        """调用 lark-cli 回复飞书消息，并返回机器人新消息 ID。"""
        if self.args.dry_run:
            self._log(f"[dry-run] 将回复 {message_id}: {text}")
            return DRY_RUN_MESSAGE_ID

        # completed 保存 lark-cli 回复命令的执行结果。
        completed = subprocess.run(
            build_lark_reply_args(
                message_id,
                text,
                identity=self.args.reply_identity,
                profile=self.args.lark_profile,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self._log(
                f"回复失败 code={completed.returncode} stderr={completed.stderr.strip()}"
            )
            return None

        # sent_message_id 存储刚发送成功的机器人回复消息 ID，用于后续编辑占位消息。
        sent_message_id = extract_sent_message_id(completed.stdout)
        self._log(f"已回复 {message_id}: {completed.stdout.strip()}")
        return sent_message_id

    def _update_message(self, message_id: str, text: str) -> bool:
        """调用飞书编辑消息接口，把占位回复替换为最终答案。"""
        if self.args.dry_run:
            self._log(f"[dry-run] 将更新消息 {message_id}: {text}")
            return True

        # completed 保存 lark-cli 原生编辑消息命令的执行结果。
        completed = subprocess.run(
            build_lark_update_message_args(
                message_id,
                text,
                identity=self.args.reply_identity,
                profile=self.args.lark_profile,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            self._log(
                f"更新消息失败 code={completed.returncode} stderr={completed.stderr.strip()}"
            )
            return False

        self._log(f"已更新消息 {message_id}: {completed.stdout.strip()}")
        return True

    def _log(self, message: str) -> None:
        """写入桥接服务日志，同时打印到当前终端。"""
        # line 是带本地时间前缀的日志行。
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
        print(line, flush=True)
        self.bridge_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.bridge_log_path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
