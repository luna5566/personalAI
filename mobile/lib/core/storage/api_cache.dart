import 'dart:async';
import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class CachedApiResponse {
  const CachedApiResponse({
    required this.data,
    required this.headers,
    required this.cachedAt,
  });

  final dynamic data;
  final Map<String, List<String>> headers;
  final DateTime cachedAt;
}

class ApiCache {
  ApiCache(
    this._storage, {
    int maxEntries = 64,
    int maxTotalBytes = 4 * 1024 * 1024,
    Duration operationTimeout = const Duration(seconds: 2),
  })  : assert(maxEntries > 0),
        assert(maxTotalBytes > 0),
        assert(operationTimeout.inMicroseconds > 0),
        _maxEntries = maxEntries,
        _maxTotalBytes = maxTotalBytes,
        _operationTimeout = operationTimeout;

  final FlutterSecureStorage _storage;
  final int _maxEntries;
  final int _maxTotalBytes;
  final Duration _operationTimeout;
  Future<void> _operationTail = Future<void>.value();

  static const _indexKey = 'api_cache_v3_index';
  static const _prefix = 'api_cache_v3_';
  static const _legacyIndexKeys = [
    'api_cache_v2_index',
    'api_cache_index',
  ];
  static const _maxEntryBytes = 512 * 1024;
  static const _maxAge = Duration(days: 7);

  bool supports(RequestOptions options) {
    if (options.method.toUpperCase() != 'GET') {
      return false;
    }
    final path = options.path;
    return path == '/documents' ||
        path.startsWith('/documents/') ||
        path == '/auth/me' ||
        path == '/tags' ||
        path == '/tags/scan' ||
        path == '/chat/conversations' ||
        path.startsWith('/chat/conversations/') ||
        path == '/settings/runtime';
  }

  Future<void> write(RequestOptions options, dynamic data) async {
    await writeResponse(options, data, Headers());
  }

  Future<void> writeResponse(
    RequestOptions options,
    dynamic data,
    Headers headers,
  ) async {
    if (!supports(options)) {
      return;
    }
    try {
      await _synchronized(() async {
        final cachedAt = DateTime.now().toUtc();
        final encoded = jsonEncode({
          'cached_at': cachedAt.toIso8601String(),
          'data': data,
          'headers': {
            if (headers.value('x-total-count') case final total?)
              'x-total-count': total,
          },
        });
        if (utf8.encode(encoded).length > _maxEntryBytes) {
          return;
        }
        final key = _key(options);
        await _storage.write(key: key, value: encoded);
        final entries = await _readCurrentIndex();
        entries.removeWhere((entry) => entry.key == key);
        entries.add(
          _CacheIndexEntry(
            key: key,
            cachedAt: cachedAt,
            byteSize: utf8.encode(encoded).length,
          ),
        );
        final retainedEntries = await _pruneCurrentIndex(entries, cachedAt);
        await _writeCurrentIndex(retainedEntries);
      }).timeout(_operationTimeout);
    } catch (_) {
      // Cache failures must never fail an API request.
    }
  }

  Future<dynamic> read(RequestOptions options) async {
    return (await readResponse(options))?.data;
  }

  Future<Map<String, List<String>>> readHeaders(RequestOptions options) async {
    return (await readResponse(options))?.headers ?? const {};
  }

  Future<CachedApiResponse?> readResponse(RequestOptions options) async {
    if (!supports(options)) {
      return null;
    }
    try {
      return await _synchronized(() async {
        final key = _key(options);
        String? value;
        try {
          value = await _storage.read(key: key);
        } catch (_) {
          return null;
        }
        if (value == null) {
          await _removeCurrentEntry(key, deleteValue: false);
          return null;
        }
        try {
          final decoded = jsonDecode(value) as Map<String, dynamic>;
          final cachedAt = DateTime.parse(decoded['cached_at'] as String);
          if (DateTime.now().toUtc().difference(cachedAt) > _maxAge) {
            await _removeCurrentEntry(key);
            return null;
          }
          final rawHeaders = decoded['headers'];
          return CachedApiResponse(
            data: decoded['data'],
            headers: rawHeaders is Map<String, dynamic>
                ? {
                    for (final entry in rawHeaders.entries)
                      entry.key: [entry.value.toString()],
                  }
                : const {},
            cachedAt: cachedAt.toUtc(),
          );
        } catch (_) {
          await _removeCurrentEntry(key);
          return null;
        }
      }).timeout(_operationTimeout);
    } catch (_) {
      return null;
    }
  }

  Future<void> clear() async {
    try {
      await _synchronized(() async {
        await _clearIndex(_indexKey);
        for (final indexKey in _legacyIndexKeys) {
          await _clearIndex(indexKey);
        }
      }).timeout(_operationTimeout);
    } catch (_) {
      // Session cleanup should continue even when secure storage is unavailable.
    }
  }

  Future<void> _clearIndex(String indexKey) async {
    final keys = await _readIndexKeys(indexKey);
    for (final key in keys) {
      await _storage.delete(key: key);
    }
    await _storage.delete(key: indexKey);
  }

  Future<Set<String>> _readIndexKeys(String indexKey) async {
    final value = await _storage.read(key: indexKey);
    if (value == null || value.isEmpty) {
      return <String>{};
    }
    final decoded = jsonDecode(value);
    final rawKeys = switch (decoded) {
      List<dynamic> items => items.map((item) => item.toString()),
      Map<String, dynamic> data when data['entries'] is List<dynamic> =>
        (data['entries'] as List<dynamic>).map(
          (item) => item is Map<String, dynamic> ? item['key'].toString() : '',
        ),
      _ => const Iterable<String>.empty(),
    };
    return rawKeys.where((key) => _isEntryKeyForIndex(indexKey, key)).toSet();
  }

