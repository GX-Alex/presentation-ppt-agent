FROM python:3.12-slim

WORKDIR /app

# 系统依赖（Playwright 浏览器 + 文档解析）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Playwright Chromium（用于 PDF/PPTX 导出）
RUN playwright install chromium --with-deps

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p data/uploads data/exports data/thumbnails

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

EXPOSE 8000

# 生产环境使用多 worker（开发环境由 docker-compose 覆盖）
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
