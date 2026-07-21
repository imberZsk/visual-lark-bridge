#!/usr/bin/env bash
set -euo pipefail

# SOURCE_DIR 存储项目源码目录，安装时从这里复制最新桥接程序。
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# SOURCE_ENV_FILE 存储仅在本机存在的桥接配置，安装时复制到运行目录但绝不提交 Git。
SOURCE_ENV_FILE="$SOURCE_DIR/.env"
# SERVICE_LABEL 存储 launchd 服务的唯一标识。
SERVICE_LABEL="com.imber.lark-claude-bridge"
# INSTALL_DIR 存储后台服务的运行副本，避开 macOS 对 Desktop 的隐私限制。
INSTALL_DIR="$HOME/Library/Application Support/lark-claude-bridge"
# LAUNCH_AGENT_DIR 存储当前用户的 LaunchAgent 配置目录。
LAUNCH_AGENT_DIR="$HOME/Library/LaunchAgents"
# PLIST_PATH 存储本服务的 LaunchAgent 配置文件路径。
PLIST_PATH="$LAUNCH_AGENT_DIR/$SERVICE_LABEL.plist"
# USER_DOMAIN 存储当前登录用户对应的 launchd 域。
USER_DOMAIN="gui/$(id -u)"

if [[ ! -f "$SOURCE_ENV_FILE" ]]; then
  printf '缺少本机配置：%s\n请复制 .env.example 为 .env 后填写自己的飞书应用配置。\n' "$SOURCE_ENV_FILE" >&2
  exit 1
fi

# 修复个人 App ID 被写入安装脚本且无法安全开源的问题；忽略提交的本机 `.env` 提供部署所需配置。
set -a
# shellcheck disable=SC1090
source "$SOURCE_ENV_FILE"
set +a

if [[ -z "${LARK_PROFILE:-}" || -z "${LARK_APP_ID:-}" ]]; then
  printf '.env 必须配置 LARK_PROFILE 和 LARK_APP_ID。\n' >&2
  exit 1
fi

# require_command 校验后台运行所需命令是否可用；第一个参数是命令名。
require_command() {
  # command_name 存储待检查的命令名称。
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf '缺少命令：%s\n' "$command_name" >&2
    exit 1
  fi
}

require_command python3
require_command claude
require_command lark-cli
require_command node
require_command npm

# bootstrap_launch_agent 加载用户服务；第一个参数是 launchd 用户域，第二个参数是 plist 路径。
bootstrap_launch_agent() {
  # user_domain 存储要加载服务的 launchd 用户域。
  local user_domain="$1"
  # plist_path 存储要加载的 LaunchAgent 配置文件路径。
  local plist_path="$2"
  # attempt 存储当前加载尝试次数。
  local attempt
  for attempt in 1 2 3; do
    if launchctl bootstrap "$user_domain" "$plist_path"; then
      return 0
    fi
    # bootout 返回后 launchd 偶尔仍在清理旧实例，短暂等待后重试可避开系统竞态。
    if [[ "$attempt" -lt 3 ]]; then
      sleep 1
    fi
  done
  return 1
}

# PYTHON_BIN 存储 launchd 直接调用的 Python 解释器绝对路径。
PYTHON_BIN="$(command -v python3)"
# CLAUDE_BIN_DIR 存储 claude 命令所在目录，供后台 PATH 使用。
CLAUDE_BIN_DIR="$(dirname "$(command -v claude)")"
# LARK_CLI_BIN_DIR 存储 lark-cli 命令所在目录，供后台 PATH 使用。
LARK_CLI_BIN_DIR="$(dirname "$(command -v lark-cli)")"
# PYTHON_BIN_DIR 存储 Python 解释器所在目录，供后台 PATH 使用。
PYTHON_BIN_DIR="$(dirname "$PYTHON_BIN")"
# SERVICE_PATH 存储后台进程使用的完整 PATH。
SERVICE_PATH="$CLAUDE_BIN_DIR:$LARK_CLI_BIN_DIR:$PYTHON_BIN_DIR:/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

mkdir -p "$INSTALL_DIR/logs" "$INSTALL_DIR/claude-workspace" "$LAUNCH_AGENT_DIR"
install -m 0755 "$SOURCE_DIR/lark_claude_bridge.py" "$INSTALL_DIR/lark_claude_bridge.py"
install -m 0755 "$SOURCE_DIR/lark_event_gateway.cjs" "$INSTALL_DIR/lark_event_gateway.cjs"
install -m 0755 "$SOURCE_DIR/run.sh" "$INSTALL_DIR/run.sh"
install -m 0600 "$SOURCE_ENV_FILE" "$INSTALL_DIR/.env"
install -m 0644 "$SOURCE_DIR/package.json" "$INSTALL_DIR/package.json"
install -m 0644 "$SOURCE_DIR/package-lock.json" "$INSTALL_DIR/package-lock.json"
# 官方 SDK 用单条长连接同时注册消息与卡片回调，避免 lark-cli 总线漏注册后产生 200671。
npm ci --omit=dev --ignore-scripts --prefix "$INSTALL_DIR"

# 首次安装时迁移现有状态，避免切换运行目录后丢失任务列表和 Claude 工作区。
if [[ ! -e "$INSTALL_DIR/.runtime-initialized" ]]; then
  cp -R "$SOURCE_DIR/logs/." "$INSTALL_DIR/logs/" 2>/dev/null || true
  cp -R "$SOURCE_DIR/claude-workspace/." "$INSTALL_DIR/claude-workspace/" 2>/dev/null || true
  touch "$INSTALL_DIR/.runtime-initialized"
fi

# 首次安装才写入通用工作区说明，避免更新公开程序时覆盖用户维护的本机项目映射。
if [[ ! -f "$INSTALL_DIR/claude-workspace/CLAUDE.md" ]]; then
  install -m 0644 "$SOURCE_DIR/claude-workspace/CLAUDE.md" "$INSTALL_DIR/claude-workspace/CLAUDE.md"
fi

# plist 内容使用绝对路径，避免 launchd 的精简环境导致命令或工作目录无法解析。
cat >"$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$SERVICE_LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$INSTALL_DIR/run.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$INSTALL_DIR</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key>
    <string>$HOME</string>
    <key>PATH</key>
    <string>$SERVICE_PATH</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>ThrottleInterval</key>
  <integer>60</integer>
  <key>StandardOutPath</key>
  <string>$INSTALL_DIR/logs/launchd.out.log</string>
  <key>StandardErrorPath</key>
  <string>$INSTALL_DIR/logs/launchd.err.log</string>
</dict>
</plist>
PLIST

plutil -lint "$PLIST_PATH"
launchctl bootout "$USER_DOMAIN/$SERVICE_LABEL" 2>/dev/null || true
# 旧版 lark-cli 事件总线会在消费者退出后继续存活 30 秒，部署新网关前主动优雅关闭。
lark-cli event stop --app-id "$LARK_APP_ID" --force >/dev/null 2>&1 || true
# 旧 launchd 日志可能来自 Desktop 方案，重新安装时清空以便准确判断本次启动结果。
: >"$INSTALL_DIR/logs/launchd.out.log"
: >"$INSTALL_DIR/logs/launchd.err.log"
bootstrap_launch_agent "$USER_DOMAIN" "$PLIST_PATH"

printf '已安装并启动：%s\n' "$SERVICE_LABEL"
printf '运行目录：%s\n' "$INSTALL_DIR"
printf '查看状态：launchctl print %s/%s\n' "$USER_DOMAIN" "$SERVICE_LABEL"
printf '查看日志：tail -f %q\n' "$INSTALL_DIR/logs/bridge.log"
