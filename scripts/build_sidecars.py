"""使用 PyInstaller 构建 Electron 随包分发的两个 Python sidecar。"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


# PROJECT_ROOT 存储项目根目录。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# OUTPUT_DIR 存储 electron-builder 将复制进应用资源的可执行文件。
OUTPUT_DIR = PROJECT_ROOT / "build" / "sidecars"
# WORK_DIR 存储 PyInstaller 中间产物。
WORK_DIR = PROJECT_ROOT / "build" / "pyinstaller"
# SPEC_DIR 存储 PyInstaller 自动生成的 spec 文件。
SPEC_DIR = PROJECT_ROOT / "build" / "specs"


def build_sidecar(name: str, entrypoint: Path, collect_packages: tuple[str, ...]) -> None:
    """构建单个 sidecar；name 是产物名，entrypoint 是 Python 入口。"""
    # command 存储本次 PyInstaller 构建参数。
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        name,
        "--distpath",
        str(OUTPUT_DIR),
        "--workpath",
        str(WORK_DIR / name),
        "--specpath",
        str(SPEC_DIR),
    ]
    for package_name in collect_packages:
        command.extend(["--collect-all", package_name])
    command.append(str(entrypoint))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> int:
    """清理旧产物并构建桥接主进程与事件网关。"""
    shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SPEC_DIR.mkdir(parents=True, exist_ok=True)
    build_sidecar("visual-lark-bridge", PROJECT_ROOT / "visual_lark_bridge.py", ())
    build_sidecar(
        "lark-event-gateway",
        PROJECT_ROOT / "lark_bridge" / "event_gateway.py",
        ("lark_oapi", "Crypto"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
