#!/bin/bash
# claude.ai/code 云端会话开始时装依赖（由 .claude/settings.json 的 SessionStart hook 调用）。
# 本地不执行：CLAUDE_CODE_REMOTE 只在云端会话里是 true。

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

# 依赖都已装好就跳过（会话从闲置恢复时常见）
if python3 -c "import numpy, scipy, zstandard, websockets" 2>/dev/null; then
  exit 0
fi

python3 -m pip install -q -r requirements.txt \
  || python3 -m pip install -q --break-system-packages -r requirements.txt \
  || echo "依赖没装上：检查环境的 Network access 是否包含 PyPI（Custom 时要勾选 Also include default list of common package managers）" >&2

# 装依赖失败也不阻止会话启动
exit 0
