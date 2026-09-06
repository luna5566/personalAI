# syntax=docker/dockerfile:1
# 构建参数 API_BASE_URL 必须在构建期注入，例如：
#   docker build --build-arg API_BASE_URL=http://127.0.0.1:8000/api -t personal-ai-web .
FROM ghcr.io/cirruslabs/flutter:3.35.0 AS build

ARG API_BASE_URL=http://127.0.0.1:8000/api
WORKDIR /src

COPY pubspec.yaml pubspec.lock ./
RUN flutter pub get

COPY . .
RUN flutter build web --release --dart-define=API_BASE_URL=${API_BASE_URL}

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

EXPOSE 80
