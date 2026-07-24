"""通过 PTY 驱动 Claude Code 交互式会话。"""

from __future__ import annotations

import errno
import os
import pty
import select
import signal
import termios
import time
import uuid
from pathlib import Path
from typing import Callable, Optional


from .claude_logs import extract_assistant_text
from .claude_logs import extract_streaming_assistant_text
from .claude_logs import find_jsonl_containing_text
from .claude_logs import newest_jsonl_file
from .claude_logs import project_log_dir_for_cwd
from .claude_logs import utc_now_iso
from .claude_protocol import build_claude_args
from .claude_protocol import format_pty_submission
from .claude_protocol import should_accept_trust_prompt
from .claude_protocol import strip_ansi


class ClaudeInteractiveSession:
    """管理一个通过 PTY 驱动的本机交互式 Claude Code 会话。"""

    def __init__(
        self,
        workspace: Path,
        log_dir: Path,
        system_prompt: str,
        timeout: int,
        session_id: Optional[str] = None,
        resume: bool = False,
    ):
        """初始化 Claude 会话配置，workspace 是 Claude 的运行目录。"""
        # workspace 存储 Claude Code 交互式会话使用的本地工作目录。
        self.workspace = workspace
        # log_dir 存储桥接脚本排查日志和 Claude TUI 文字转储。
        self.log_dir = log_dir
        # system_prompt 是追加给 Claude 的行为约束。
        self.system_prompt = system_prompt
        # timeout 是单轮等待 Claude 最终回答前记录软超时提示的秒数。
        self.timeout = timeout
        # session_id 是本次 Claude 交互式会话的唯一 ID；持久化恢复时会传入历史 ID 以便续接。
        self.session_id = session_id or str(uuid.uuid4())
        # resume 表示本次启动是否用 --resume 恢复该 session_id 对应的历史对话上下文。
        self.resume = resume
        # child_pid 保存 Claude 子进程 ID，用于退出时发送 SIGTERM。
        self.child_pid: Optional[int] = None
        # fd 保存父进程侧 PTY 文件描述符，用于向 Claude 输入文本并读取屏幕输出。
        self.fd: Optional[int] = None
        # session_log 保存首轮消息后定位到的 Claude JSONL 会话日志路径。
        self.session_log: Optional[Path] = None
        # transcript_path 保存 Claude TUI 屏幕输出的清洗后日志。
        self.transcript_path = log_dir / "claude-pty.log"
        # max_wait_after_soft_timeout 存储内部测试用最大等待秒数；None 表示生产环境不硬切长任务。
        self.max_wait_after_soft_timeout: Optional[float] = None

    def start(self) -> None:
        """启动交互式 Claude，并处理进入主界面前的安全确认。"""
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # pid 是 PTY fork 出来的子进程 ID；fd 是父进程侧控制 Claude TUI 的文件描述符。
        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(self.workspace)
            os.environ.setdefault("TERM", "xterm-256color")
            os.execvp(
                "claude",
                build_claude_args(
                    self.system_prompt, self.session_id, resume=self.resume
                ),
            )

        self.child_pid = pid
        self.fd = fd
        self._set_pty_size(rows=40, cols=120)
        self._accept_startup_prompts(initial_screen=self._drain_output(seconds=2.0))

    def stop(self) -> None:
        """温和停止 Claude 子进程并关闭 PTY。"""
        if self.child_pid:
            try:
                os.kill(self.child_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass

    def ask(
        self, message: str, on_delta: Optional[Callable[[str], None]] = None
    ) -> str:
        """把用户消息输入交互式 Claude，并等待 JSONL 日志里出现新回答。

        on_delta 是可选的流式增量回调：等待期间每读到更长的本轮回答文本，就用
        累计全文回调一次，供上层往飞书流式卡片追加；为空时保持原有一次性返回行为。
        """
        if self.fd is None:
            raise RuntimeError("Claude 会话尚未启动")

        try:
            return self._ask_once(message, on_delta=on_delta)
        except OSError as exc:
            # 迁移工作目录后，Claude 找不到旧会话会退出并让 PTY 返回 EIO；此时保留当前问题并新建会话重试。
            if exc.errno != errno.EIO or not self.resume:
                raise

        self.stop()
        # 新会话不能复用已失效的历史 ID，否则 Claude 会再次立即退出。
        self.resume = False
        self.session_id = str(uuid.uuid4())
        self.session_log = None
        self.start()
        return self._ask_once(message, on_delta=on_delta)

    def _ask_once(
        self, message: str, on_delta: Optional[Callable[[str], None]] = None
    ) -> str:
        """向当前 PTY 提交一次消息；message 是问题正文，on_delta 接收累计流式文本。"""
        if self.fd is None:
            raise RuntimeError("Claude 会话尚未启动")

        # since_iso 记录本轮提问开始时间，用来过滤历史 assistant 回答。
        since_iso = utc_now_iso()
        # marker 是本轮消息唯一标记，用来从 Claude 日志树定位真实会话文件。
        marker = f"LARK_BRIDGE_TURN:{uuid.uuid4()}"
        # prompt 是实际粘贴进 Claude TUI 的完整用户消息。
        prompt = (
            "请回答下面这条来自飞书的消息。"
            "只输出要发回飞书的正文，不要添加额外前缀。\n\n"
            f"{message}\n\n"
            f"[{marker}]\n"
        )

        os.write(self.fd, format_pty_submission(prompt))
        self._drain_output(seconds=0.3)
        os.write(self.fd, b"\r")
        if self.session_log is None:
            self.session_log = self._wait_for_session_log(marker=marker)
        return self._wait_for_answer(since_iso, on_delta=on_delta)

    def _set_pty_size(self, rows: int, cols: int) -> None:
        """设置 PTY 尺寸，减少 Claude TUI 因过窄换行造成的异常表现。"""
        if self.fd is None:
            return
        import fcntl
        import struct

        # window_size 是 TIOCSWINSZ 需要的 rows/cols 二进制结构。
        window_size = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, window_size)

    def _drain_output(self, seconds: float) -> str:
        """读取 Claude TUI 当前可用输出，并追加到本地排查日志。"""
        if self.fd is None:
            return ""

        # deadline 是本次读取 PTY 输出的截止时间。
        deadline = time.monotonic() + seconds
        # chunks 累积 PTY 当前可读的字节块。
        chunks: list[bytes] = []
        while time.monotonic() < deadline:
            # readable 是 select 返回的可读文件描述符列表。
            readable, _, _ = select.select([self.fd], [], [], 0.1)
            if self.fd not in readable:
                continue
            try:
                # chunk 是从 Claude TUI 读取到的一段原始屏幕输出。
                chunk = os.read(self.fd, 8192)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            chunks.append(chunk)

        # text 是把 PTY 字节流按 UTF-8 容错解码后的屏幕文本。
        text = b"".join(chunks).decode("utf-8", "replace")
        if text:
            with self.transcript_path.open("a", encoding="utf-8") as file:
                file.write(strip_ansi(text))
        return text

    def _accept_startup_prompts(self, initial_screen: str) -> None:
        """自动确认专用工作目录启动时 Claude 展示的安全提示。"""
        # screen 保存上一次读取到的 Claude TUI 屏幕内容。
        screen = initial_screen
        for _ in range(3):
            if not should_accept_trust_prompt(screen) or self.fd is None:
                return
            os.write(self.fd, b"\r")
            screen = self._drain_output(seconds=1.5)

    def _wait_for_session_log(self, marker: Optional[str] = None) -> Path:
        """等待 Claude 为本次交互创建 JSONL 日志。"""
        # project_dir 是按工作目录推导出的 Claude 默认项目日志目录。
        project_dir = project_log_dir_for_cwd(self.workspace)
        # target 是使用 --session-id 时理论上对应的 JSONL 文件路径。
        target = project_dir / f"{self.session_id}.jsonl"
        # deadline 是等待日志出现的截止时间。
        deadline = time.monotonic() + 20
        # scan_root 是 Claude Code 所有项目会话日志的根目录。
        scan_root = Path.home() / ".claude" / "projects"
        # scan_since 限制扫描范围，避免误命中过早的历史会话。
        scan_since = time.time() - 60

        while time.monotonic() < deadline:
            self._drain_output(seconds=0.2)
            if marker:
                # marked_log 是包含本轮唯一标记的真实 Claude JSONL 文件。
                marked_log = find_jsonl_containing_text(
                    scan_root, marker, newer_than=scan_since
                )
                if marked_log is not None:
                    return marked_log
            if target.exists():
                return target
            time.sleep(0.2)

        if marker:
            # marked_log 是最后一次兜底扫描得到的真实 Claude JSONL 文件。
            marked_log = find_jsonl_containing_text(
                scan_root, marker, newer_than=scan_since
            )
            if marked_log is not None:
                return marked_log

        # newest 是按理论项目目录找到的最新 JSONL，用作旧版本 Claude 的兜底。
        newest = newest_jsonl_file(project_dir, newer_than=time.time() - 60)
        if newest is not None:
            return newest

        raise TimeoutError(f"没有找到 Claude 会话日志：{target}")

    def _wait_for_answer(
        self, since_iso: str, on_delta: Optional[Callable[[str], None]] = None
    ) -> str:
        """等待指定时间之后的最终 assistant 文本回答。

        on_delta 非空时开启流式模式：每轮循环读取本轮累计的中间 assistant 文本，
        只要比上次更长就用累计全文回调一次，用于往飞书流式卡片追加；为空时保持
        原有行为，只在拿到终稿文本时一次性返回。
        """
        if self.session_log is None:
            raise RuntimeError("Claude 会话日志尚未初始化")

        # soft_deadline 是首次记录长任务仍在执行的时间点，不再作为失败边界。
        soft_deadline = time.monotonic() + self.timeout
        # hard_deadline 是测试或特殊场景使用的最大等待边界，生产默认不设置。
        hard_deadline = (
            time.monotonic() + self.max_wait_after_soft_timeout
            if self.max_wait_after_soft_timeout is not None
            else None
        )
        # soft_timeout_logged 记录是否已经把软超时状态写入日志，避免刷屏。
        soft_timeout_logged = False
        # streamed_len 记录已经通过 on_delta 推送出去的累计文本长度，用来只在有新增时回调。
        streamed_len = 0
        while True:
            self._drain_output(seconds=0.2)

            # on_delta 非空时，先把本轮中间增量文本推给流式卡片，让飞书端逐步显示。
            if on_delta is not None:
                # interim_text 是本轮累计到的最新 assistant 文本，含尚未终稿的中间块。
                interim_text = extract_streaming_assistant_text(
                    self.session_log, since_iso
                )
                if interim_text and len(interim_text) > streamed_len:
                    on_delta(interim_text)
                    streamed_len = len(interim_text)

            # text 是从会话 JSONL 中提取到的最新 assistant 文本。
            text = extract_assistant_text(self.session_log, since_iso)
            if text:
                # 终稿文本长度可能超过最后一次流式推送，补推一次保证卡片显示完整全文。
                if on_delta is not None and len(text) > streamed_len:
                    on_delta(text)
                return text

            # Claude 子进程已经退出时，再继续等待不会产生新答案，应向上抛出真实失败。
            if self.child_pid is not None:
                try:
                    # exited_pid 是已经退出的子进程 ID；0 表示当前未退出。
                    exited_pid, _ = os.waitpid(self.child_pid, os.WNOHANG)
                except ChildProcessError:
                    exited_pid = self.child_pid
                if exited_pid == self.child_pid:
                    raise TimeoutError("Claude 进程已退出，但没有产生最终回答")

            if not soft_timeout_logged and time.monotonic() >= soft_deadline:
                with self.transcript_path.open("a", encoding="utf-8") as file:
                    file.write(
                        f"\n[bridge] Claude 已超过 {self.timeout} 秒仍在执行，继续等待最终回答。\n"
                    )
                soft_timeout_logged = True

            if hard_deadline is not None and time.monotonic() >= hard_deadline:
                raise TimeoutError(
                    f"Claude 在 {self.max_wait_after_soft_timeout} 秒内没有产生最终回答"
                )
            time.sleep(0.5)
