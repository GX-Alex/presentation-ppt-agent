#!/bin/bash
#
# Presentation Agent — 开发模式启动脚本（支持热重载）
# 使用 uvicorn CLI 方式启动，可以检测代码变更并自动重载
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
BACKEND_PORT=8002
FRONTEND_PORT=3000
BACKEND_URL="http://localhost:$BACKEND_PORT"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[dev]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[警告]${NC} $1"; }

# 检查端口
check_port() {
    local port=$1
    local name=$2
    if lsof -i :$port > /dev/null 2>&1; then
        log_warn "端口 $port ($name) 已被占用"
        return 1
    fi
    return 0
}

echo ""
echo "=========================================="
echo "  Presentation Agent — 开发模式"
echo "=========================================="
echo ""

# 检查端口
check_port $BACKEND_PORT "后端" || exit 1
check_port $FRONTEND_PORT "前端" || exit 1

# 检查 venv
if [ ! -d "$BACKEND_DIR/.venv" ]; then
    log_warn "后端虚拟环境不存在，请先运行 ./start.sh"
    exit 1
fi

# 创建日志目录
mkdir -p "$SCRIPT_DIR/logs"

# 启动后端（使用 uvicorn CLI，支持热重载）
log_info "启动后端 (热重载模式)..."
source "$BACKEND_DIR/.venv/bin/activate"
cd "$BACKEND_DIR"

# 使用 uvicorn CLI 直接启动，这样可以正确处理 reload
# 注意：不能使用 python3 main.py 因为 uvicorn reload 在 macOS + Python 3.13 上有兼容性问题
nohup uvicorn main:app \
    --host 0.0.0.0 \
    --port $BACKEND_PORT \
    --reload \
    --reload-dir app \
    --reload-exclude "*.db" \
    --reload-exclude "*.db-*" \
    > "$SCRIPT_DIR/logs/backend-dev.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$SCRIPT_DIR/logs/backend.pid"
log_ok "后端进程 PID: $BACKEND_PID"

# 等待后端启动
log_info "等待后端启动..."
for i in {1..30}; do
    if curl -s --max-time 2 "$BACKEND_URL/api/health" > /dev/null 2>&1; then
        log_ok "后端已就绪"
        break
    fi
    sleep 1
done

# 启动前端
log_info "启动前端..."
cd "$FRONTEND_DIR"
nohup npm run dev > "$SCRIPT_DIR/logs/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$SCRIPT_DIR/logs/frontend.pid"
log_ok "前端进程 PID: $FRONTEND_PID"

echo ""
echo "=========================================="
echo -e "  ${GREEN}开发服务已启动${NC}"
echo "=========================================="
echo ""
echo -e "  前端: ${BLUE}http://localhost:$FRONTEND_PORT${NC}"
echo -e "  后端: ${BLUE}$BACKEND_URL${NC}"
echo ""
echo "  日志文件:"
echo "    后端: $SCRIPT_DIR/logs/backend-dev.log"
echo "    前端: $SCRIPT_DIR/logs/frontend.log"
echo ""
echo "  按 Ctrl+C 停止服务，或运行 ./stop.sh"
echo ""
