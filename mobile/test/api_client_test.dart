import 'dart:async';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/core/network/api_client.dart';
import 'package:personal_ai_mobile/core/network/cache_state.dart';
import 'package:personal_ai_mobile/core/storage/api_cache.dart';
import 'package:personal_ai_mobile/core/storage/token_storage.dart';

void main() {
  final cachedAt = DateTime.utc(2026, 7, 17, 3, 4, 5);

  test('identifies the app platform on API requests', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    final clientName =
        container.read(dioProvider).options.headers['X-Client-Name'];

    expect(clientName, isA<String>());
    expect(clientName, startsWith('Personal AI '));
  });

  test('clears the local session after a 401 response', () async {
    final tokenStorage = FakeTokenStorage();
    final apiCache = FakeApiCache();
    final container = ProviderContainer(
      overrides: [
        tokenStorageProvider.overrideWithValue(tokenStorage),
        apiCacheProvider.overrideWithValue(apiCache),
      ],
    );
    addTearDown(container.dispose);
    final dio = container.read(dioProvider);
    dio.httpClientAdapter = UnauthorizedAdapter();
    container.read(cacheFallbackNoticeProvider.notifier).state =
        CacheFallbackNotice(
      reason: CacheFallbackReason.offline,
      cachedAt: cachedAt,
    );

    await expectLater(
        dio.get<void>('/documents'), throwsA(isA<DioException>()));

    expect(tokenStorage.clearCount, 1);
    expect(apiCache.clearCount, 1);
    expect(container.read(authSessionInvalidationProvider), 1);
    expect(container.read(cacheFallbackNoticeProvider), isNull);
  });

  test('returns cached GET data while offline', () async {
    final apiCache = FakeApiCache(
      cachedData: {
        'items': <dynamic>[],
        'total': 0,
        'page': 1,
        'page_size': 20,
      },
      cachedHeaders: {
        'x-total-count': ['100'],
      },
      cachedAt: cachedAt,
    );
    final container = ProviderContainer(
      overrides: [
        tokenStorageProvider.overrideWithValue(FakeTokenStorage()),
        apiCacheProvider.overrideWithValue(apiCache),
      ],
    );
    addTearDown(container.dispose);
    final dio = container.read(dioProvider);
    dio.httpClientAdapter = OfflineAdapter();

    final response = await dio.get<Map<String, dynamic>>('/documents');

    expect(response.data?['total'], 0);
    expect(response.extra['from_cache'], isTrue);
    expect(response.extra['cache_fallback_reason'], 'offline');
    expect(response.extra['cached_at'], cachedAt.toIso8601String());
    expect(response.headers.value('x-total-count'), '100');
    final notice = container.read(cacheFallbackNoticeProvider);
    expect(notice?.reason, CacheFallbackReason.offline);
    expect(notice?.cachedAt, cachedAt);
  });

  test('returns cached GET data after a 503 response', () async {
    final apiCache = FakeApiCache(
      cachedData: {
        'items': <dynamic>[],
        'total': 3,
        'page': 1,
        'page_size': 20,
      },
      cachedHeaders: {
        'x-total-count': ['3'],
      },
      cachedAt: cachedAt,
    );
    final container = ProviderContainer(
      overrides: [
        tokenStorageProvider.overrideWithValue(FakeTokenStorage()),
        apiCacheProvider.overrideWithValue(apiCache),
      ],
    );
    addTearDown(container.dispose);
    final dio = container.read(dioProvider);
    dio.httpClientAdapter = ServiceUnavailableAdapter();
    container.read(cacheFallbackNoticeProvider.notifier).state =
        CacheFallbackNotice(
      reason: CacheFallbackReason.offline,
      cachedAt: cachedAt,
    );

    final response = await dio.get<Map<String, dynamic>>('/documents');

    expect(response.data?['total'], 3);
    expect(response.extra['from_cache'], isTrue);
    expect(response.extra['cache_fallback_reason'], 'service_unavailable');
    expect(response.extra['retry_after'], '5');
    expect(response.extra['cached_at'], cachedAt.toIso8601String());
    expect(response.headers.value('x-total-count'), '3');
    expect(apiCache.readCount, 1);
    final notice = container.read(cacheFallbackNoticeProvider);
    expect(notice?.reason, CacheFallbackReason.serviceUnavailable);
    expect(notice?.retryAfter, '5');
    expect(notice?.cachedAt, cachedAt);
  });

  test('keeps a 503 error when cached GET data is unavailable', () async {
    final apiCache = FakeApiCache();
    final container = ProviderContainer(
      overrides: [
        tokenStorageProvider.overrideWithValue(FakeTokenStorage()),
        apiCacheProvider.overrideWithValue(apiCache),
      ],
    );
    addTearDown(container.dispose);
    final dio = container.read(dioProvider);
    dio.httpClientAdapter = ServiceUnavailableAdapter();
    container.read(cacheFallbackNoticeProvider.notifier).state =
        CacheFallbackNotice(
      reason: CacheFallbackReason.offline,
      cachedAt: cachedAt,
    );

    await expectLater(
      dio.get<void>('/documents'),
      throwsA(
        isA<DioException>()
            .having((error) => error.response?.statusCode, 'status', 503)
            .having(
              (error) => error.message,
              'message',
              '数据库暂时不可用，请稍后重试',
            ),
      ),
    );

    expect(apiCache.readCount, 1);
    expect(
      container.read(cacheFallbackNoticeProvider)?.cachedAt,
      cachedAt,
    );
  });

  test('does not use cached data for a failed mutation', () async {
    final apiCache = FakeApiCache(cachedData: {'stale': true});
    final container = ProviderContainer(
      overrides: [
        tokenStorageProvider.overrideWithValue(FakeTokenStorage()),
        apiCacheProvider.overrideWithValue(apiCache),
      ],
    );
    addTearDown(container.dispose);
    final dio = container.read(dioProvider);
    dio.httpClientAdapter = ServiceUnavailableAdapter();
    container.read(cacheFallbackNoticeProvider.notifier).state =
        CacheFallbackNotice(
      reason: CacheFallbackReason.offline,
      cachedAt: cachedAt,
    );

    await expectLater(
      dio.patch<void>('/documents/document-id', data: {'title': '新标题'}),
      throwsA(isA<DioException>()),
    );

    expect(apiCache.readCount, 0);
    expect(apiCache.clearCount, 0);
    expect(
      container.read(cacheFallbackNoticeProvider)?.cachedAt,
      cachedAt,
    );
  });

  test('clears a cache fallback notice after a live GET response', () async {
    final apiCache = FakeApiCache();
    final container = ProviderContainer(
      overrides: [
        tokenStorageProvider.overrideWithValue(FakeTokenStorage()),
        apiCacheProvider.overrideWithValue(apiCache),
      ],
    );
    addTearDown(container.dispose);
    final dio = container.read(dioProvider);
    dio.httpClientAdapter = SuccessAdapter();
    container.read(cacheFallbackNoticeProvider.notifier).state =
        CacheFallbackNotice(
      reason: CacheFallbackReason.offline,
      cachedAt: cachedAt,
    );

    await dio.get<void>('/documents');

    expect(container.read(cacheFallbackNoticeProvider), isNull);
  });

  test('clears cached GET data after a successful mutation', () async {
    final apiCache = FakeApiCache();
    final container = ProviderContainer(
      overrides: [
        tokenStorageProvider.overrideWithValue(FakeTokenStorage()),
        apiCacheProvider.overrideWithValue(apiCache),
      ],
    );
    addTearDown(container.dispose);
    final dio = container.read(dioProvider);
    dio.httpClientAdapter = SuccessAdapter();
    container.read(cacheFallbackNoticeProvider.notifier).state =
        CacheFallbackNotice(
      reason: CacheFallbackReason.offline,
      cachedAt: cachedAt,
    );

    await dio.patch<void>('/documents/document-id', data: {'title': '新标题'});

    expect(apiCache.clearCount, 1);
    expect(container.read(cacheFallbackNoticeProvider), isNull);
  });

  test('keeps the notice when mixed revalidation results finish out of order',
      () async {
    final apiCache = FakeApiCache(cachedData: {'cached': true});
    final container = ProviderContainer(
      overrides: [
        tokenStorageProvider.overrideWithValue(FakeTokenStorage()),
        apiCacheProvider.overrideWithValue(apiCache),
      ],
    );
    addTearDown(container.dispose);
    final dio = container.read(dioProvider);
    final adapter = MixedRevalidationAdapter();
    dio.httpClientAdapter = adapter;
    container.read(cacheFallbackNoticeProvider.notifier).state =
        CacheFallbackNotice(
      reason: CacheFallbackReason.offline,
      cachedAt: cachedAt,
    );
    container.read(cacheRevalidationTrackerProvider.notifier).start();

    final liveRequest = dio.get<dynamic>('/documents');
    final fallbackRequest = dio.get<dynamic>('/tags');
    await adapter.waitForRequests(2);

    adapter.respond(
      '/tags',
      statusCode: 503,
      body: '{"message":"数据库暂时不可用"}',
    );
    await fallbackRequest;
    adapter.respond('/documents', statusCode: 200, body: '{}');
    await liveRequest;
    await Future<void>.delayed(const Duration(milliseconds: 150));

    final revalidation = container.read(cacheRevalidationTrackerProvider);
    expect(revalidation.inProgress, isFalse);
    expect(revalidation.liveResponses, 1);
    expect(revalidation.fallbackResponses, 1);
    expect(
      container.read(cacheFallbackNoticeProvider)?.reason,
      CacheFallbackReason.serviceUnavailable,
    );
  });
}

