#!/bin/sh
# 运行时注入 API_BASE_URL：重写产物中的 env.js，Flutter 启动时读取
# window.__APP_CONFIG__.API_BASE_URL。修改地址只需更新环境变量并重启容器。
set -eu

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000/api}"

cat > /usr/share/nginx/html/env.js <<EOF
window.__APP_CONFIG__ = Object.assign(window.__APP_CONFIG__ || {}, {
  API_BASE_URL: "${API_BASE_URL}"
});
EOF

echo "env.js: API_BASE_URL=${API_BASE_URL}"
