import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/cache_state.dart';
import '../../../core/network/user_error_message.dart';
import '../data/auth_api.dart';
import '../models/auth_config.dart';
import '../models/auth_session.dart';
import '../models/user.dart';

final authApiProvider = Provider<AuthApi>((ref) {
  ref.watch(cacheRevalidationProvider);
  return AuthApi(ref.watch(dioProvider));
});

final authSessionsProvider =
    FutureProvider.autoDispose<List<AuthSessionInfo>>((ref) {
  return ref.watch(authApiProvider).sessions();
});

final authConfigProvider = FutureProvider.autoDispose<AuthConfig>((ref) {
  return ref.watch(authApiProvider).config();
});

final authControllerProvider =
    StateNotifierProvider<AuthController, AuthState>((ref) {
  final controller = AuthController(ref);
  ref.listen<int>(authSessionInvalidationProvider, (_, __) {
    controller.expireSession();
  });
  ref.listen<int>(cacheRevalidationProvider, (_, __) {
    controller.refreshCurrentUser();
  });
  return controller;
});

class AuthState {
  const AuthState({
    this.user,
    this.loading = false,
    this.initializing = false,
    this.error,
    this.startupFailed = false,
  });

  final User? user;
  final bool loading;
  final bool initializing;
  final String? error;
  final bool startupFailed;

  AuthState copyWith({
    User? user,
    bool? loading,
    bool? initializing,
    String? error,
    bool clearError = false,
    bool? startupFailed,
  }) {
    return AuthState(
      user: user ?? this.user,
      loading: loading ?? this.loading,
      initializing: initializing ?? this.initializing,
      error: clearError ? null : error ?? this.error,
      startupFailed: startupFailed ?? this.startupFailed,
    );
  }
}

class AuthController extends StateNotifier<AuthState> {
  AuthController(this._ref)
      : super(const AuthState(loading: true, initializing: true)) {
    loadCurrentUser();
  }

  final Ref _ref;

  Future<void> loadCurrentUser() async {
    state = const AuthState(loading: true, initializing: true);
    final tokenStorage = _ref.read(tokenStorageProvider);
    String? token;
    try {
      token =
          await tokenStorage.readToken().timeout(const Duration(seconds: 2));
    } catch (_) {
      state = const AuthState(
        error: '无法读取本机登录状态，请重试。',
        startupFailed: true,
      );
      return;
    }
    if (token == null || token.isEmpty) {
      state = const AuthState();
      return;
    }

    state = const AuthState(loading: true, initializing: true);
    try {
      final user = await _ref.read(authApiProvider).me();
      state = AuthState(user: user);
    } catch (error) {
      if (_isUnauthorized(error)) {
        await tokenStorage.clear();
        await _ref.read(apiCacheProvider).clear();
        state = const AuthState();
        return;
      }
      state = const AuthState(
        error: '暂时无法恢复登录状态，请检查网络或后端服务后重试。',
        startupFailed: true,
      );
    }
  }

  Future<void> refreshCurrentUser() async {
    if (state.user == null || state.loading) {
      return;
    }
    try {
      final user = await _ref.read(authApiProvider).me();
      if (mounted) {
        state = AuthState(user: user);
      }
    } catch (error) {
      if (_isUnauthorized(error)) {
        await _ref.read(tokenStorageProvider).clear();
        await _ref.read(apiCacheProvider).clear();
        if (mounted) {
          state = const AuthState();
        }
      }
      // Temporary failures preserve the current user and cache warning.
    }
  }

  Future<void> login(String email, String password) async {
    state = state.copyWith(loading: true, clearError: true);
    try {
      final result = await _ref
          .read(authApiProvider)
          .login(email: email, password: password);
      await _ref.read(apiCacheProvider).clear();
      await _ref.read(tokenStorageProvider).saveToken(result.token);
      state = AuthState(user: result.user);
    } catch (error) {
      state = AuthState(
        error: userFacingErrorMessage(
          error,
          fallback: '登录失败，请稍后重试',
        ),
      );
    }
  }

