import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../config/app_config.dart';
import '../storage/api_cache.dart';
import '../storage/token_storage.dart';
import 'cache_state.dart';

final tokenStorageProvider = Provider<TokenStorage>((ref) {
  return TokenStorage(const FlutterSecureStorage());
});

final authSessionInvalidationProvider = StateProvider<int>((ref) => 0);

final apiCacheProvider = Provider<ApiCache>((ref) {
  return ApiCache(const FlutterSecureStorage());
});

final dioProvider = Provider<Dio>((ref) {
  final tokenStorage = ref.watch(tokenStorageProvider);
  final apiCache = ref.watch(apiCacheProvider);
  final dio = Dio(
    BaseOptions(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 60),
      headers: {'X-Client-Name': _clientName()},
    ),
  );

  dio.interceptors.add(
    InterceptorsWrapper(
      onRequest: (options, handler) async {
        if (apiCache.supports(options)) {
          final generation = ref
              .read(cacheRevalidationTrackerProvider.notifier)
              .requestStarted();
          if (generation != null) {
            options.extra[cacheRevalidationGenerationExtra] = generation;
          }
        }
        String? token;
        try {
          token = await tokenStorage
              .readToken()
              .timeout(const Duration(seconds: 2));
        } catch (_) {
          token = null;
        }
        if (token != null && token.isNotEmpty) {
          options.headers['Authorization'] = 'Bearer $token';
        }
        handler.next(options);
      },
      onResponse: (response, handler) async {
        if (response.requestOptions.method.toUpperCase() == 'GET') {
          await apiCache.writeResponse(
            response.requestOptions,
            response.data,
            response.headers,
          );
          final generation = _revalidationGeneration(response.requestOptions);
          if (generation == null) {
            ref.read(cacheFallbackNoticeProvider.notifier).state = null;
          } else {
            ref
                .read(cacheRevalidationTrackerProvider.notifier)
                .requestSucceeded(generation);
          }
        } else {
          await apiCache.clear();
          ref.read(cacheFallbackNoticeProvider.notifier).state = null;
          ref.read(cacheRevalidationTrackerProvider.notifier).cancel();
        }
        handler.next(response);
      },
      onError: (error, handler) async {
        if (error.response?.statusCode == 401) {
          try {
            await tokenStorage.clear().timeout(const Duration(seconds: 2));
          } catch (_) {
            // The in-memory session still needs to expire if secure storage fails.
          }
          await apiCache.clear();
          ref.read(cacheFallbackNoticeProvider.notifier).state = null;
          ref.read(cacheRevalidationTrackerProvider.notifier).cancel();
          ref.read(authSessionInvalidationProvider.notifier).state += 1;
        }
        if (_canUseCachedResponse(error)) {
          final cached = await apiCache.readResponse(error.requestOptions);
          if (cached != null) {
            final retryAfter = error.response?.headers.value('retry-after');
            final fallbackReason = _cacheFallbackReason(error);
            ref.read(cacheFallbackNoticeProvider.notifier).state =
                CacheFallbackNotice(
              reason: fallbackReason,
              cachedAt: cached.cachedAt,
              retryAfter: retryAfter,
            );
            ref
                .read(cacheRevalidationTrackerProvider.notifier)
                .requestUsedFallback(
                  _revalidationGeneration(error.requestOptions),
                );
            handler.resolve(
              Response<dynamic>(
                requestOptions: error.requestOptions,
                data: cached.data,
                statusCode: 200,
                headers: Headers.fromMap(cached.headers),
                extra: {
                  'from_cache': true,
                  'cache_fallback_reason': fallbackReason.value,
                  if (retryAfter != null) 'retry_after': retryAfter,
                  'cached_at': cached.cachedAt.toIso8601String(),
                },
              ),
            );
            return;
          }
        }
        ref.read(cacheRevalidationTrackerProvider.notifier).requestFailed(
              _revalidationGeneration(error.requestOptions),
            );
        handler.next(_withApiMessage(error));
      },
    ),
  );

  return dio;
});

String _clientName() {
  if (kIsWeb) {
    return 'Personal AI Web';
  }
  return switch (defaultTargetPlatform) {
    TargetPlatform.android => 'Personal AI Android',
    TargetPlatform.iOS => 'Personal AI iOS',
    TargetPlatform.windows => 'Personal AI Windows',
    TargetPlatform.macOS => 'Personal AI macOS',
    TargetPlatform.linux => 'Personal AI Linux',
    TargetPlatform.fuchsia => 'Personal AI Fuchsia',
  };
}

int? _revalidationGeneration(RequestOptions options) {
  final value = options.extra[cacheRevalidationGenerationExtra];
  return value is int ? value : null;
}

bool _canUseCachedResponse(DioException error) {
  if (error.requestOptions.method.toUpperCase() != 'GET') {
    return false;
  }
  if (error.response?.statusCode == 503) {
    return true;
  }
  if (error.response != null) {
    return false;
  }
  return switch (error.type) {
    DioExceptionType.connectionTimeout ||
    DioExceptionType.sendTimeout ||
    DioExceptionType.receiveTimeout ||
    DioExceptionType.connectionError ||
    DioExceptionType.unknown =>
      true,
    _ => false,
  };
}

CacheFallbackReason _cacheFallbackReason(DioException error) {
  return error.response?.statusCode == 503
      ? CacheFallbackReason.serviceUnavailable
      : CacheFallbackReason.offline;
}

DioException _withApiMessage(DioException error) {
  final data = error.response?.data;
  if (data is! Map<String, dynamic>) {
    return error;
  }
  final message = data['message'];
  if (message is! String || message.isEmpty) {
    return error;
  }
  return DioException(
    requestOptions: error.requestOptions,
    response: error.response,
    type: error.type,
    error: error.error,
    stackTrace: error.stackTrace,
    message: message,
  );
}
