import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/core/storage/api_cache.dart';

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
  });

  test('stores, reads and clears supported GET responses', () async {
    final cache = ApiCache(const FlutterSecureStorage());
    final request = RequestOptions(
      path: '/documents',
      method: 'GET',
      queryParameters: {'page': 1},
    );
    final data = {
      'items': <dynamic>[],
      'total': 0,
      'page': 1,
      'page_size': 20,
    };

    final writeStartedAt = DateTime.now().toUtc();
    await cache.writeResponse(
      request,
      data,
      Headers.fromMap({
        'x-total-count': ['100'],
      }),
    );
    final writeFinishedAt = DateTime.now().toUtc();
    final cachedResponse = await cache.readResponse(request);
    expect(cachedResponse?.data, data);
    expect(cachedResponse?.headers['x-total-count'], ['100']);
    expect(cachedResponse?.cachedAt.isUtc, isTrue);
    expect(cachedResponse!.cachedAt.compareTo(writeStartedAt),
        greaterThanOrEqualTo(0));
    expect(cachedResponse.cachedAt.compareTo(writeFinishedAt),
        lessThanOrEqualTo(0));

    await cache.clear();
    expect(await cache.readResponse(request), isNull);
  });

  test('does not cache mutations', () async {
    final cache = ApiCache(const FlutterSecureStorage());
    final request = RequestOptions(path: '/documents/note', method: 'POST');

    await cache.write(request, {'id': 'note'});

    expect(await cache.read(request), isNull);
  });

  test('supports cursor scan responses used by complete loaders', () {
    final cache = ApiCache(const FlutterSecureStorage());

    expect(
      cache.supports(RequestOptions(path: '/documents/scan', method: 'GET')),
      isTrue,
    );
    expect(
      cache.supports(
        RequestOptions(
          path: '/chat/conversations/id/messages/scan',
          method: 'GET',
        ),
      ),
      isTrue,
    );
    expect(
      cache.supports(RequestOptions(path: '/tags/scan', method: 'GET')),
      isTrue,
    );
  });

  test('keeps every concurrent cache entry indexed for session clearing',
      () async {
    final storage = DelayedSecureStorage();
    final cache = ApiCache(storage);
    final firstRequest = RequestOptions(
      path: '/documents',
      method: 'GET',
      queryParameters: {'page': 1},
    );
    final secondRequest = RequestOptions(
      path: '/documents',
      method: 'GET',
      queryParameters: {'page': 2},
    );

    await Future.wait([
      cache.write(firstRequest, {'page': 1}),
      cache.write(secondRequest, {'page': 2}),
    ]);
    await cache.clear();

    expect(
      storage.values.keys.where((key) => key.startsWith('api_cache_v3_')),
      isEmpty,
    );
  });

  test('clear waits for an in-flight cache write', () async {
    final storage = DelayedSecureStorage();
    final cache = ApiCache(storage);
    final request = RequestOptions(path: '/documents', method: 'GET');

    await Future.wait([
      cache.write(request, {'items': <dynamic>[]}),
      cache.clear(),
    ]);

    expect(await cache.read(request), isNull);
    expect(
      storage.values.keys.where((key) => key.startsWith('api_cache_v3_')),
      isEmpty,
    );
  });

  test('clears entries listed by the legacy cache index', () async {
    final storage = DelayedSecureStorage();
    storage.values['api_cache_v2_legacy_entry'] = 'encrypted-data';
    storage.values['api_cache_v2_index'] = jsonEncode([
      'api_cache_v2_legacy_entry',
    ]);
    storage.values['api_cache_legacy_entry'] = 'encrypted-data';
    storage.values['access_token'] = 'must-not-be-deleted';
    storage.values['api_cache_index'] = jsonEncode([
      'api_cache_legacy_entry',
      'access_token',
    ]);
    final cache = ApiCache(storage);

    await cache.clear();

    expect(storage.values.containsKey('api_cache_v2_legacy_entry'), isFalse);
    expect(storage.values.containsKey('api_cache_v2_index'), isFalse);
    expect(storage.values.containsKey('api_cache_legacy_entry'), isFalse);
    expect(storage.values.containsKey('api_cache_index'), isFalse);
    expect(storage.values['access_token'], 'must-not-be-deleted');
  });

  test('isolates identical requests by authorization token fingerprint',
      () async {
    final storage = DelayedSecureStorage();
    final cache = ApiCache(storage);
    final firstSessionRequest = RequestOptions(
      path: '/documents',
      method: 'GET',
      headers: {'Authorization': 'Bearer first-secret-token'},
    );
    final secondSessionRequest = RequestOptions(
      path: '/documents',
      method: 'GET',
      headers: {'Authorization': 'Bearer second-secret-token'},
    );

    await cache.write(firstSessionRequest, {'owner': 'first'});

    expect((await cache.read(firstSessionRequest))?['owner'], 'first');
    expect(await cache.read(secondSessionRequest), isNull);
    expect(
      storage.values.keys.any((key) => key.contains('first-secret-token')),
      isFalse,
    );
  });

  test('evicts the oldest entry when the count limit is reached', () async {
    final storage = DelayedSecureStorage();
    final cache = ApiCache(
      storage,
      maxEntries: 2,
      maxTotalBytes: 1024 * 1024,
    );
    final requests = [
      for (var page = 1; page <= 3; page += 1)
        RequestOptions(
          path: '/documents',
          method: 'GET',
          queryParameters: {'page': page},
        ),
    ];

    for (var index = 0; index < requests.length; index += 1) {
      await cache.write(requests[index], {'page': index + 1});
      await Future<void>.delayed(const Duration(milliseconds: 2));
    }

    expect(await cache.read(requests.first), isNull);
    expect((await cache.read(requests[1]))?['page'], 2);
    expect((await cache.read(requests[2]))?['page'], 3);
  });

  test('evicts oldest entries when the total byte limit is reached', () async {
    final storage = DelayedSecureStorage();
    final cache = ApiCache(
      storage,
      maxEntries: 64,
      maxTotalBytes: 700,
    );
    final firstRequest = RequestOptions(
      path: '/documents',
      method: 'GET',
      queryParameters: {'page': 1},
    );
    final secondRequest = RequestOptions(
      path: '/documents',
      method: 'GET',
      queryParameters: {'page': 2},
    );
    final firstPayload = List.filled(400, 'a').join();
    final secondPayload = List.filled(400, 'b').join();

    await cache.write(firstRequest, {'text': firstPayload});
    await Future<void>.delayed(const Duration(milliseconds: 2));
    await cache.write(secondRequest, {'text': secondPayload});

    expect(await cache.read(firstRequest), isNull);
    expect((await cache.read(secondRequest))?['text'], secondPayload);
  });

  test('removes an expired entry and its index metadata while reading',
      () async {
    final storage = DelayedSecureStorage();
    final cache = ApiCache(storage);
    final request = RequestOptions(path: '/documents', method: 'GET');
    await cache.write(request, {'items': <dynamic>[]});
    final entryKey = storage.values.keys.singleWhere(
      (key) => key.startsWith('api_cache_v3_') && key != 'api_cache_v3_index',
    );
    final entry = jsonDecode(storage.values[entryKey]!) as Map<String, dynamic>;
    entry['cached_at'] = DateTime.now()
        .toUtc()
        .subtract(const Duration(days: 8))
        .toIso8601String();
    storage.values[entryKey] = jsonEncode(entry);

    expect(await cache.read(request), isNull);
    expect(storage.values.containsKey(entryKey), isFalse);
    expect(storage.values.containsKey('api_cache_v3_index'), isFalse);
  });

  test('migrates a v3 list index to bounded metadata on the next write',
      () async {
    final storage = DelayedSecureStorage();
    final cache = ApiCache(storage);
    final firstRequest = RequestOptions(
      path: '/documents',
      method: 'GET',
      queryParameters: {'page': 1},
    );
    final secondRequest = RequestOptions(
      path: '/documents',
      method: 'GET',
      queryParameters: {'page': 2},
    );
    await cache.write(firstRequest, {'page': 1});
    final firstEntryKey = storage.values.keys.singleWhere(
      (key) => key.startsWith('api_cache_v3_') && key != 'api_cache_v3_index',
    );
    storage.values['api_cache_v3_index'] = jsonEncode([firstEntryKey]);

    await cache.write(secondRequest, {'page': 2});

    final index = jsonDecode(storage.values['api_cache_v3_index']!)
        as Map<String, dynamic>;
    expect(index['version'], 1);
    expect(index['entries'], hasLength(2));
  });

  test('times out a hung write while preserving queued clear order', () async {
    final storage = BlockingWriteSecureStorage();
    final cache = ApiCache(
      storage,
      operationTimeout: const Duration(milliseconds: 20),
    );
    final request = RequestOptions(path: '/documents', method: 'GET');

    final write = cache.write(request, {'items': <dynamic>[]});
    await storage.writeStarted.future;
    await write;
    final clear = cache.clear();
    await clear;

    storage.releaseWrite.complete();
    await storage.v3IndexDeleted.future.timeout(const Duration(seconds: 1));

    expect(
      storage.values.keys.where((key) => key.startsWith('api_cache_v3_')),
      isEmpty,
    );
  });

  test('returns a cache miss when secure storage read exceeds its budget',
      () async {
    final storage = BlockingReadSecureStorage();
    final cache = ApiCache(
      storage,
      operationTimeout: const Duration(milliseconds: 20),
    );
    final request = RequestOptions(path: '/documents', method: 'GET');

    final read = cache.read(request);
    await storage.readStarted.future;
    expect(await read, isNull);
    storage.releaseRead.complete();
  });
}

