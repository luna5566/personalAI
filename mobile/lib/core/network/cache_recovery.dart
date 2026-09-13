import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/app_config.dart';
import 'cache_state.dart';

final cacheRecoveryClientProvider = Provider<Dio>((ref) {
  final dio = Dio(
    BaseOptions(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 10),
    ),
  );
  ref.onDispose(dio.close);
  return dio;
});

final cacheRecoveryControllerProvider =
    NotifierProvider<CacheRecoveryController, bool>(
  CacheRecoveryController.new,
);

class CacheRecoveryController extends Notifier<bool> {
  CacheRecoveryController({
    Dio? dio,
    void Function()? onReady,
    void Function()? onRevalidationTimeout,
    this._revalidationTimeout = const Duration(seconds: 10),
  })  : _ctorDio = dio,
        _ctorOnReady = onReady,
        _ctorOnRevalidationTimeout = onRevalidationTimeout;

  // 直连构造（测试）时注入依赖；挂在 provider 上时从 ref 解析。
  final Dio? _ctorDio;
  final void Function()? _ctorOnReady;
  final void Function()? _ctorOnRevalidationTimeout;
  final Duration _revalidationTimeout;
  late Dio _dio;
  late void Function() _onReady;
  late void Function()? _onRevalidationTimeout;
  Completer<void>? _activeRecovery;
  Timer? _revalidationTimer;
  bool _disposed = false;

  @override
  bool build() {
    _dio = _ctorDio ?? ref.watch(cacheRecoveryClientProvider);
    _onReady =
        _ctorOnReady ?? () => ref.read(cacheRevalidationTrackerProvider.notifier).start();
    _onRevalidationTimeout = _ctorOnRevalidationTimeout ??
        () => ref.read(cacheRevalidationTrackerProvider.notifier).cancel();
    ref.listen<CacheRevalidationState>(cacheRevalidationTrackerProvider,
        (previous, next) {
      if ((previous?.inProgress ?? false) && !next.inProgress) {
        completeRevalidation();
      }
    });
    ref.listen<CacheFallbackNotice?>(cacheFallbackNoticeProvider, (_, notice) {
      if (notice == null) {
        ref.read(cacheRevalidationTrackerProvider.notifier).cancel();
        completeRevalidation();
      }
    });
    ref.onDispose(_cleanup);
    return false;
  }

  Future<void> retry() {
    if (_disposed) {
      return Future<void>.value();
    }
    final activeRecovery = _activeRecovery;
    if (activeRecovery != null) {
      return activeRecovery.future;
    }
    final recovery = Completer<void>();
    _activeRecovery = recovery;
    state = true;
    unawaited(_probe(recovery));
    return recovery.future;
  }

  void completeRevalidation() {
    final recovery = _activeRecovery;
    if (recovery != null) {
      _finish(recovery);
    }
  }

  Future<void> _probe(Completer<void> recovery) async {
    var ready = false;
    try {
      final response = await _dio.get<dynamic>('/health/ready');
      final data = response.data;
      ready = response.statusCode == 200 &&
          data is Map &&
          data['status'] == 'ready';
      if (ready && !_disposed && identical(_activeRecovery, recovery)) {
        _onReady();
        if (identical(_activeRecovery, recovery)) {
          _revalidationTimer = Timer(
            _revalidationTimeout,
            () {
              _onRevalidationTimeout?.call();
              _finish(recovery);
            },
          );
        }
      }
    } catch (_) {
      // A failed probe keeps the existing cache fallback notice visible.
    } finally {
      if (!ready) {
        _finish(recovery);
      }
    }
  }

  void _finish(Completer<void> recovery) {
    if (!identical(_activeRecovery, recovery)) {
      return;
    }
    _revalidationTimer?.cancel();
    _revalidationTimer = null;
    _activeRecovery = null;
    if (!_disposed) {
      state = false;
    }
    if (!recovery.isCompleted) {
      recovery.complete();
    }
  }

  void _cleanup() {
    _disposed = true;
    _revalidationTimer?.cancel();
    final recovery = _activeRecovery;
    _activeRecovery = null;
    if (recovery != null && !recovery.isCompleted) {
      recovery.complete();
    }
  }
}
