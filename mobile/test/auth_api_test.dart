import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/auth/data/auth_api.dart';

void main() {
  test('loads public authentication configuration', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = AuthSessionsAdapter();
    dio.httpClientAdapter = adapter;

    final config = await AuthApi(dio).config();

    expect(adapter.operations, ['config']);
    expect(config.registrationEnabled, isTrue);
    expect(config.invitationRequired, isFalse);
  });

  test('sends a trimmed invitation code during registration', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = RegistrationAdapter();
    dio.httpClientAdapter = adapter;

    final result = await AuthApi(dio).register(
      email: 'invitee@example.com',
      password: 'secure-password',
      name: 'Invitee',
      inviteCode: '  one-time-code  ',
    );

    expect(result.token, 'access-token');
    expect(adapter.body?['invite_code'], 'one-time-code');
    expect(adapter.body?['email'], 'invitee@example.com');
  });

  test('loads authentication sessions with local timestamp accessors',
      () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = AuthSessionsAdapter();
    dio.httpClientAdapter = adapter;

    final sessions = await AuthApi(dio).sessions();

    expect(adapter.operations, ['list']);
    expect(sessions, hasLength(2));
    expect(sessions.first.id, 'current-session');
    expect(sessions.first.clientName, 'Personal AI Web');
    expect(sessions.first.isCurrent, isTrue);
    expect(
      sessions.first.createdAtLocal,
      DateTime.parse('2026-07-17T12:00:00Z').toLocal(),
    );
    expect(
      sessions.first.expiresAtLocal,
      DateTime.parse('2026-07-24T12:00:00Z').toLocal(),
    );
    expect(sessions.last.clientName, isNull);
    expect(sessions.last.isCurrent, isFalse);
  });

  test('revokes one authentication session through its dedicated endpoint',
      () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = AuthSessionsAdapter();
    dio.httpClientAdapter = adapter;

    await AuthApi(dio).revokeSession('other-session');

    expect(adapter.operations, ['revoke:other-session']);
  });

  test('deletes the account with password and explicit confirmation', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = AccountDeletionAdapter();
    dio.httpClientAdapter = adapter;

    await AuthApi(dio).deleteAccount(currentPassword: 'current-password');

    expect(adapter.method, 'DELETE');
    expect(adapter.path, '/auth/account');
    expect(adapter.body, {
      'current_password': 'current-password',
      'confirmation': 'DELETE',
    });
  });
}

class AccountDeletionAdapter implements HttpClientAdapter {
  String? method;
  String? path;
  Map<String, dynamic>? body;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    method = options.method;
    path = options.path;
    final bytes = await requestStream!.fold<List<int>>(
      <int>[],
      (buffer, chunk) => buffer..addAll(chunk),
    );
    body = jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
    return ResponseBody.fromString('', 204);
  }

  @override
  void close({bool force = false}) {}
}

class AuthSessionsAdapter implements HttpClientAdapter {
  final List<String> operations = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    if (options.path == '/auth/config') {
      operations.add('config');
      return ResponseBody.fromString(
        jsonEncode({
          'registration_enabled': true,
          'invitation_required': false,
        }),
        200,
        headers: {
          Headers.contentTypeHeader: ['application/json'],
        },
      );
    }
    if (options.method == 'DELETE') {
      operations.add('revoke:${options.path.split('/').last}');
      return ResponseBody.fromString('', 204);
    }
    expect(options.method, 'GET');
    expect(options.path, '/auth/sessions');
    operations.add('list');
    return ResponseBody.fromString(
      jsonEncode([
        {
          'id': 'current-session',
          'client_name': 'Personal AI Web',
          'created_at': '2026-07-17T12:00:00Z',
          'expires_at': '2026-07-24T12:00:00Z',
          'is_current': true,
        },
        {
          'id': 'other-session',
          'client_name': null,
          'created_at': '2026-07-17T11:00:00Z',
          'expires_at': '2026-07-24T11:00:00Z',
          'is_current': false,
        },
      ]),
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

class RegistrationAdapter implements HttpClientAdapter {
  Map<String, dynamic>? body;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    expect(options.method, 'POST');
    expect(options.path, '/auth/register');
    final bytes = await requestStream!.fold<List<int>>(
      <int>[],
      (buffer, chunk) => buffer..addAll(chunk),
    );
    body = jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
    return ResponseBody.fromString(
      jsonEncode({
        'access_token': 'access-token',
        'user': {
          'id': 'user-id',
          'email': 'invitee@example.com',
          'name': 'Invitee',
          'is_admin': false,
        },
      }),
      201,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}
