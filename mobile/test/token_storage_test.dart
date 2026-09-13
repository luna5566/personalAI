import 'dart:async';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/core/storage/token_storage.dart';

void main() {
  for (final operation in TokenOperation.values) {
    test('${operation.name} respects the secure storage operation budget',
        () async {
      final storage = BlockingTokenSecureStorage(operation);
      final tokenStorage = TokenStorage(
        storage,
        operationTimeout: const Duration(milliseconds: 20),
      );

      final result = switch (operation) {
        TokenOperation.read => tokenStorage.readToken(),
        TokenOperation.write => tokenStorage.saveToken('token'),
        TokenOperation.delete => tokenStorage.clear(),
      };
      await storage.started.future;

      await expectLater(result, throwsA(isA<TimeoutException>()));
      storage.release.complete();
      await storage.completed.future.timeout(const Duration(seconds: 1));
    });
  }

  test('removes a token written after save timeout', () async {
    final storage = LateWriteTokenSecureStorage();
    final tokenStorage = TokenStorage(
      storage,
      operationTimeout: const Duration(milliseconds: 20),
    );

    final save = tokenStorage.saveToken('late-token');
    await storage.firstWriteStarted.future;
    await expectLater(save, throwsA(isA<TimeoutException>()));
    storage.releaseFirstWrite.complete();
    await storage.compensatingDelete.future.timeout(const Duration(seconds: 1));

    expect(storage.token, isNull);
  });

  test('failed-save compensation does not delete a later successful token',
      () async {
    final storage = LateWriteTokenSecureStorage();
    final tokenStorage = TokenStorage(
      storage,
      operationTimeout: const Duration(milliseconds: 20),
    );

    final firstSave = tokenStorage.saveToken('old-token');
    await storage.firstWriteStarted.future;
    await expectLater(firstSave, throwsA(isA<TimeoutException>()));
    final secondSave = tokenStorage.saveToken('new-token');
    storage.releaseFirstWrite.complete();
    await secondSave;

    expect(storage.token, 'new-token');
  });
}

enum TokenOperation { read, write, delete }

class BlockingTokenSecureStorage extends FlutterSecureStorage {
  BlockingTokenSecureStorage(this.operation);

  final TokenOperation operation;
  final Completer<void> started = Completer<void>();
  final Completer<void> release = Completer<void>();
  final Completer<void> completed = Completer<void>();

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
    if (operation == TokenOperation.read) {
      await _block();
    }
    return null;
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
    if (operation == TokenOperation.write) {
      await _block();
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
    if (operation == TokenOperation.delete) {
      await _block();
    }
  }

  Future<void> _block() async {
    started.complete();
    await release.future;
    completed.complete();
  }
}

class LateWriteTokenSecureStorage extends FlutterSecureStorage {
  final Completer<void> firstWriteStarted = Completer<void>();
  final Completer<void> releaseFirstWrite = Completer<void>();
  final Completer<void> compensatingDelete = Completer<void>();
  bool _blockFirstWrite = true;
  String? token;

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
    return token;
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
    if (_blockFirstWrite) {
      _blockFirstWrite = false;
      firstWriteStarted.complete();
      await releaseFirstWrite.future;
    }
    token = value;
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
    token = null;
    if (!compensatingDelete.isCompleted) {
      compensatingDelete.complete();
    }
  }
}
