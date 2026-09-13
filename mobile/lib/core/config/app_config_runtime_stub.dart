/// 非 Web 平台的运行时配置占位：没有 `window.__APP_CONFIG__`，
/// 全部回退到编译期 `--dart-define` 或默认值。
String? appRuntimeConfigValue(String key) => null;
