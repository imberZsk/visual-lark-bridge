"""consumers 模块。"""

from __future__ import annotations

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Iterable, Optional


from .lark_commands import build_lark_consume_args
from .lark_commands import build_lark_gateway_args
from .lark_commands import build_stdin_keeper_args


class LarkGatewayConsumer:
    """管理官方 SDK 单长连接网关，同时接收消息事件与卡片回调。"""

    def __init__(
        self, gateway_path: Path, config_path: Path, profile: str, log_dir: Path
    ):
        """初始化网关；gateway_path 是 Python 入口，config_path 是 lark-cli 配置文件。"""
        # gateway_path 存储 Python 事件网关脚本路径。
        self.gateway_path = gateway_path
        # config_path 存储包含目标应用 profile 的 lark-cli 配置路径。
        self.config_path = config_path
        # profile 存储目标飞书应用 profile 名称。
        self.profile = profile
        # log_dir 存储网关 stdout 与 stderr 日志。
        self.log_dir = log_dir
        # process 存储正在运行的 Python 网关子进程。
        self.process: Optional[subprocess.Popen[str]] = None
        # stderr_thread 持续读取网关诊断输出，避免管道阻塞。
        self.stderr_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """启动事件网关并等待 WebSocket 确认连接成功。"""
        if not self.gateway_path.is_file():
            raise FileNotFoundError(f"找不到飞书事件网关：{self.gateway_path}")
        if not self.config_path.is_file():
            raise FileNotFoundError(f"找不到 lark-cli 配置：{self.config_path}")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # ready 在线程读取到网关 ready 标记后置位。
        ready = threading.Event()
        # startup_errors 保存启动阶段 stderr 尾部，失败时用于报错。
        startup_errors: list[str] = []
        self.process = subprocess.Popen(
            build_lark_gateway_args(self.gateway_path, self.config_path, self.profile),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if self.process.stderr is None:
            raise RuntimeError("无法读取飞书事件网关 stderr")
        self.stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(ready, startup_errors),
            daemon=True,
        )
        self.stderr_thread.start()
        # deadline 存储等待 WebSocket ready 的截止时间。
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if ready.is_set():
                return
            if self.process.poll() is not None:
                # error_tail 存储最近几行启动错误，避免把无关长日志带入异常。
                error_tail = "".join(startup_errors[-8:]).strip()
                raise RuntimeError(
                    f"飞书事件网关提前退出，退出码 {self.process.returncode}: {error_tail}"
                )
            time.sleep(0.1)
        raise TimeoutError("等待飞书事件网关 ready 超时")

    def stop(self) -> None:
        """向事件网关发送 SIGTERM，让官方 SDK 主动关闭 WebSocket。"""
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()

    def _drain_stderr(self, ready: threading.Event, startup_errors: list[str]) -> None:
        """持续记录网关 stderr；ready 和 startup_errors 用于判断启动结果。"""
        if self.process is None or self.process.stderr is None:
            return
        # stderr_path 存储事件网关诊断日志路径。
        stderr_path = self.log_dir / "lark-event-gateway.stderr.log"
        with stderr_path.open("a", encoding="utf-8") as stderr_log:
            for line in self.process.stderr:
                stderr_log.write(line)
                stderr_log.flush()
                startup_errors.append(line)
                if "[gateway] ready" in line:
                    ready.set()

    def events(self) -> Iterable[dict]:
        """逐条产出网关 stdout 中的普通消息或卡片回调 NDJSON。"""
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("飞书事件网关尚未启动")
        # stdout_path 存储事件网关原始事件日志路径。
        stdout_path = self.log_dir / "lark-event-gateway.stdout.log"
        with stdout_path.open("a", encoding="utf-8") as stdout_log:
            for line in self.process.stdout:
                stdout_log.write(line)
                stdout_log.flush()
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


