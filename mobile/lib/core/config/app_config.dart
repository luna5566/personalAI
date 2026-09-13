import 'app_config_runtime_stub.dart'
    if (dart.library.js_interop) 'app_config_runtime_web.dart';

/// 应用配置。
///
/// Web 端支持运行时注入：容器启动时把 `API_BASE_URL` 写入 `env.js`，
/// 改地址只需改环境变量并重启 `web` 容器，无需重建镜像。
/// 优先级：运行时 `window.__APP_CONFIG__`（仅容器场景存在）>
/// 编译期 `--dart-define` > 本地开发默认值。
class AppConfig {
  static String get apiBaseUrl {
    final runtime = appRuntimeConfigValue('API_BASE_URL');
    if (runtime != null && runtime.isNotEmpty) {
      return runtime;
    }
    return const String.fromEnvironment(
      'API_BASE_URL',
      defaultValue: 'http://127.0.0.1:8000/api',
    );
  }
}
