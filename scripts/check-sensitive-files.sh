#!/usr/bin/env bash

set -euo pipefail

# BLOCKED_FILE_PATHS 存储禁止进入版本库或发布包的敏感文件路径模式。
readonly BLOCKED_FILE_PATHS=(".env" "*.pem" "*.key" "*.p12" "*.pfx" "*.mobileprovision")
# SECRET_PATTERN 存储需要在已跟踪文本中拦截的凭据特征。
readonly SECRET_PATTERN='-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9_]{20,}|LARK_APP_SECRET[[:space:]]*=[[:space:]]*[^[:space:]<][^[:space:]]*'
# LOCAL_PATH_PATTERN 存储不应进入公开源码的本机绝对路径。
readonly LOCAL_PATH_PATTERN='/Users/imber/'

# blockedPath 存储当前正在检查的敏感路径模式。
for blockedPath in "${BLOCKED_FILE_PATHS[@]}"; do
  # trackedFiles 存储匹配当前敏感路径模式的已跟踪文件。
  trackedFiles="$(git ls-files -- "$blockedPath")"
  if [[ -n "$trackedFiles" ]]; then
    printf '发现禁止发布的敏感文件：\n%s\n' "$trackedFiles" >&2
    exit 1
  fi
done

# 凭据和本机路径只检查已跟踪文本，避免扫描依赖、构建缓存与用户运行数据。
if git grep -nI -E -e "$SECRET_PATTERN|$LOCAL_PATH_PATTERN" -- . ":(exclude)scripts/check-sensitive-files.sh"; then
  printf '发现疑似凭据或本机绝对路径，请确认后再发布。\n' >&2
  exit 1
fi

printf '敏感信息检查通过。\n'