class DelayedSecureStorage extends FlutterSecureStorage {
  final Map<String, String> values = {};

  @override
  Future<String?> read({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    final value = values[key];
    await Future<void>.delayed(Duration.zero);
    return value;
  }

  @override
  Future<void> write({
    required String key,
    required String? value,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    await Future<void>.delayed(Duration.zero);
    if (value == null) {
      values.remove(key);
    } else {
      values[key] = value;
    }
  }

  @override
  Future<void> delete({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    await Future<void>.delayed(Duration.zero);
    values.remove(key);
  }
}

class BlockingWriteSecureStorage extends DelayedSecureStorage {
  final Completer<void> writeStarted = Completer<void>();
  final Completer<void> releaseWrite = Completer<void>();
  final Completer<void> v3IndexDeleted = Completer<void>();
  bool _blockNextWrite = true;

  @override
  Future<void> write({
    required String key,
    required String? value,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (_blockNextWrite) {
      _blockNextWrite = false;
      writeStarted.complete();
      await releaseWrite.future;
    }
    await super.write(key: key, value: value);
  }

  @override
  Future<void> delete({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    await super.delete(key: key);
    if (key == 'api_cache_v3_index' && !v3IndexDeleted.isCompleted) {
      v3IndexDeleted.complete();
    }
  }
}

class BlockingReadSecureStorage extends DelayedSecureStorage {
  final Completer<void> readStarted = Completer<void>();
  final Completer<void> releaseRead = Completer<void>();
  bool _blockNextRead = true;

  @override
  Future<String?> read({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (_blockNextRead) {
      _blockNextRead = false;
      readStarted.complete();
      await releaseRead.future;
    }
    return super.read(key: key);
  }
}
