FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# 安装 git
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv
RUN pip install --no-cache-dir uv

# 先复制依赖声明文件，利用 Docker 缓存
COPY pyproject.toml uv.lock /app/

# 安装依赖，不安装当前项目本身
RUN uv sync --frozen --no-dev --no-install-project

# 再复制项目源码
COPY . /app

CMD ["python", "main.py"]