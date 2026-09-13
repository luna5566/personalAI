import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

enum CacheFallbackReason {
  offline('offline'),
  serviceUnavailable('service_unavailable');

  const CacheFallbackReason(this.value);

  final String value;
}

class CacheFallbackNotice {
  const CacheFallbackNotice({
    required this.reason,
    required this.cachedAt,
    this.retryAfter,
  });

  final CacheFallbackReason reason;
  final DateTime cachedAt;
  final String? retryAfter;
}

final cacheFallbackNoticeProvider =
    NotifierProvider<CacheFallbackNoticeController, CacheFallbackNotice?>(
  CacheFallbackNoticeController.new,
);

class CacheFallbackNoticeController extends Notifier<CacheFallbackNotice?> {
  @override
  CacheFallbackNotice? build() => null;

  void show(CacheFallbackNotice notice) {
    state = notice;
  }

  void clear() {
    state = null;
  }
}

const cacheRevalidationGenerationExtra = 'cache_revalidation_generation';

class CacheRevalidationState {
  const CacheRevalidationState({
    this.generation = 0,
    this.inProgress = false,
    this.activeRequests = 0,
    this.registeredRequests = 0,
    this.liveResponses = 0,
    this.fallbackResponses = 0,
    this.failedResponses = 0,
  });

  final int generation;
  final bool inProgress;
  final int activeRequests;
  final int registeredRequests;
  final int liveResponses;
  final int fallbackResponses;
  final int failedResponses;

  bool get fullyRevalidated =>
      registeredRequests > 0 &&
      activeRequests == 0 &&
      liveResponses == registeredRequests &&
      fallbackResponses == 0 &&
      failedResponses == 0;

  CacheRevalidationState copyWith({
    bool? inProgress,
    int? activeRequests,
    int? registeredRequests,
    int? liveResponses,
    int? fallbackResponses,
    int? failedResponses,
  }) {
    return CacheRevalidationState(
      generation: generation,
      inProgress: inProgress ?? this.inProgress,
      activeRequests: activeRequests ?? this.activeRequests,
      registeredRequests: registeredRequests ?? this.registeredRequests,
      liveResponses: liveResponses ?? this.liveResponses,
      fallbackResponses: fallbackResponses ?? this.fallbackResponses,
      failedResponses: failedResponses ?? this.failedResponses,
    );
  }
}

final cacheRevalidationTrackerProvider =
    NotifierProvider<CacheRevalidationTracker, CacheRevalidationState>(
  CacheRevalidationTracker.new,
);

final cacheRevalidationProvider = Provider<int>((ref) {
  return ref.watch(cacheRevalidationTrackerProvider).generation;
});

class CacheRevalidationTracker extends Notifier<CacheRevalidationState> {
  CacheRevalidationTracker({
    void Function()? onFullyRevalidated,
    this._settleDelay = const Duration(milliseconds: 100),
  })  : _ctorOnFullyRevalidated = onFullyRevalidated;

  // 直连构造（测试）时注入回调；挂在 provider 上时走默认实现。
  final void Function()? _ctorOnFullyRevalidated;
  final Duration _settleDelay;
  Timer? _settleTimer;
  bool _disposed = false;

  int start() {
    _settleTimer?.cancel();
    state = CacheRevalidationState(
      generation: state.generation + 1,
      inProgress: true,
    );
    _scheduleSettlement();
    return state.generation;
  }

  int? requestStarted() {
    if (!state.inProgress) {
      return null;
    }
    _settleTimer?.cancel();
    _settleTimer = null;
    state = state.copyWith(
      activeRequests: state.activeRequests + 1,
      registeredRequests: state.registeredRequests + 1,
    );
    return state.generation;
  }

  void requestSucceeded(int? generation) {
    _settleRequest(
      generation,
      liveResponses: state.liveResponses + 1,
    );
  }

  void requestUsedFallback(int? generation) {
    _settleRequest(
      generation,
      fallbackResponses: state.fallbackResponses + 1,
    );
  }

  void requestFailed(int? generation) {
    _settleRequest(
      generation,
      failedResponses: state.failedResponses + 1,
    );
  }

  void cancel() {
    if (!state.inProgress) {
      return;
    }
    _settleTimer?.cancel();
    _settleTimer = null;
    state = state.copyWith(inProgress: false, activeRequests: 0);
  }

  void _settleRequest(
    int? generation, {
    int? liveResponses,
    int? fallbackResponses,
    int? failedResponses,
  }) {
    if (generation == null ||
        !state.inProgress ||
        generation != state.generation ||
        state.activeRequests == 0) {
      return;
    }
    state = state.copyWith(
      activeRequests: state.activeRequests - 1,
      liveResponses: liveResponses,
      fallbackResponses: fallbackResponses,
      failedResponses: failedResponses,
    );
    if (state.activeRequests == 0) {
      _scheduleSettlement();
    }
  }

  @override
  CacheRevalidationState build() {
    ref.onDispose(() {
      _disposed = true;
      _settleTimer?.cancel();
    });
    return const CacheRevalidationState();
  }

  void _notifyFullyRevalidated() {
    final override = _ctorOnFullyRevalidated;
    if (override != null) {
      override();
      return;
    }
    ref.read(cacheFallbackNoticeProvider.notifier).clear();
  }

  void _scheduleSettlement() {
    _settleTimer?.cancel();
    _settleTimer = Timer(_settleDelay, () {
      if (_disposed || !state.inProgress || state.activeRequests != 0) {
        return;
      }
      final fullyRevalidated = state.fullyRevalidated;
      state = state.copyWith(inProgress: false);
      if (fullyRevalidated) {
        _notifyFullyRevalidated();
      }
    });
  }
}
