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
    StateNotifierProvider<CacheRecoveryController, bool>((ref) {
  final tracker = ref.read(cacheRevalidationTrackerProvider.notifier);
  final controller = CacheRecoveryController(
    ref.watch(cacheRecoveryClientProvider),
    tracker.start,
    onRevalidationTimeout: tracker.cancel,
  );
  ref.listen<CacheRevalidationState>(cacheRevalidationTrackerProvider,
      (previous, next) {
    if ((previous?.inProgress ?? false) && !next.inProgress) {
      controller.completeRevalidation();
    }
  });
  ref.listen<CacheFallbackNotice?>(cacheFallbackNoticeProvider, (_, notice) {
    if (notice == null) {
      tracker.cancel();
      controller.completeRevalidation();
    }
  });
  return controller;
});

class CacheRecoveryController extends StateNotifier<bool> {
  CacheRecoveryController(
    this._dio,
    this._onReady, {
    void Function()? onRevalidationTimeout,
    Duration revalidationTimeout = const Duration(seconds: 10),
  })  : _onRevalidationTimeout = onRevalidationTimeout,
        _revalidationTimeout = revalidationTimeout,
        super(false);

  final Dio _dio;
  final void Function() _onReady;
  final void Function()? _onRevalidationTimeout;
  final Duration _revalidationTimeout;
  Completer<void>? _activeRecovery;
  Timer? _revalidationTimer;

  Future<void> retry() {
    if (!mounted) {
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
      if (ready && mounted && identical(_activeRecovery, recovery)) {
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
    if (mounted) {
      state = false;
    }
    if (!recovery.isCompleted) {
      recovery.complete();
    }
  }

  @override
  void dispose() {
    _revalidationTimer?.cancel();
    final recovery = _activeRecovery;
    _activeRecovery = null;
    if (recovery != null && !recovery.isCompleted) {
      recovery.complete();
    }
    super.dispose();
  }
}
