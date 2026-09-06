import 'package:dio/dio.dart';

import '../models/auth_config.dart';
import '../models/auth_session.dart';
import '../models/user.dart';

class AuthResult {
  const AuthResult({required this.token, required this.user});

  final String token;
  final User user;
}

class AuthApi {
  const AuthApi(this._dio);

  final Dio _dio;

  Future<AuthConfig> config() async {
    final response = await _dio.get<Map<String, dynamic>>('/auth/config');
    return AuthConfig.fromJson(response.data!);
  }

  Future<AuthResult> login(
      {required String email, required String password}) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/auth/login',
      data: {'email': email, 'password': password},
    );
    final data = response.data!;
    return AuthResult(
      token: data['access_token'] as String,
      user: User.fromJson(data['user'] as Map<String, dynamic>),
    );
  }

  Future<AuthResult> register({
    required String email,
    required String password,
    String? name,
    String? inviteCode,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/auth/register',
      data: {
        'email': email,
        'password': password,
        if (name != null && name.trim().isNotEmpty) 'name': name.trim(),
        if (inviteCode != null && inviteCode.trim().isNotEmpty)
          'invite_code': inviteCode.trim(),
      },
    );
    final data = response.data!;
    return AuthResult(
      token: data['access_token'] as String,
      user: User.fromJson(data['user'] as Map<String, dynamic>),
    );
  }

  Future<User> me() async {
    final response = await _dio.get<Map<String, dynamic>>('/auth/me');
    return User.fromJson(response.data!);
  }

  Future<void> logout() async {
    await _dio.post<void>('/auth/logout');
  }

  Future<void> logoutAll() async {
    await _dio.post<void>('/auth/logout-all');
  }

  Future<void> deleteAccount({required String currentPassword}) async {
    await _dio.delete<void>(
      '/auth/account',
      data: {
        'current_password': currentPassword,
        'confirmation': 'DELETE',
      },
    );
  }

  Future<List<AuthSessionInfo>> sessions() async {
    final response = await _dio.get<List<dynamic>>('/auth/sessions');
    return response.data!
        .map(
          (item) => AuthSessionInfo.fromJson(item as Map<String, dynamic>),
        )
        .toList();
  }

  Future<void> revokeSession(String id) async {
    await _dio.delete<void>('/auth/sessions/$id');
  }

  Future<AuthResult> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/auth/change-password',
      data: {
        'current_password': currentPassword,
        'new_password': newPassword,
      },
    );
    final data = response.data!;
    return AuthResult(
      token: data['access_token'] as String,
      user: User.fromJson(data['user'] as Map<String, dynamic>),
    );
  }
}
