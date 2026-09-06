import 'dart:async';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TokenStorage {
  TokenStorage(
    this._storage, {
    Duration operationTimeout = const Duration(seconds: 2),
  })  : assert(operationTimeout.inMicroseconds > 0),
        _operationTimeout = operationTimeout;

  final FlutterSecureStorage _storage;
  final Duration _operationTimeout;
  Future<void> _operationTail = Future<void>.value();

  static const _tokenKey = 'access_token';

  Future<String?> readToken() => _synchronized(
        () => _storage.read(key: _tokenKey),
      ).timeout(_operationTimeout);

  Future<void> saveToken(String token) async {
    try {
      await _synchronized(
        () => _storage.write(key: _tokenKey, value: token),
      ).timeout(_operationTimeout);
    } catch (_) {
      unawaited(_removeFailedToken(token));
      rethrow;
    }
  }

  Future<void> clear() => _synchronized(
        () => _storage.delete(key: _tokenKey),
      ).timeout(_operationTimeout);

  Future<void> _removeFailedToken(String token) async {
    try {
      await _synchronized(() async {
        final currentToken = await _storage.read(key: _tokenKey);
        if (currentToken == token) {
          await _storage.delete(key: _tokenKey);
        }
      });
    } catch (_) {
      // A later explicit clear or token-scoped cache still protects the session.
    }
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
}
