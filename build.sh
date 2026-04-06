#!/bin/bash
set -e

REGISTRY="crpi-euihr92xl17baj83.cn-shenzhen.personal.cr.aliyuncs.com"
IMAGE="${REGISTRY}/dpeak/embyboos"
ACR_USER="c305093325"
ACR_PASS="1354547633a"

# 取 git commit 短hash作为版本标签
GIT_TAG=$(git -C "$(dirname "$0")" rev-parse --short HEAD 2>/dev/null || echo "manual")
DATE_TAG=$(date +%Y%m%d)

echo "====== dpeak embyboss 构建推送 ======"
echo "版本: ${DATE_TAG}-${GIT_TAG}"
echo "仓库: ${IMAGE}"
echo ""

# 1. 先做git快照
cd "$(dirname "$0")"
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "[1/4] 提交未保存变更..."
    git add -A
    git commit -m "build: release ${DATE_TAG}-${GIT_TAG}"
else
    echo "[1/4] 工作区干净，跳过提交"
fi

# 2. 登录ACR
echo "[2/4] 登录阿里云ACR..."
echo "${ACR_PASS}" | docker login --username="${ACR_USER}" --password-stdin "${REGISTRY}"

# 3. 构建镜像
echo "[3/4] 构建镜像..."
docker build \
    --platform linux/amd64 \
    -t "${IMAGE}:${DATE_TAG}-${GIT_TAG}" \
    -t "${IMAGE}:latest" \
    -f Dockerfile \
    .

# 4. 推送
echo "[4/4] 推送到ACR..."
docker push "${IMAGE}:${DATE_TAG}-${GIT_TAG}"
docker push "${IMAGE}:latest"

echo ""
echo "====== 完成 ======"
echo "镜像: ${IMAGE}:latest"
echo "版本: ${IMAGE}:${DATE_TAG}-${GIT_TAG}"
echo ""
echo "生产服务器更新命令："
echo "  bash /dpeak/update.sh"
