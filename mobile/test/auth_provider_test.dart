import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/core/network/api_client.dart';
import 'package:personal_ai_mobile/core/network/cache_state.dart';
import 'package:personal_ai_mobile/core/storage/api_cache.dart';
import 'package:personal_ai_mobile/core/storage/token_storage.dart';
import 'package:personal_ai_mobile/features/auth/data/auth_api.dart';
import 'package:personal_ai_mobile/features/auth/models/user.dart';
import 'package:personal_ai_mobile/features/auth/providers/auth_provider.dart';

void main() {
  test('keeps the token when startup authentication fails temporarily',
      () async {
    final tokenStorage = StartupTokenStorage();
    final container = _container(
      tokenStorage: tokenStorage,
      authApi: FailingMeApi(statusCode: 500),
    );
    addTearDown(container.dispose);

    container.read(authControllerProvider);
    await _waitForStartup(container);

    final state = container.read(authControllerProvider);
    expect(state.startupFailed, isTrue);
    expect(state.error, contains('重试'));
    expect(tokenStorage.clearCount, 0);
  });

  test('clears the token when startup authentication returns 401', () async {
    final tokenStorage = StartupTokenStorage();
    final cache = StartupApiCache();
    final container = _container(
      tokenStorage: tokenStorage,
      apiCache: cache,
      authApi: FailingMeApi(statusCode: 401),
    );
    addTearDown(container.dispose);

    container.read(authControllerProvider);
    await _waitForStartup(container);

    final state = container.read(authControllerProvider);
    expect(state.startupFailed, isFalse);
    expect(state.user, isNull);
    expect(tokenStorage.clearCount, 1);
    expect(cache.clearCount, 1);
  });

  test('silently refreshes the current user during cache revalidation',
      () async {
    final authApi = RefreshingMeApi();
    final container = _container(
      tokenStorage: StartupTokenStorage(),
      authApi: authApi,
    );
    addTearDown(container.dispose);

    container.read(authControllerProvider);
    await _waitForStartup(container);
    expect(container.read(authControllerProvider).user?.email, 'cached@test');

    container.read(cacheRevalidationTrackerProvider.notifier).start();
    await _waitForAuthCalls(authApi, 2);

    final state = container.read(authControllerProvider);
    expect(state.loading, isFalse);
    expect(state.user?.email, 'live@test');
  });

  test('does not authenticate when persisting the login token times out',
      () async {
    final container = _container(
      tokenStorage: FailingSaveTokenStorage(),
      authApi: SuccessfulLoginApi(),
    );
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await _waitForStartup(container);

    await container
        .read(authControllerProvider.notifier)
        .login('user@test', 'password');

    final state = container.read(authControllerProvider);
    expect(state.user, isNull);
    expect(state.loading, isFalse);
    expect(state.error, '登录失败，请稍后重试');
    expect(state.error, isNot(contains('TimeoutException')));
  });

  test('ends the in-memory session when deleting the token times out',
      () async {
    final container = _container(
      tokenStorage: TimeoutClearTokenStorage(),
      authApi: RefreshingMeApi(),
    );
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await _waitForStartup(container);
    expect(container.read(authControllerProvider).user, isNotNull);

    await container.read(authControllerProvider.notifier).logout();

    expect(container.read(authControllerProvider).user, isNull);
    expect((container.read(authApiProvider) as RefreshingMeApi).logoutCount, 1);
  });

  test('clears local credentials when server logout fails', () async {
    final tokenStorage = StartupTokenStorage();
    final cache = StartupApiCache();
    final authApi = FailingLogoutApi();
    final container = _container(
      tokenStorage: tokenStorage,
      apiCache: cache,
      authApi: authApi,
    );
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await _waitForStartup(container);

    await container.read(authControllerProvider.notifier).logout();

    expect(authApi.logoutCount, 1);
    expect(tokenStorage.clearCount, 1);
    expect(cache.clearCount, 1);
    expect(container.read(authControllerProvider).user, isNull);
  });

  test('saves the replacement token after changing the password', () async {
    final tokenStorage = RecordingTokenStorage();
    final authApi = SecurityAuthApi();
    final container = _container(
      tokenStorage: tokenStorage,
      authApi: authApi,
    );
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await _waitForStartup(container);

    final error =
        await container.read(authControllerProvider.notifier).changePassword(
              currentPassword: 'current-password',
              newPassword: 'new-password',
            );

    expect(error, isNull);
    expect(authApi.changePasswordCount, 1);
    expect(tokenStorage.savedTokens, ['replacement-token']);
    expect(container.read(authControllerProvider).user?.email, 'user@test');
  });

  test('logs out locally when the replacement token cannot be saved', () async {
    final tokenStorage = FailingReplacementTokenStorage();
    final container = _container(
      tokenStorage: tokenStorage,
      authApi: SecurityAuthApi(),
    );
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await _waitForStartup(container);

    final error =
        await container.read(authControllerProvider.notifier).changePassword(
              currentPassword: 'current-password',
              newPassword: 'new-password',
            );

    expect(error, contains('重新登录'));
    expect(tokenStorage.clearCount, 1);
    expect(container.read(authControllerProvider).user, isNull);
  });

  test('clears the local session after logging out all devices', () async {
    final tokenStorage = StartupTokenStorage();
    final authApi = SecurityAuthApi();
    final container = _container(
      tokenStorage: tokenStorage,
      authApi: authApi,
    );
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await _waitForStartup(container);

    final error =
        await container.read(authControllerProvider.notifier).logoutAll();

    expect(error, isNull);
    expect(authApi.logoutAllCount, 1);
    expect(tokenStorage.clearCount, 1);
    expect(container.read(authControllerProvider).user, isNull);
  });

  test('keeps the current session when logout all fails', () async {
    final tokenStorage = StartupTokenStorage();
    final authApi = FailingLogoutAllApi();
    final container = _container(
      tokenStorage: tokenStorage,
      authApi: authApi,
    );
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await _waitForStartup(container);

    final error =
        await container.read(authControllerProvider.notifier).logoutAll();

    expect(error, isNotNull);
    expect(authApi.logoutAllCount, 1);
    expect(tokenStorage.clearCount, 0);
    expect(container.read(authControllerProvider).user, isNotNull);
  });

  test('clears the local session after deleting the remote account', () async {
    final tokenStorage = StartupTokenStorage();
    final cache = StartupApiCache();
    final authApi = SecurityAuthApi();
    final container = _container(
      tokenStorage: tokenStorage,
      apiCache: cache,
      authApi: authApi,
    );
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await _waitForStartup(container);

    final error =
        await container.read(authControllerProvider.notifier).deleteAccount(
              currentPassword: 'current-password',
            );

    expect(error, isNull);
    expect(authApi.deleteAccountPasswords, ['current-password']);
    expect(tokenStorage.clearCount, 1);
    expect(cache.clearCount, 1);
    expect(container.read(authControllerProvider).user, isNull);
  });

  test('keeps the current session when remote account deletion fails',
      () async {
    final tokenStorage = StartupTokenStorage();
    final authApi = FailingDeleteAccountApi();
    final container = _container(
      tokenStorage: tokenStorage,
      authApi: authApi,
    );
    addTearDown(container.dispose);
    container.read(authControllerProvider);
    await _waitForStartup(container);

    final error =
        await container.read(authControllerProvider.notifier).deleteAccount(
              currentPassword: 'current-password',
            );

    expect(error, isNotNull);
    expect(authApi.deleteAccountPasswords, ['current-password']);
    expect(tokenStorage.clearCount, 0);
    expect(container.read(authControllerProvider).user, isNotNull);
  });
}