  Future<void> register({
    required String email,
    required String password,
    String? name,
    String? inviteCode,
  }) async {
    state = state.copyWith(loading: true, clearError: true);
    try {
      final result = await _ref.read(authApiProvider).register(
            email: email,
            password: password,
            name: name,
            inviteCode: inviteCode,
          );
      await _ref.read(apiCacheProvider).clear();
      await _ref.read(tokenStorageProvider).saveToken(result.token);
      state = AuthState(user: result.user);
    } catch (error) {
      state = AuthState(
        error: userFacingErrorMessage(
          error,
          fallback: '注册失败，请稍后重试',
        ),
      );
    }
  }

  Future<void> logout() async {
    try {
      await _ref.read(authApiProvider).logout().timeout(
            const Duration(seconds: 2),
          );
    } catch (_) {
      // Offline logout still removes local credentials and ends this session.
    }
    try {
      await _clearLocalSession();
    } catch (_) {
      // The in-memory session must still end if secure storage is unavailable.
    } finally {
      state = const AuthState();
    }
  }

  Future<String?> logoutAll() async {
    final previousUser = state.user;
    state = state.copyWith(loading: true, clearError: true);
    try {
      await _ref.read(authApiProvider).logoutAll();
    } catch (error) {
      if (_isUnauthorized(error)) {
        try {
          await _clearLocalSession();
        } catch (_) {
          // The server has already rejected this session.
        }
        state = const AuthState();
        return null;
      }
      final message = userFacingErrorMessage(
        error,
        fallback: '退出所有设备失败，请稍后重试',
      );
      state = AuthState(user: previousUser, error: message);
      return message;
    }

    try {
      await _clearLocalSession();
    } catch (_) {
      // Remote sessions are revoked even if local secure storage is unavailable.
    } finally {
      state = const AuthState();
    }
    return null;
  }

  Future<String?> deleteAccount({required String currentPassword}) async {
    final previousUser = state.user;
    state = state.copyWith(loading: true, clearError: true);
    try {
      await _ref.read(authApiProvider).deleteAccount(
            currentPassword: currentPassword,
          );
    } catch (error) {
      if (_isUnauthorized(error)) {
        try {
          await _clearLocalSession();
        } catch (_) {
          // The server has already rejected this session.
        }
        state = const AuthState();
        return '登录状态已失效，请重新登录';
      }
      final message = userFacingErrorMessage(
        error,
        fallback: '删除账号失败，请稍后重试',
      );
      state = AuthState(user: previousUser, error: message);
      return message;
    }

    try {
      await _clearLocalSession();
    } catch (_) {
      // The remote account is gone even if local secure storage is unavailable.
    } finally {
      state = const AuthState();
    }
    return null;
  }

  Future<String?> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final previousUser = state.user;
    state = state.copyWith(loading: true, clearError: true);
    AuthResult result;
    try {
      result = await _ref.read(authApiProvider).changePassword(
            currentPassword: currentPassword,
            newPassword: newPassword,
          );
    } catch (error) {
      if (_isUnauthorized(error)) {
        try {
          await _clearLocalSession();
        } catch (_) {
          // The server has already rejected this session.
        }
        state = const AuthState();
        return '登录状态已失效，请重新登录';
      }
      final message = userFacingErrorMessage(
        error,
        fallback: '修改密码失败，请稍后重试',
      );
      state = AuthState(user: previousUser, error: message);
      return message;
    }

    try {
      await _ref.read(apiCacheProvider).clear();
      await _ref.read(tokenStorageProvider).saveToken(result.token);
    } catch (_) {
      try {
        await _clearLocalSession();
      } catch (_) {
        // The in-memory session still ends when local cleanup cannot finish.
      }
      const message = '密码已修改，但无法保存新的登录状态，请重新登录';
      state = const AuthState(error: message);
      return message;
    }

    state = AuthState(user: result.user);
    return null;
  }

  void expireSession() {
    state = const AuthState();
  }

  bool _isUnauthorized(Object error) {
    return error is DioException && error.response?.statusCode == 401;
  }

  Future<void> _clearLocalSession() async {
    await Future.wait([
      _ref.read(tokenStorageProvider).clear(),
      _ref.read(apiCacheProvider).clear(),
    ]);
  }
}
