// 运行时配置占位。本地 `flutter run` 时保持为空对象，配置回退到
// `--dart-define`；Web 容器启动时由 /docker-entrypoint.d 脚本重写本文件，
// 注入 `API_BASE_URL`，因此改地址无需重建镜像。
window.__APP_CONFIG__ = window.__APP_CONFIG__ || {};