class FakeTokenStorage extends TokenStorage {
  FakeTokenStorage() : super(const FlutterSecureStorage());

  int clearCount = 0;

  @override
  Future<String?> readToken() async => 'expired-token';

  @override
  Future<void> clear() async {
    clearCount += 1;
  }
}

class UnauthorizedAdapter implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    return ResponseBody.fromString(
      '{"detail":"登录状态无效或已过期"}',
      401,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class OfflineAdapter implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) {
    throw DioException(
      requestOptions: options,
      type: DioExceptionType.connectionError,
      error: 'offline',
    );
  }

  @override
  void close({bool force = false}) {}
}

class SuccessAdapter implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    return ResponseBody.fromString(
      '{}',
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class ServiceUnavailableAdapter implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    return ResponseBody.fromString(
      '{"message":"数据库暂时不可用，请稍后重试","detail":"数据库暂时不可用，请稍后重试"}',
      503,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
        'retry-after': ['5'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class MixedRevalidationAdapter implements HttpClientAdapter {
  final Map<String, Completer<ResponseBody>> _requests = {};

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) {
    final request = Completer<ResponseBody>();
    _requests[options.path] = request;
    return request.future;
  }

  Future<void> waitForRequests(int count) async {
    for (var attempt = 0; attempt < 20; attempt += 1) {
      if (_requests.length >= count) {
        return;
      }
      await Future<void>.delayed(Duration.zero);
    }
    fail(
        'Expected $count revalidation requests, received ${_requests.length}.');
  }

  void respond(
    String path, {
    required int statusCode,
    required String body,
  }) {
    _requests[path]!.complete(
      ResponseBody.fromString(
        body,
        statusCode,
        headers: {
          Headers.contentTypeHeader: ['application/json'],
          if (statusCode == 503) 'retry-after': ['5'],
        },
      ),
    );
  }

  @override
  void close({bool force = false}) {}
}

class FakeApiCache extends ApiCache {
  FakeApiCache({
    this.cachedData,
    this.cachedHeaders = const {},
    DateTime? cachedAt,
  })  : cachedAt = cachedAt ?? DateTime.utc(2026, 7, 17, 3, 4, 5),
        super(const FlutterSecureStorage());

  final dynamic cachedData;
  final Map<String, List<String>> cachedHeaders;
  final DateTime cachedAt;
  int clearCount = 0;
  int readCount = 0;

  @override
  Future<CachedApiResponse?> readResponse(RequestOptions options) async {
    readCount += 1;
    if (cachedData == null) {
      return null;
    }
    return CachedApiResponse(
      data: cachedData,
      headers: cachedHeaders,
      cachedAt: cachedAt,
    );
  }

  @override
  Future<void> write(RequestOptions options, dynamic data) async {}

  @override
  Future<void> writeResponse(
    RequestOptions options,
    dynamic data,
    Headers headers,
  ) async {}

  @override
  Future<void> clear() async {
    clearCount += 1;
  }
}
