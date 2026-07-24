"""通过 Claude Code stream-json 协议执行任务。"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path
from typing import Callable, Optional


from .claude_protocol import friendly_tool_phase
from .claude_protocol import parse_claude_stream_event
from .config import CLAUDE_CONTEXT_WINDOW


class ClaudeStreamSession:
    """通过 Claude Code stream-json 接口提供 token 级实时输出和会话续接。"""

    def __init__(
        self,
        workspace: Path,
        log_dir: Path,
        system_prompt: str,
        timeout: int,
        session_id: Optional[str] = None,
        resume: bool = False,
    ):
        """初始化流式会话；workspace 是工作目录，session_id 用于恢复历史对话。"""
        # workspace 存储 Claude Code 执行任务时使用的工作目录。
        self.workspace = workspace
        # log_dir 存储 Claude stream-json 和 stderr 排查日志。
        self.log_dir = log_dir
        # system_prompt 存储追加给 Claude 的飞书回复约束。
        self.system_prompt = system_prompt
        # timeout 存储长任务软提示阈值，stream-json 模式不会因此终止任务。
        self.timeout = timeout
        # session_id 存储 Claude 会话 UUID，用于后续轮次续接上下文。
        self.session_id = session_id or str(uuid.uuid4())
        # resume 标记首轮是否需要恢复已经存在的 Claude 会话。
        self.resume = resume
        # process 存储当前正在执行本轮请求的 Claude 子进程。
        self.process: Optional[subprocess.Popen] = None
        # stream_log_path 存储 Claude 输出的原始 NDJSON，便于排查流式事件。
        self.stream_log_path = log_dir / "claude-stream.jsonl"
        # stderr_path 存储 Claude 子进程标准错误输出。
        self.stderr_path = log_dir / "claude-stream.stderr.log"
        # model 存储 Claude init 事件报告的当前模型名称。
        self.model = "Claude"
        # context_tokens 存储当前请求已占用的上下文 token 数。
        self.context_tokens = 0
        # context_window 存储当前模型的上下文窗口大小。
        self.context_window = CLAUDE_CONTEXT_WINDOW
        # phase 存储当前可展示的执行阶段。
        self.phase = "准备中"
        # cancelled 标记本轮是否由用户主动停止。
        self.cancelled = False

    def start(self) -> None:
        """准备工作目录和日志目录；Claude 子进程在每轮 ask 时按需启动。"""
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def stop(self) -> None:
        """停止当前仍在执行的 Claude 流式子进程。"""
        if self.process is not None and self.process.poll() is None:
            self.cancelled = True
            self.process.terminate()

    def ask(
        self, message: str, on_delta: Optional[Callable[[str], None]] = None
    ) -> str:
        """发送一轮消息并实时回调思考、工具状态和正文；message 是飞书问题正文。"""
        self.cancelled = False
        self.phase = "思考中"
        try:
            return self._run_once(message, on_delta=on_delta)
        except RuntimeError as exc:
            # 工作目录迁移可能使旧 session_id 无法恢复，此时新建会话并完整重试当前问题。
            if not self.resume or "No conversation found with session ID" not in str(
                exc
            ):
                raise

        self.resume = False
        self.session_id = str(uuid.uuid4())
        return self._run_once(message, on_delta=on_delta)

    def _build_args(self, prompt: str) -> list[str]:
        """构造单轮 Claude stream-json 命令；prompt 是包装后的用户问题。"""
        # args 存储 Claude Code 非交互实时输出命令参数。
        args = [
            "claude",
            "--print",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--permission-mode",
            "bypassPermissions",
            "--append-system-prompt",
            self.system_prompt,
        ]
        if self.resume:
            args.extend(["--resume", self.session_id])
        else:
            args.extend(["--session-id", self.session_id])
        args.append(prompt)
        return args

    def _run_once(
        self, message: str, on_delta: Optional[Callable[[str], None]] = None
    ) -> str:
        """执行一次 Claude 子进程并消费 NDJSON；message 是当前用户问题。"""
        # prompt 存储传给 Claude 的完整飞书回复要求和用户问题。
        prompt = (
            "请回答下面这条来自飞书的消息。"
            "只输出要发回飞书的正文，不要添加额外前缀。\n\n"
            f"{message}"
        )
        # answer_text 累积最终正文 token。
        answer_text = ""
        # thinking_text 累积正文开始前的思考 token。
        thinking_text = ""
        # result_error 存储 Claude result 事件报告的失败原因。
        result_error = ""
        with (
            self.stream_log_path.open("a", encoding="utf-8") as stream_log,
            self.stderr_path.open("a", encoding="utf-8") as stderr_log,
        ):
            # process 存储本轮 Claude Code 流式子进程。
            process = subprocess.Popen(
                self._build_args(prompt),
                cwd=self.workspace,
                stdout=subprocess.PIPE,
                stderr=stderr_log,
                text=True,
                bufsize=1,
            )
            self.process = process
            if process.stdout is None:
                raise RuntimeError("Claude 流式输出管道创建失败")

            for line in process.stdout:
                stream_log.write(line)
                stream_log.flush()
                try:
                    # payload 存储当前 NDJSON 行解析后的 Claude 事件。
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # parsed_session_id 存储事件返回的真实会话 ID。
                parsed_session_id = payload.get("session_id")
                if isinstance(parsed_session_id, str) and parsed_session_id:
                    self.session_id = parsed_session_id

                if payload.get("type") == "system" and payload.get("subtype") == "init":
                    # parsed_model 存储 Claude init 事件中的模型名称。
                    parsed_model = payload.get("model")
                    if isinstance(parsed_model, str) and parsed_model:
                        self.model = parsed_model

                if payload.get("type") == "stream_event":
                    # stream_event 存储 Claude API token 事件主体。
                    stream_event = payload.get("event")
                    if (
                        isinstance(stream_event, dict)
                        and stream_event.get("type") == "message_start"
                    ):
                        # message_data 存储 message_start 中的消息及用量信息。
                        message_data = stream_event.get("message")
                        if isinstance(message_data, dict):
                            # usage 存储当前请求的上下文 token 用量。
                            usage = message_data.get("usage")
                            if isinstance(usage, dict):
                                self.context_tokens = sum(
                                    int(usage.get(key, 0) or 0)
                                    for key in (
                                        "input_tokens",
                                        "cache_creation_input_tokens",
                                        "cache_read_input_tokens",
                                    )
                                )

                if payload.get("type") == "result":
                    if payload.get("is_error"):
                        # result_value 存储 Claude result 事件中的错误文本。
                        result_value = payload.get("result")
                        result_error = str(
                            result_value or payload.get("subtype") or "Claude 执行失败"
                        )
                    else:
                        # result_value 存储 Claude 汇总的最终回答，用它覆盖工具调用前的阶段性文本。
                        result_value = payload.get("result")
                        if isinstance(result_value, str):
                            answer_text = result_value
                    continue

                answer_text, thinking_text, display_text, _ = parse_claude_stream_event(
                    payload,
                    answer_text,
                    thinking_text,
                )
                if on_delta is not None and display_text:
                    if display_text.startswith("正在使用工具："):
                        # tool_name 存储当前工具名，用于转换为更友好的阶段状态。
                        tool_name = display_text.removeprefix(
                            "正在使用工具："
                        ).removesuffix("...")
                        self.phase = friendly_tool_phase(tool_name)
                    elif display_text.startswith("思考中："):
                        self.phase = "思考中"
                    elif display_text.startswith("Claude 服务繁忙"):
                        self.phase = "等待服务"
                    else:
                        self.phase = "整理答案"
                    on_delta(display_text)

            # return_code 存储 Claude 子进程退出码。
            return_code = process.wait()
            self.process = None

        if self.cancelled:
            raise InterruptedError("任务已停止")
        if return_code != 0 or result_error:
            raise RuntimeError(result_error or f"Claude 进程退出码：{return_code}")
        if not answer_text:
            raise RuntimeError("Claude 没有产生可回复的正文")
        self.resume = True
        self.phase = "已完成"
        return answer_text
