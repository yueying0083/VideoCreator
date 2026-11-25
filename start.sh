#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="$ROOT_DIR/apps/api"
WEB_DIR="$ROOT_DIR/apps/web"

echo "=================================================="
echo "  Video Creator Studio · Google AI 全模态视频导演台"
echo "=================================================="

# 1. Check FFmpeg / FFprobe
if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "[WARN] 未检测到完整 ffmpeg/ffprobe，抽帧、裁剪与合片将受限或回退。建议安装：brew install ffmpeg"
fi

# 2. Ensure backend virtualenv & deps
if [ ! -x "$API_DIR/.venv/bin/uvicorn" ]; then
  echo "[1/2] 初始化 Python 后端虚拟环境..."
  if command -v uv >/dev/null 2>&1; then
    (cd "$API_DIR" && uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt)
  else
    (cd "$API_DIR" && python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -r requirements.txt)
  fi
fi

# 3. Ensure frontend node_modules
if [ ! -d "$WEB_DIR/node_modules" ]; then
  echo "[2/2] 安装前端依赖..."
  (cd "$WEB_DIR" && npm install)
fi

cleanup() {
  echo ""
  echo "正在停止 Video Creator Studio 服务..."
  kill ${API_PID:-} ${WEB_PID:-} 2>/dev/null || true
  wait ${API_PID:-} ${WEB_PID:-} 2>/dev/null || true
}
trap cleanup INT TERM EXIT

# 4. Launch FastAPI Backend
echo "启动 FastAPI 后端 -> http://127.0.0.1:8000"
(cd "$API_DIR" && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) &
API_PID=$!

for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

# 5. Launch Vite Frontend
echo "启动 Vite 前端 -> http://localhost:3000"
(cd "$WEB_DIR" && npm run dev) &
WEB_PID=$!

echo ""
echo "✅ 服务已启动：http://localhost:3000"
echo "💡 未配置 GEMINI_API_KEY 时将自动以 Demo 本地演示模式运行；随时可点击右上角「设置」配置与测试连通性。"
echo "按 Ctrl+C 一键停止前后端服务。"
echo ""

wait
