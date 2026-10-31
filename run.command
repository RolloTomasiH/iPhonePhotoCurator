#!/bin/bash
# iPhone Photo Curator Launcher
# 双击一键启动本地整理看板并打开浏览器

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "======================================================="
echo "  📸 启动 iPhone Photo Curator 本地照片整理工具..."
echo "======================================================="

# Find python3
if [ -f "/opt/anaconda3/bin/python3" ]; then
    PYTHON_CMD="/opt/anaconda3/bin/python3"
else
    PYTHON_CMD="python3"
fi

# Start server in background
$PYTHON_CMD "$DIR/server.py" 8765 &
SERVER_PID=$!

sleep 1

# Open browser
open "http://127.0.0.1:8765"

echo "Web看板已在浏览器打开: http://127.0.0.1:8765"
echo "按 Ctrl+C 即可关闭服务 (PID: $SERVER_PID)"

wait $SERVER_PID
