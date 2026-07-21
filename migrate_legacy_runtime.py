#!/usr/bin/env python3
"""把旧版 Lark Claude Bridge 的本机状态迁移到 Lark AI Bridge。"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Optional

from runtime_paths import encode_claude_project_path


# MIGRATION_MARKER_NAME 存储迁移完成标记文件名，避免后续安装覆盖新运行数据。
MIGRATION_MARKER_NAME = ".legacy-runtime-migrated"
# RUNTIME_INITIALIZED_MARKER_NAME 存储安装器识别的运行目录初始化标记文件名。
RUNTIME_INITIALIZED_MARKER_NAME = ".runtime-initialized"
# RUNTIME_DIRECTORY_NAMES 存储需要从旧运行目录完整迁移的用户数据目录。
RUNTIME_DIRECTORY_NAMES = ("logs", "claude-workspace", "attachments")
# RUNTIME_FILE_NAMES 存储需要迁移且不得提交到仓库的本机配置文件。
RUNTIME_FILE_NAMES = (".env",)


def copy_runtime_directory(source_dir: Path, target_dir: Path) -> int:
    """递归合并 source_dir 到 target_dir，并返回迁移的普通文件数量。"""
    if not source_dir.is_dir():
        return 0
    # file_count 存储源目录中需要迁移的普通文件总数，用于安装后核对迁移范围。
    file_count = sum(1 for source_path in source_dir.rglob("*") if source_path.is_file())
    shutil.copytree(source_dir, target_dir, dirs_exist_ok=True, symlinks=True)
    return file_count


def copy_claude_project_sessions(
    claude_projects_dir: Path,
    legacy_workspace_dir: Path,
    target_workspace_dir: Path,
) -> int:
    """迁移 legacy_workspace_dir 及其任务子目录对应的 Claude Code 会话目录。"""
    if not claude_projects_dir.is_dir():
        return 0
    # legacy_prefix 存储旧 workspace 在 Claude projects 中使用的目录名前缀。
    legacy_prefix = encode_claude_project_path(legacy_workspace_dir)
    # target_prefix 存储新 workspace 在 Claude projects 中使用的目录名前缀。
    target_prefix = encode_claude_project_path(target_workspace_dir)
    # copied_directory_count 存储成功迁移的 Claude project 目录数量。
    copied_directory_count = 0
    # legacy_project_dir 存储当前匹配旧 workspace 前缀的 Claude project 目录。
    for legacy_project_dir in claude_projects_dir.glob(f"{legacy_prefix}*"):
        if not legacy_project_dir.is_dir():
            continue
        # suffix 存储任务子目录编码相对旧 workspace 前缀的剩余部分。
        suffix = legacy_project_dir.name[len(legacy_prefix) :]
        # target_project_dir 存储迁移后 Claude Code 应读取的会话目录。
        target_project_dir = claude_projects_dir / f"{target_prefix}{suffix}"
        shutil.copytree(legacy_project_dir, target_project_dir, dirs_exist_ok=True, symlinks=True)
        copied_directory_count += 1
    return copied_directory_count


def migrate_legacy_runtime(
    legacy_install_dir: Path,
    target_install_dir: Path,
    claude_projects_dir: Path,
) -> dict[str, int | bool]:
    """迁移旧运行目录和 Claude 会话；三个参数分别是旧目录、新目录和 Claude projects 根目录。"""
    # migration_marker 存储新运行目录中的幂等迁移标记路径。
    migration_marker = target_install_dir / MIGRATION_MARKER_NAME
    # 已迁移的新目录可能已有用户改动，重复复制旧数据会造成历史内容回退，因此直接返回。
    if migration_marker.exists():
        return {"already_migrated": True, "runtime_files": 0, "runtime_config_files": 0, "claude_projects": 0}
    if not legacy_install_dir.is_dir():
        return {"already_migrated": False, "runtime_files": 0, "runtime_config_files": 0, "claude_projects": 0}

    target_install_dir.mkdir(parents=True, exist_ok=True)
    # runtime_file_count 存储 logs、workspace 和 attachments 中迁移的普通文件总数。
    runtime_file_count = 0
    # directory_name 存储当前需要迁移的运行数据目录名。
    for directory_name in RUNTIME_DIRECTORY_NAMES:
        runtime_file_count += copy_runtime_directory(
            legacy_install_dir / directory_name,
            target_install_dir / directory_name,
        )

    # runtime_config_file_count 存储成功迁移的本机配置文件数量。
    runtime_config_file_count = 0
    # file_name 存储当前需要迁移的本机配置文件名。
    for file_name in RUNTIME_FILE_NAMES:
        # source_file 存储旧运行目录中的本机配置文件路径。
        source_file = legacy_install_dir / file_name
        if not source_file.is_file():
            continue
        # target_file 存储新运行目录中的本机配置文件路径。
        target_file = target_install_dir / file_name
        # 新安装可能已使用另一套 profile，本机配置存在时必须优先保留新值。
        if target_file.exists():
            continue
        shutil.copy2(source_file, target_file)
        runtime_config_file_count += 1

    # Claude Code 按 workspace 绝对路径隔离 session；只迁移 workspace 文件会导致旧任务无法 resume。
    # claude_project_count 存储迁移的 Claude Code 会话目录数量。
    claude_project_count = copy_claude_project_sessions(
        claude_projects_dir,
        legacy_install_dir / "claude-workspace",
        target_install_dir / "claude-workspace",
    )
    # migration_summary 存储迁移统计，既写入标记也输出给安装脚本核对。
    migration_summary: dict[str, int | bool] = {
        "already_migrated": False,
        "runtime_files": runtime_file_count,
        "runtime_config_files": runtime_config_file_count,
        "claude_projects": claude_project_count,
    }
    migration_marker.write_text(json.dumps(migration_summary, ensure_ascii=False) + "\n", encoding="utf-8")
    (target_install_dir / RUNTIME_INITIALIZED_MARKER_NAME).touch()
    return migration_summary


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """解析迁移命令参数；argv 允许测试传入隔离参数列表。"""
    # parser 存储旧目录、新目录和 Claude projects 目录的命令行定义。
    parser = argparse.ArgumentParser(description="迁移 Lark Claude Bridge 本机运行状态")
    parser.add_argument("--legacy-install-dir", type=Path, required=True, help="旧版运行目录")
    parser.add_argument("--target-install-dir", type=Path, required=True, help="新版运行目录")
    parser.add_argument("--claude-projects-dir", type=Path, required=True, help="Claude Code projects 目录")
    return parser.parse_args(argv)


def main() -> int:
    """执行命令行迁移并输出可供安装脚本记录的 JSON 统计。"""
    # args 存储命令行解析后的三个迁移目录。
    args = parse_args()
    # summary 存储本次迁移是否执行以及各类文件数量。
    summary = migrate_legacy_runtime(
        args.legacy_install_dir.expanduser().resolve(),
        args.target_install_dir.expanduser().resolve(),
        args.claude_projects_dir.expanduser().resolve(),
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