ProviderContainer _container({
  required TokenStorage tokenStorage,
  required AuthApi authApi,
  StartupApiCache? apiCache,
}) {
  return ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(tokenStorage),
      apiCacheProvider.overrideWithValue(apiCache ?? StartupApiCache()),
      authApiProvider.overrideWithValue(authApi),
    ],
  );
}

Future<void> _waitForStartup(ProviderContainer container) async {
  for (var attempt = 0; attempt < 20; attempt += 1) {
    await Future<void>.delayed(Duration.zero);
    if (!container.read(authControllerProvider).loading) {
      return;
    }
  }
  fail('Authentication startup did not finish.');
}

Future<void> _waitForAuthCalls(RefreshingMeApi api, int count) async {
  for (var attempt = 0; attempt < 20; attempt += 1) {
    await Future<void>.delayed(Duration.zero);
    if (api.callCount >= count) {
      return;
    }
  }
  fail('Current-user revalidation did not finish.');
}

class StartupTokenStorage extends TokenStorage {
  StartupTokenStorage() : super(const FlutterSecureStorage());

  int clearCount = 0;

  @override
  Future<String?> readToken() async => 'stored-token';

  @override
  Future<void> clear() async {
    clearCount += 1;
  }
}

class RecordingTokenStorage extends StartupTokenStorage {
  final List<String> savedTokens = [];