class LarkEventConsumer:
    """管理 lark-cli 事件消费子进程。"""

    def __init__(
        self,
        identity: str,
        log_dir: Path,
        profile: Optional[str],
        event_key: str = "im.message.receive_v1",
    ):
        """初始化事件消费配置；event_key 指定要监听的飞书事件。"""
        # identity 存储 lark-cli 监听事件时使用的身份类型。
        self.identity = identity
        # profile 存储 lark-cli profile 名称，用来绑定正确的飞书机器人。
        self.profile = profile
        # event_key 存储当前消费者订阅的飞书事件类型。
        self.event_key = event_key
        # log_dir 存储 lark-cli event 的 stderr 诊断日志。
        self.log_dir = log_dir
        # process 保存 lark-cli event consume 子进程。
        self.process: Optional[subprocess.Popen[str]] = None
        # stdin_keeper 保存 tail -f /dev/null 子进程，用于持续占住 lark-cli stdin。
        self.stdin_keeper: Optional[subprocess.Popen[bytes]] = None
        # stderr_thread 持续消费 stderr，避免长时间运行时缓冲区堵塞。
        self.stderr_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """启动飞书事件消费进程并等待 ready 标记。"""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # ready 在线程读取到 lark-cli 的 ready 标记后置位。
        ready = threading.Event()
        # startup_errors 保存启动阶段 stderr 尾部，失败时用于报错。
        startup_errors: list[str] = []
        self.stdin_keeper = subprocess.Popen(
            build_stdin_keeper_args(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.process = subprocess.Popen(
            build_lark_consume_args(
                self.identity, profile=self.profile, event_key=self.event_key
            ),
            stdin=self.stdin_keeper.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        if self.stdin_keeper.stdout is not None:
            self.stdin_keeper.stdout.close()

        if self.process.stderr is None:
            raise RuntimeError("无法读取 lark-cli event stderr")

        self.stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(ready, startup_errors),
            daemon=True,
        )
        self.stderr_thread.start()

        # deadline 是等待 lark-cli event ready 的截止时间。
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if ready.is_set():
                return
            if self.process.poll() is not None:
                error_tail = "".join(startup_errors[-8:]).strip()
                raise RuntimeError(
                    f"lark-cli event 提前退出，退出码 {self.process.returncode}: {error_tail}"
                )
            time.sleep(0.1)
        raise TimeoutError("等待 lark-cli event ready 超时")

    def stop(self) -> None:
        """关闭事件消费进程的 stdin，让 lark-cli 优雅退出。"""
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.terminate()
        if self.stdin_keeper is not None:
            self.stdin_keeper.terminate()
            try:
                self.stdin_keeper.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.stdin_keeper.kill()

    def _drain_stderr(self, ready: threading.Event, startup_errors: list[str]) -> None:
        """持续读取 lark-cli event stderr，写日志并识别 ready 标记。"""
        if self.process is None or self.process.stderr is None:
            return

        # log_slug 存储可安全用于日志文件名的事件类型。
        log_slug = self.event_key.replace(".", "-")
        with (self.log_dir / f"lark-event-{log_slug}.stderr.log").open(
            "a", encoding="utf-8"
        ) as stderr_log:
            for line in self.process.stderr:
                stderr_log.write(line)
                stderr_log.flush()
                startup_errors.append(line)
                if "[event] ready" in line:
                    ready.set()

    def events(self) -> Iterable[dict]:
        """逐条产出 lark-cli stdout 中的 NDJSON 事件。"""
        if self.process is None or self.process.stdout is None:
            raise RuntimeError("lark-cli event 尚未启动")

        # log_slug 存储可安全用于日志文件名的事件类型。
        log_slug = self.event_key.replace(".", "-")
        with (self.log_dir / f"lark-event-{log_slug}.stdout.log").open(
            "a", encoding="utf-8"
        ) as stdout_log:
            for line in self.process.stdout:
                stdout_log.write(line)
                stdout_log.flush()
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
