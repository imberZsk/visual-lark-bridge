#!/usr/bin/env bash

set -euo pipefail

# LEGACY_NAME_PATTERN 存储禁止重新进入源码的旧产品名称及旧入口标识。
readonly LEGACY_NAME_PATTERN='lark-ai-bridge|Lark AI Bridge|LarkAIBridge|lark_ai_bridge'
# EXCLUDED_SCRIPT 存储包含检测表达式自身、无需参与内容扫描的脚本路径。
readonly EXCLUDED_SCRIPT='scripts/check-product-naming.sh'
# contentMatches 存储已跟踪文本中的旧产品标识命中结果。
contentMatches="$(git grep -nI -E -e "$LEGACY_NAME_PATTERN" -- . ":(exclude)$EXCLUDED_SCRIPT" || true)"
# fileMatches 存储已跟踪文件名中的旧产品标识命中结果。
fileMatches="$(git ls-files | grep -Ei 'lark-ai-bridge|lark_ai_bridge' || true)"

if [[ -n "$contentMatches" || -n "$fileMatches" ]]; then
  printf '发现未完成重命名的旧产品标识：\n%s\n%s\n' "$contentMatches" "$fileMatches" >&2
  exit 1
fi

printf '产品命名检查通过。\n'