  @override
  Future<void> saveToken(String token) async {
    savedTokens.add(token);
  }
}

class FailingReplacementTokenStorage extends StartupTokenStorage {
  @override
  Future<void> saveToken(String token) async {
    throw TimeoutException('replacement token save timed out');
  }
}

class StartupApiCache extends ApiCache {
  StartupApiCache() : super(const FlutterSecureStorage());

  int clearCount = 0;

  @override
  Future<void> clear() async {
    clearCount += 1;
  }
}

class FailingMeApi extends AuthApi {
  FailingMeApi({required this.statusCode}) : super(Dio());

  final int statusCode;

  @override
  Future<User> me() async {
    final options = RequestOptions(path: '/auth/me');
    throw DioException(
      requestOptions: options,
      response: Response<void>(
        requestOptions: options,
        statusCode: statusCode,
      ),
    );
  }
}

class RefreshingMeApi extends AuthApi {
  RefreshingMeApi() : super(Dio());

  int callCount = 0;
  int logoutCount = 0;

  @override
  Future<User> me() async {
    callCount += 1;
    return User(
      id: 'user-id',
      email: callCount == 1 ? 'cached@test' : 'live@test',
    );
  }

  @override
  Future<void> logout() async {
    logoutCount += 1;
  }
}

class FailingLogoutApi extends RefreshingMeApi {
  @override
  Future<void> logout() async {
    logoutCount += 1;
    final options = RequestOptions(path: '/auth/logout');
    throw DioException(
      requestOptions: options,
      type: DioExceptionType.connectionError,
    );
  }
}

class SecurityAuthApi extends RefreshingMeApi {
  int changePasswordCount = 0;
  int logoutAllCount = 0;
  final List<String> deleteAccountPasswords = [];

  @override
  Future<AuthResult> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    changePasswordCount += 1;
    return const AuthResult(
      token: 'replacement-token',
      user: User(id: 'user-id', email: 'user@test'),
    );
  }

  @override
  Future<void> logoutAll() async {
    logoutAllCount += 1;
  }

  @override
  Future<void> deleteAccount({required String currentPassword}) async {
    deleteAccountPasswords.add(currentPassword);
  }
}

class FailingLogoutAllApi extends SecurityAuthApi {
  @override
  Future<void> logoutAll() async {
    logoutAllCount += 1;
    final options = RequestOptions(path: '/auth/logout-all');
    throw DioException(
      requestOptions: options,
      type: DioExceptionType.connectionError,
    );
  }
}

class FailingDeleteAccountApi extends SecurityAuthApi {
  @override
  Future<void> deleteAccount({required String currentPassword}) async {
    deleteAccountPasswords.add(currentPassword);
    final options = RequestOptions(path: '/auth/account');
    throw DioException(
      requestOptions: options,
      type: DioExceptionType.connectionError,
    );
  }
}

class FailingSaveTokenStorage extends StartupTokenStorage {
  @override
  Future<String?> readToken() async => null;

  @override
  Future<void> saveToken(String token) async {
    throw TimeoutException('token save timed out');
  }
}

class TimeoutClearTokenStorage extends StartupTokenStorage {
  @override
  Future<void> clear() async {
    throw TimeoutException('token delete timed out');
  }
}

class SuccessfulLoginApi extends AuthApi {
  SuccessfulLoginApi() : super(Dio());

  @override
  Future<AuthResult> login({
    required String email,
    required String password,
  }) async {
    return const AuthResult(
      token: 'new-token',
      user: User(id: 'user-id', email: 'user@test'),
    );
  }
}
