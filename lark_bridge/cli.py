"""cli 模块。"""

from __future__ import annotations

import argparse
import fcntl
import os
import sys
from pathlib import Path
from typing import IO
from typing import Optional


from .app import BridgeApp
from .config import DEFAULT_EVENT_GATEWAY
from .config import DEFAULT_LARK_CONFIG
from .config import DEFAULT_LARK_PROFILE
from .config import DEFAULT_LOG_DIR
from .config import DEFAULT_SYSTEM_PROMPT
from .config import DEFAULT_WORKSPACE


# INSTANCE_LOCK_FILE 存储同一运行目录内桥接单实例锁的文件名。
INSTANCE_LOCK_FILE = "bridge.lock"


def acquire_instance_lock(log_dir: Path) -> IO[str]:
    """独占锁定当前运行目录；log_dir 用于区分彼此独立的桥接配置。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    # lock_path 存储当前桥接运行目录对应的单实例锁文件路径。
    lock_path = log_dir / INSTANCE_LOCK_FILE
    # lock_file 保存进程生命周期内持有的文件描述符，关闭后系统自动释放锁。
    lock_file = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        lock_file.close()
        raise RuntimeError("同一运行目录已有桥接服务正在运行") from exc
    lock_file.seek(0)
    lock_file.truncate()
    lock_file.write(f"{os.getpid()}\n")
    lock_file.flush()
    return lock_file


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """解析命令行参数，允许按需覆盖工作目录、身份和超时时间。"""
    # parser 定义桥接脚本支持的命令行参数。
    parser = argparse.ArgumentParser(
        description="飞书消息到本地交互式 Claude 的桥接服务"
    )
    parser.add_argument(
        "--workspace", default=str(DEFAULT_WORKSPACE), help="Claude 交互式会话运行目录"
    )
    parser.add_argument(
        "--log-dir", default=str(DEFAULT_LOG_DIR), help="桥接脚本日志目录"
    )
    parser.add_argument(
        "--lark-profile", default=DEFAULT_LARK_PROFILE, help="lark-cli profile 名称"
    )
    parser.add_argument(
        "--lark-config",
        default=str(DEFAULT_LARK_CONFIG),
        help="包含机器人 profile 的 lark-cli 配置文件",
    )
    parser.add_argument(
        "--event-gateway",
        default=str(DEFAULT_EVENT_GATEWAY),
        help="飞书官方 SDK 单长连接网关脚本",
    )
    parser.add_argument(
        "--lark-identity",
        default="bot",
        choices=["bot", "user"],
        help="监听飞书事件的身份",
    )
    parser.add_argument(
        "--reply-identity",
        default="bot",
        choices=["bot", "user"],
        help="回复飞书消息的身份",
    )
    parser.add_argument(
        "--claude-timeout",
        type=int,
        default=180,
        help="等待 Claude 最终回答前记录软超时提示的秒数",
    )
    parser.add_argument("--provider", choices=["claude", "codex"], default="claude")
    parser.add_argument("--codex-model", default="")
    parser.add_argument(
        "--system-prompt",
        default=DEFAULT_SYSTEM_PROMPT,
        help="追加给 Claude 的系统提示",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要回复的内容，不真正发送飞书消息",
    )
    parser.add_argument(
        "--once", action="store_true", help="处理一条消息后退出，适合联调"
    )
    return parser.parse_args(argv)


def main() -> int:
    """程序入口：创建并运行桥接应用。"""
    # args 是从命令行解析出的运行配置。
    args = parse_args()
    # instance_lock 保存桥接进程持有的单实例文件锁，避免重复监听写坏任务状态。
    instance_lock: Optional[IO[str]] = None
    try:
        instance_lock = acquire_instance_lock(Path(args.log_dir).expanduser().resolve())
        # app 是桥接应用实例，负责启动和编排所有子进程。
        app = BridgeApp(args)
        app.run()
    except KeyboardInterrupt:
        print("收到中断，退出。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"桥接服务异常：{exc}", file=sys.stderr)
        return 1
    finally:
        if instance_lock is not None:
            instance_lock.close()
    return 0
