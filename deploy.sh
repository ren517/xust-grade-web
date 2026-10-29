#!/usr/bin/env bash
set -e

# ============================================================
# 西科大教务助手 — 部署/启动脚本
# 用法：
#   bash deploy.sh            # 本地 http 调试（HTTPS_ONLY=0）
#   bash deploy.sh --https    # 公网 HTTPS 部署（Cookie 仅 HTTPS 下发）
# 前置：
#   - 已把整个项目目录传到服务器（含 config.py 与 key.key，二者被 .gitignore 排除，
#     不要用 git clone 后直接跑，否则会缺这两个文件）
#   - Ubuntu 若没有 venv： sudo apt install -y python3-venv python3-pip
# ============================================================

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

echo "==> 工作目录: $APP_DIR"

# ---------- 1. 环境检查 ----------
PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "✗ 未找到 python3，请先安装"; exit 1; }
echo "==> $($PY --version 2>&1)"

# ---------- 2. 关键文件检查（被 gitignore，必须随包传） ----------
for f in app.py config.py key.key requirements.txt; do
  if [ ! -f "$f" ]; then
    echo "✗ 缺少关键文件: $f"
    echo "  config.py / key.key 已被 .gitignore 排除，请用 scp 整包传输项目，不要 git clone"
    exit 1
  fi
done
echo "==> 关键文件齐全 (app.py / config.py / key.key / requirements.txt)"

# ---------- 3. 虚拟环境 + 依赖 ----------
if [ ! -d venv ]; then
  echo "==> 创建虚拟环境 venv ..."
  if ! $PY -m venv venv 2>/dev/null; then
    echo "✗ venv 创建失败，请先执行: sudo apt install -y python3-venv python3-pip"
    exit 1
  fi
fi
VENV_PIP="venv/bin/pip"
VENV_PY="venv/bin/python"
"$VENV_PIP" install -q --upgrade pip
echo "==> 安装依赖 (这可能要一两分钟，pandas 较大) ..."
"$VENV_PIP" install -q -r requirements.txt
echo "==> 依赖安装完成"

# ---------- 4. HTTPS 开关 ----------
HTTPS_ONLY="${HTTPS_ONLY:-0}"
[ "$1" = "--https" ] && HTTPS_ONLY=1
export HTTPS_ONLY
echo "==> HTTPS_ONLY=$HTTPS_ONLY  (1=仅HTTPS下发Cookie, 配nginx反代时必须开启)"

# ---------- 5. 启动（后台 + 日志） ----------
HOST=127.0.0.1
PORT=8000
LOG="$APP_DIR/server.log"

# 若已有同端口进程则先停（按 uvicorn 进程名匹配，谨慎）
if pgrep -f "uvicorn app:app" >/dev/null 2>&1; then
  echo "==> 检测到已有 uvicorn 进程，先停止"
  pkill -f "uvicorn app:app" || true
  sleep 1
fi

nohup "$VENV_PY" -m uvicorn app:app --host "$HOST" --port "$PORT" > "$LOG" 2>&1 &
echo "==> 已启动 uvicorn (PID $!)"
echo "==> 访问地址: http://$HOST:$PORT"
echo "==> 查看日志: tail -f $LOG"
echo "==> 停止服务: pkill -f 'uvicorn app:app'"
