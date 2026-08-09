"""桥接命令行入口测试。"""

from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path

from lark_bridge.cli import InstanceAlreadyRunningError
from lark_bridge.cli import acquire_instance_lock


class InstanceLockTest(unittest.TestCase):
    """验证同一运行目录只能启动一个桥接实例。"""

    def test_second_instance_is_rejected_until_first_lock_is_closed(self) -> None:
        """首个实例持锁时拒绝第二个实例，释放后允许重新启动。"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # log_dir 存储本测试隔离出的桥接运行目录。
            log_dir = Path(temp_dir)
            # first_lock 模拟首个正在运行的桥接进程持有的文件锁。
            first_lock = acquire_instance_lock(log_dir)
            try:
                with self.assertRaisesRegex(
                    InstanceAlreadyRunningError,
                    rf"已有桥接服务正在运行（pid={os.getpid()}）",
                ) as raised:
                    acquire_instance_lock(log_dir)
                self.assertEqual(raised.exception.pid, os.getpid())
            finally:
                first_lock.close()

            # restarted_lock 模拟旧进程退出后重新启动的桥接实例。
            restarted_lock = acquire_instance_lock(log_dir)
            restarted_lock.close()


if __name__ == "__main__":
    unittest.main()
