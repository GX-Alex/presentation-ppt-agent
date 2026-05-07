#!/bin/bash
#
# Presentation Agent — 停止脚本
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "停止 Presentation Agent 服务..."

# 读取 PID 并杀死进程
for svc in backend frontend; do
    pid_file="$SCRIPT_DIR/logs/${svc}.pid"
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo "停止 $svc (PID: $pid)..."
            kill "$pid" 2>/dev/null || true
            sleep 1
            # 如果还在运行，强制杀死
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid" 2>/dev/null || true
            fi
        fi
        rm -f "$pid_file"
    fi
done

# 也尝试通过端口杀死
lsof -ti :8002 | xargs kill -9 2>/dev/null || true
lsof -ti :3000 | xargs kill -9 2>/dev/null || true

echo "服务已停止"
