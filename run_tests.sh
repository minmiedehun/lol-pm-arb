#!/usr/bin/env bash
# 全部测试：只用本地模拟服务器和合成数据，不联网
set -euo pipefail
cd "$(dirname "$0")"
echo "== recorder"; python3 recorder/test_recorder.py | tail -1
echo "== scanner";  python3 scanner/test_scan.py | grep -E "通过|不误报|恒等式错价：普通"
echo "== monitor";  python3 scanner/test_monitor.py 2>/dev/null | grep -E "通过"
echo "全部通过"
