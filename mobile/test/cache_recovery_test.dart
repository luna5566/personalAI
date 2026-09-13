import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/core/network/cache_recovery.dart';
import 'package:personal_ai_mobile/core/network/cache_state.dart';

void main() {
  test('deduplicates probes and waits for live data revalidation', () async {
    final adapter = ControlledRecoveryAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    dio.httpClientAdapter = adapter;
    addTearDown(dio.close);
    final container = ProviderContainer(
      overrides: [cacheRecoveryClientProvider.overrideWithValue(dio)],
    );
    addTearDown(container.dispose);
    container.read(cacheFallbackNoticeProvider.notifier).show(
          CacheFallbackNotice(
            reason: CacheFallbackReason.offline,
            cachedAt: DateTime.utc(2026, 7, 17, 3, 4),
          ),
        );
    final controller = container.read(cacheRecoveryControllerProvider.notifier);

    final firstProbe = controller.retry();
    final secondProbe = controller.retry();
    await _waitForRequest(adapter);

    expect(container.read(cacheRecoveryControllerProvider), isTrue);
    expect(adapter.callCount, 1);
    expect(adapter.requestedPath, '/health/ready');

    adapter.respond(statusCode: 200, body: '{"status":"ready"}');
    await _waitForRevalidation(container);

    expect(container.read(cacheRevalidationProvider), 1);
    expect(container.read(cacheRecoveryControllerProvider), isTrue);
    expect(container.read(cacheFallbackNoticeProvider), isNotNull);

    container.read(cacheFallbackNoticeProvider.notifier).clear();
    await Future.wait([firstProbe, secondProbe]);

    expect(container.read(cacheRecoveryControllerProvider), isFalse);
  });

  test('keeps the notice when the readiness probe fails', () async {
    final adapter = ControlledRecoveryAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    dio.httpClientAdapter = adapter;
    addTearDown(dio.close);
    final container = ProviderContainer(
      overrides: [cacheRecoveryClientProvider.overrideWithValue(dio)],
    );
    addTearDown(container.dispose);
    final notice = CacheFallbackNotice(
      reason: CacheFallbackReason.serviceUnavailable,
      cachedAt: DateTime.utc(2026, 7, 17, 3, 4),
      retryAfter: '5',
    );
    container.read(cacheFallbackNoticeProvider.notifier).show(notice);
    final controller = container.read(cacheRecoveryControllerProvider.notifier);

    final probe = controller.retry();
    await _waitForRequest(adapter);
    adapter.respond(statusCode: 503, body: '{"status":"not_ready"}');
    await probe;

    expect(container.read(cacheRecoveryControllerProvider), isFalse);
    expect(container.read(cacheRevalidationProvider), 0);
    expect(container.read(cacheFallbackNoticeProvider), same(notice));
  });

  test('ends loading without clearing data when revalidation times out',
      () async {
    final adapter = ControlledRecoveryAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    dio.httpClientAdapter = adapter;
    addTearDown(dio.close);
    var revalidationCount = 0;
    final container = ProviderContainer(
      overrides: [
        cacheRecoveryClientProvider.overrideWithValue(dio),
        cacheRevalidationTrackerProvider.overrideWith(
          () => _CountingRevalidationTracker(() => revalidationCount += 1),
        ),
        cacheRecoveryControllerProvider.overrideWith(
          () => _ZeroTimeoutRecoveryController(),
        ),
      ],
    );
    addTearDown(container.dispose);

    final controller = container.read(cacheRecoveryControllerProvider.notifier);
    final recovery = controller.retry();
    await _waitForRequest(adapter);
    adapter.respond(statusCode: 200, body: '{"status":"ready"}');
    await recovery;

    expect(revalidationCount, 1);
    expect(container.read(cacheRecoveryControllerProvider), isFalse);
  });
}

Future<void> _waitForRevalidation(ProviderContainer container) async {
  for (var attempt = 0; attempt < 20; attempt += 1) {
    if (container.read(cacheRevalidationProvider) > 0) {
      return;
    }
    await Future<void>.delayed(Duration.zero);
  }
  fail('Cache revalidation was not triggered.');
}

Future<void> _waitForRequest(ControlledRecoveryAdapter adapter) async {
  for (var attempt = 0; attempt < 20; attempt += 1) {
    if (adapter.callCount > 0) {
      return;
    }
    await Future<void>.delayed(Duration.zero);
  }
  fail('The readiness probe was not sent.');
}

class _ZeroTimeoutRecoveryController extends CacheRecoveryController {
  _ZeroTimeoutRecoveryController() : super(revalidationTimeout: Duration.zero);
}

class _CountingRevalidationTracker extends CacheRevalidationTracker {
  _CountingRevalidationTracker(void Function() onStart)
      : _onStart = onStart,
        super(settleDelay: Duration.zero);

  final void Function() _onStart;

  @override
  int start() {
    _onStart();
    return super.start();
  }
}

class ControlledRecoveryAdapter implements HttpClientAdapter {
  final Completer<ResponseBody> _response = Completer<ResponseBody>();

  int callCount = 0;
  String? requestedPath;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) {
    callCount += 1;
    requestedPath = options.path;
    return _response.future;
  }

  void respond({required int statusCode, required String body}) {
    _response.complete(
      ResponseBody.fromString(
        body,
        statusCode,
        headers: {
          Headers.contentTypeHeader: ['application/json'],
        },
      ),
    );
  }

  @override
  void close({bool force = false}) {}
}