  Future<List<_CacheIndexEntry>> _readCurrentIndex() async {
    final value = await _storage.read(key: _indexKey);
    if (value == null || value.isEmpty) {
      return [];
    }
    final decoded = jsonDecode(value);
    if (decoded case {'entries': final List<dynamic> rawEntries}) {
      return rawEntries
          .map(_CacheIndexEntry.tryParse)
          .whereType<_CacheIndexEntry>()
          .where((entry) => entry.key.startsWith(_prefix))
          .toList();
    }
    if (decoded is List<dynamic>) {
      final entries = <_CacheIndexEntry>[];
      for (final item in decoded) {
        final key = item.toString();
        if (!key.startsWith(_prefix)) {
          continue;
        }
        final entry = await _readEntryMetadata(key);
        if (entry != null) {
          entries.add(entry);
        }
      }
      return entries;
    }
    return [];
  }

  Future<_CacheIndexEntry?> _readEntryMetadata(String key) async {
    final value = await _storage.read(key: key);
    if (value == null) {
      return null;
    }
    try {
      final decoded = jsonDecode(value) as Map<String, dynamic>;
      return _CacheIndexEntry(
        key: key,
        cachedAt: DateTime.parse(decoded['cached_at'] as String).toUtc(),
        byteSize: utf8.encode(value).length,
      );
    } catch (_) {
      await _storage.delete(key: key);
      return null;
    }
  }

  Future<List<_CacheIndexEntry>> _pruneCurrentIndex(
    List<_CacheIndexEntry> entries,
    DateTime now,
  ) async {
    final retained = <_CacheIndexEntry>[];
    for (final entry in entries) {
      if (now.difference(entry.cachedAt) > _maxAge) {
        await _storage.delete(key: entry.key);
      } else {
        retained.add(entry);
      }
    }
    retained.sort((left, right) => left.cachedAt.compareTo(right.cachedAt));
    var totalBytes = retained.fold<int>(
      0,
      (total, entry) => total + entry.byteSize,
    );
    while (retained.length > _maxEntries || totalBytes > _maxTotalBytes) {
      final removed = retained.removeAt(0);
      totalBytes -= removed.byteSize;
      await _storage.delete(key: removed.key);
    }
    return retained;
  }

  Future<void> _writeCurrentIndex(List<_CacheIndexEntry> entries) async {
    if (entries.isEmpty) {
      await _storage.delete(key: _indexKey);
      return;
    }
    await _storage.write(
      key: _indexKey,
      value: jsonEncode({
        'version': 1,
        'entries': entries.map((entry) => entry.toJson()).toList(),
      }),
    );
  }

  Future<void> _removeCurrentEntry(
    String key, {
    bool deleteValue = true,
  }) async {
    try {
      if (deleteValue) {
        await _storage.delete(key: key);
      }
      final entries = await _readCurrentIndex();
      entries.removeWhere((entry) => entry.key == key);
      await _writeCurrentIndex(entries);
    } catch (_) {
      // Invalid cache cleanup must not fail the caller.
    }
  }

  bool _isEntryKeyForIndex(String indexKey, String key) {
    final prefix = switch (indexKey) {
      _indexKey => _prefix,
      'api_cache_v2_index' => 'api_cache_v2_',
      'api_cache_index' => 'api_cache_',
      _ => '',
    };
    return prefix.isNotEmpty && key.startsWith(prefix) && key != indexKey;
  }

  Future<T> _synchronized<T>(Future<T> Function() operation) async {
    final previous = _operationTail;
    final release = Completer<void>();
    _operationTail = release.future;
    await previous;
    try {
      return await operation();
    } finally {
      release.complete();
    }
  }

  String _key(RequestOptions options) {
    final queryEntries = options.queryParameters.entries.toList()
      ..sort((left, right) => left.key.compareTo(right.key));
    final signature = jsonEncode({
      'scope': _authorizationScope(options),
      'path': options.path,
      'query': {for (final entry in queryEntries) entry.key: entry.value},
    });
    return '$_prefix${base64Url.encode(utf8.encode(signature)).replaceAll('=', '')}';
  }

  String _authorizationScope(RequestOptions options) {
    String? authorization;
    for (final entry in options.headers.entries) {
      if (entry.key.toLowerCase() == 'authorization') {
        authorization = entry.value?.toString();
        break;
      }
    }
    if (authorization == null || authorization.isEmpty) {
      return 'anonymous';
    }
    return sha256.convert(utf8.encode(authorization)).toString();
  }
}

class _CacheIndexEntry {
  const _CacheIndexEntry({
    required this.key,
    required this.cachedAt,
    required this.byteSize,
  });

  final String key;
  final DateTime cachedAt;
  final int byteSize;

  Map<String, dynamic> toJson() {
    return {
      'key': key,
      'cached_at': cachedAt.toUtc().toIso8601String(),
      'byte_size': byteSize,
    };
  }

  static _CacheIndexEntry? tryParse(dynamic value) {
    if (value is! Map<String, dynamic>) {
      return null;
    }
    final key = value['key'];
    final cachedAt = value['cached_at'];
    final byteSize = value['byte_size'];
    if (key is! String || cachedAt is! String || byteSize is! int) {
      return null;
    }
    try {
      return _CacheIndexEntry(
        key: key,
        cachedAt: DateTime.parse(cachedAt).toUtc(),
        byteSize: byteSize,
      );
    } catch (_) {
      return null;
    }
  }
}
