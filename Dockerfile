# 使用 Python 3.12 官方镜像作为基础镜像
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# 复制项目配置文件（用于依赖安装）
COPY pyproject.toml ./

# 复制源代码目录（pip install -e . 需要完整的项目结构）
COPY src/ ./src/

# 复制构建元数据需要的文件（pyproject 指定了 readme = "README.md"）
COPY README.md ./
COPY LICENSE ./

# 安装 Python 运行时依赖（从 pyproject.toml）
# 先安装 httpx 以确保版本兼容性（nonebot2 2.0+ 需要 httpx>=0.24.0 以支持 proxy 参数）
RUN pip install --no-cache-dir "httpx>=0.24.0" && \
    pip install --no-cache-dir -e .

# 复制应用入口文件
COPY bot.py .

# 创建数据目录（用于 SQLite 数据库持久化）
RUN mkdir -p /app/data && chmod 755 /app/data

# 暴露端口（NoneBot 默认使用 8080，但可以通过环境变量配置）
# Zeabur 会自动检测端口，也可以设置 PORT 环境变量
EXPOSE 8080

# 启动应用
CMD ["python", "bot.py"]

