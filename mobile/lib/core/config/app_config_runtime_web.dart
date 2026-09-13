import 'dart:js_interop';
import 'dart:js_interop_unsafe';

/// 读取容器启动时写入 `env.js` 的运行时配置（`window.__APP_CONFIG__`）。
String? appRuntimeConfigValue(String key) {
  final config = _appConfig;
  if (config == null) {
    return null;
  }
  final value = config.getProperty(key.toJS);
  if (value == null || !value.isA<JSString>()) {
    return null;
  }
  return (value as JSString).toDart;
}

@JS('__APP_CONFIG__')
external JSObject? get _appConfig;
