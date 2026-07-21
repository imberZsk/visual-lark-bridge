#!/usr/bin/env bash
set -euo pipefail

# SCRIPT_DIR 存放当前脚本所在目录，用来保证从任意目录启动都能找到 Python 文件。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# ENV_FILE 存储本机桥接配置文件路径，允许测试或特殊部署显式覆盖。
ENV_FILE="${LARK_BRIDGE_ENV_FILE:-$SCRIPT_DIR/.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  printf '缺少本机配置：%s\n请复制 .env.example 为 .env 后填写自己的飞书应用配置。\n' "$ENV_FILE" >&2
  exit 1
fi

# 修复源码硬编码个人 profile 导致他人部署时误连或启动失败的问题；本机 `.env` 统一供 Python 和 Node 读取。
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

exec python3 "$SCRIPT_DIR/lark_claude_bridge.py" "$@"
