# syntax=docker/dockerfile:1
# Web 静态产物镜像。API_BASE_URL 在运行期由环境变量注入（写入 env.js），
# 无需为不同 API 地址重建镜像；也可以用 --build-arg 在构建期固定：
#   docker build -t personal-ai-web .
#   docker run -e API_BASE_URL=https://api.example.com/api -p 5600:80 personal-ai-web
# 与本地 Flutter 版本保持一致（Dart 3.12）；Riverpod 3 要求 Dart >= 3.12。
# cirruslabs 镜像自 2026-05 起停止更新，3.44.0 为其最终版本之一，
# 后续升级需自建镜像或更换基础镜像（见 docs/project-decisions.md 决策 143）。
FROM ghcr.io/cirruslabs/flutter:3.44.0 AS build

WORKDIR /src

COPY pubspec.yaml pubspec.lock ./
RUN flutter pub get

COPY . .
RUN flutter build web --release

FROM nginx:1.27-alpine

RUN printf 'server {\n\
    listen 80;\n\
    server_name _;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
\n\
    gzip on;\n\
    gzip_comp_level 6;\n\
    gzip_min_length 1024;\n\
    gzip_vary on;\n\
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;\n\
\n\
    location /assets/ {\n\
        expires 30d;\n\
        add_header Cache-Control "public, immutable";\n\
    }\n\
\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

COPY --from=build /src/build/web /usr/share/nginx/html
COPY docker/90-inject-env-config.sh /docker-entrypoint.d/90-inject-env-config.sh
RUN chmod +x /docker-entrypoint.d/90-inject-env-config.sh

EXPOSE 80
