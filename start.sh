#!/bin/bash
#
# General Agent — 一键启动脚本
# 同时启动前端 (3000) 和后端 (8002)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
BACKEND_PORT=8002
FRONTEND_PORT=3000
BACKEND_URL="http://localhost:$BACKEND_PORT"
MAX_WAIT=60

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[启动]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[警告]${NC} $1"; }
log_error() { echo -e "${RED}[错误]${NC} $1"; }

# 检查端口是否被占用
check_port() {
    local port=$1
    local name=$2
    if lsof -i :$port > /dev/null 2>&1; then
        log_warn "端口 $port ($name) 已被占用"
        log_warn "请先关闭现有服务: lsof -ti :$port | xargs kill -9"
        return 1
    fi
    return 0
}

# 等待服务就绪
wait_for_service() {
    local url=$1
    local name=$2
    local waited=0
    log_info "等待 $name 就绪..."

    while [ $waited -lt $MAX_WAIT ]; do
        if curl -s --max-time 2 "$url/api/health" > /dev/null 2>&1; then
            log_ok "$name 已就绪"
            return 0
        fi
        sleep 1
        ((waited++))
        if [ $((waited % 10)) -eq 0 ]; then
            log_info "已等待 ${waited}s，仍在等待 $name..."
        fi
    done

    log_error "$name 启动超时 (${MAX_WAIT}s)"
    return 1
}

# 主流程
main() {
    echo ""
    echo "=========================================="
    echo "  General Agent 启动脚本"
    echo "=========================================="
    echo ""

    # 1. 检查端口
    log_info "检查端口可用性..."
    check_port $BACKEND_PORT "后端" || exit 1
    check_port $FRONTEND_PORT "前端" || exit 1
    log_ok "端口检查通过"

    # 2. 检查依赖
    log_info "检查 Python 虚拟环境..."
    if [ ! -d "$BACKEND_DIR/.venv" ]; then
        log_warn "后端虚拟环境不存在，正在创建..."
        python3 -m venv "$BACKEND_DIR/.venv"
        source "$BACKEND_DIR/.venv/bin/activate"
        pip install -q -r "$BACKEND_DIR/requirements.txt"
        log_ok "虚拟环境已创建"
    else
        log_ok "后端虚拟环境已存在"
    fi

    log_info "检查 Node.js 依赖..."
    if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
        log_warn "前端 node_modules 不存在，正在安装..."
        (cd "$FRONTEND_DIR" && npm install)
        log_ok "依赖已安装"
    else
        log_ok "前端依赖已存在"
    fi

    # 3. 启动后端
    echo ""
    log_info "启动后端服务 (端口 $BACKEND_PORT)..."
    source "$BACKEND_DIR/.venv/bin/activate"
    export ENV=production  # 避免 uvicorn reload 在 macOS 上的兼容性问题
    cd "$BACKEND_DIR"
    nohup python3 main.py > "$SCRIPT_DIR/logs/backend.log" 2>&1 &
    BACKEND_PID=$!
    log_info "后端进程 PID: $BACKEND_PID"
    echo "$BACKEND_PID" > "$SCRIPT_DIR/logs/backend.pid"

    # 4. 启动前端
    echo ""
    log_info "启动前端服务 (端口 $FRONTEND_PORT)..."
    cd "$FRONTEND_DIR"
    nohup npm run dev > "$SCRIPT_DIR/logs/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    log_info "前端进程 PID: $FRONTEND_PID"
    echo "$FRONTEND_PID" > "$SCRIPT_DIR/logs/frontend.pid"

    # 5. 等待服务就绪
    echo ""
    wait_for_service "$BACKEND_URL" "后端 API"

    # 6. 显示结果
    echo ""
    echo "=========================================="
    echo -e "  ${GREEN}服务已就绪${NC}"
    echo "=========================================="
    echo ""
    echo -e "  前端: ${BLUE}http://localhost:$FRONTEND_PORT${NC}"
    echo -e "  后端: ${BLUE}$BACKEND_URL${NC}"
    echo ""
    echo "  日志文件:"
    echo "    后端: $SCRIPT_DIR/logs/backend.log"
    echo "    前端: $SCRIPT_DIR/logs/frontend.log"
    echo ""
    echo "  停止服务:"
    echo "    ./stop.sh"
    echo ""

    # 7. 打开浏览器（可选）
    if command -v open > /dev/null 2>&1; then
        read -p "是否打开浏览器? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            open "http://localhost:$FRONTEND_PORT"
        fi
    fi
}

# 创建日志目录
mkdir -p "$SCRIPT_DIR/logs"

main "$@"
