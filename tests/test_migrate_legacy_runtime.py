import json
import tempfile
import unittest
from pathlib import Path

from migrate_legacy_runtime import MIGRATION_MARKER_NAME, migrate_legacy_runtime
from runtime_paths import encode_claude_project_path


class LegacyRuntimeMigrationTest(unittest.TestCase):
    """验证旧品牌运行数据和 Claude Code 会话可以无损迁移。"""

    def test_migrate_copies_runtime_state_and_claude_sessions_once(self):
        """首次迁移应复制状态与会话，重复执行不得覆盖新目录。"""
        with tempfile.TemporaryDirectory() as tmp:
            # root_dir 存储隔离测试使用的临时根目录。
            root_dir = Path(tmp)
            # legacy_install_dir 存储模拟的旧品牌运行目录。
            legacy_install_dir = root_dir / "Application Support" / "lark-claude-bridge"
            # target_install_dir 存储模拟的新品牌运行目录。
            target_install_dir = root_dir / "Application Support" / "lark-ai-bridge"
            # claude_projects_dir 存储模拟的 Claude Code projects 根目录。
            claude_projects_dir = root_dir / ".claude" / "projects"
            # legacy_workspace_dir 存储旧运行目录中的 Claude workspace。
            legacy_workspace_dir = legacy_install_dir / "claude-workspace"
            # legacy_task_dir 存储旧 workspace 中的历史任务目录。
            legacy_task_dir = legacy_workspace_dir / "t1"
            # legacy_logs_dir 存储旧任务和卡片状态所在目录。
            legacy_logs_dir = legacy_install_dir / "logs"
            # legacy_attachment_dir 存储旧飞书附件目录。
            legacy_attachment_dir = legacy_install_dir / "attachments" / "om_test"
            legacy_task_dir.mkdir(parents=True)
            legacy_logs_dir.mkdir(parents=True)
            legacy_attachment_dir.mkdir(parents=True)
            claude_projects_dir.mkdir(parents=True)
            (legacy_workspace_dir / "CLAUDE.md").write_text("个人工作区说明", encoding="utf-8")
            (legacy_task_dir / "task.txt").write_text("历史任务文件", encoding="utf-8")
            (legacy_logs_dir / "tasks-state.json").write_text('{"tasks":[{"task_id":"t1"}]}', encoding="utf-8")
            (legacy_logs_dir / "cards-state.json").write_text('{"cards":{"t1":{}}}', encoding="utf-8")
            (legacy_attachment_dir / "file.txt").write_text("附件", encoding="utf-8")
            (legacy_install_dir / ".env").write_text("LARK_PROFILE=test\n", encoding="utf-8")
            # legacy_project_name 存储旧任务 workspace 对应的 Claude projects 编码目录名。
            legacy_project_name = encode_claude_project_path(legacy_task_dir)
            # legacy_project_dir 存储包含历史 session 的模拟 Claude project 目录。
            legacy_project_dir = claude_projects_dir / legacy_project_name
            legacy_project_dir.mkdir()
            (legacy_project_dir / "session.jsonl").write_text('{"sessionId":"session-old"}\n', encoding="utf-8")

            # first_summary 存储首次迁移的分类统计。
            first_summary = migrate_legacy_runtime(legacy_install_dir, target_install_dir, claude_projects_dir)
            # target_task_dir 存储迁移后任务 workspace 的目标目录。
            target_task_dir = target_install_dir / "claude-workspace" / "t1"
            # target_project_name 存储新任务 workspace 对应的 Claude projects 编码目录名。
            target_project_name = encode_claude_project_path(target_task_dir)
            # target_project_dir 存储迁移后的 Claude session 目录。
            target_project_dir = claude_projects_dir / target_project_name

            self.assertFalse(first_summary["already_migrated"])
            self.assertEqual(first_summary["runtime_config_files"], 1)
            self.assertEqual(first_summary["claude_projects"], 1)
            self.assertEqual((target_install_dir / "claude-workspace" / "CLAUDE.md").read_text(encoding="utf-8"), "个人工作区说明")
            self.assertEqual((target_install_dir / "logs" / "tasks-state.json").read_text(encoding="utf-8"), '{"tasks":[{"task_id":"t1"}]}')
            self.assertEqual((target_install_dir / "attachments" / "om_test" / "file.txt").read_text(encoding="utf-8"), "附件")
            self.assertTrue((target_project_dir / "session.jsonl").is_file())
            self.assertTrue((target_install_dir / ".runtime-initialized").is_file())

            (target_task_dir / "task.txt").write_text("新目录修改", encoding="utf-8")
            # second_summary 存储重复迁移结果，用来断言幂等保护生效。
            second_summary = migrate_legacy_runtime(legacy_install_dir, target_install_dir, claude_projects_dir)

            self.assertTrue(second_summary["already_migrated"])
            self.assertEqual((target_task_dir / "task.txt").read_text(encoding="utf-8"), "新目录修改")
            self.assertTrue((target_install_dir / MIGRATION_MARKER_NAME).is_file())
            # marker_payload 存储迁移标记中持久化的首次迁移统计。
            marker_payload = json.loads((target_install_dir / MIGRATION_MARKER_NAME).read_text(encoding="utf-8"))
            self.assertEqual(marker_payload["claude_projects"], 1)


if __name__ == "__main__":
    unittest.main()
