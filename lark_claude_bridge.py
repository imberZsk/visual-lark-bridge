#!/usr/bin/env python3
"""旧文件名兼容入口；新安装应使用 lark_ai_bridge.py。"""

from lark_ai_bridge import *
from lark_ai_bridge import main


if __name__ == "__main__":
    raise SystemExit(main())
