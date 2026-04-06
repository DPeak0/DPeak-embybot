# 第一阶段：安装依赖
FROM python:3.10.11-alpine AS builder

RUN apk add --no-cache --virtual .build-deps \
    gcc musl-dev openssl-dev libffi-dev jpeg-dev zlib-dev freetype-dev \
    mariadb-connector-c-dev coreutils

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN apk del --purge .build-deps && \
    rm -rf /tmp/* /root/.cache /var/cache/apk/*

# 第二阶段：运行镜像
FROM python:3.10.11-alpine

ENV TZ=Asia/Shanghai \
    DOCKER_MODE=1 \
    PYTHONUNBUFFERED=1

RUN apk add --no-cache \
    mariadb-connector-c \
    tzdata \
    jpeg \
    freetype \
    libstdc++ && \
    ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo Asia/Shanghai > /etc/timezone

WORKDIR /app

# 从builder复制已安装的Python包
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 复制项目代码（排除config.json，生产用挂载）
COPY bot/ ./bot/
COPY main.py .

ENTRYPOINT ["python3"]
CMD ["main.py"]
