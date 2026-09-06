import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/auth/data/registration_invites_api.dart';

void main() {
  test('lists paginated registration invites with status and timestamps',
      () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = RegistrationInvitesAdapter();
    dio.httpClientAdapter = adapter;

    final page = await RegistrationInvitesApi(dio).list(
      page: 2,
      pageSize: 10,
      status: 'active',
    );

    expect(adapter.requestedPage, 2);
    expect(adapter.requestedPageSize, 10);
    expect(adapter.requestedStatus, 'active');
    expect(page.total, 11);
    expect(page.hasPrevious, isTrue);
    expect(page.hasNext, isFalse);
    expect(page.items.single.status, 'active');
    expect(page.items.single.canRevoke, isTrue);
    expect(page.items.single.createdAt, DateTime.utc(2026, 7, 17, 12));
  });

  test('creates and revokes registration invites', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = RegistrationInvitesAdapter();
    dio.httpClientAdapter = adapter;
    final api = RegistrationInvitesApi(dio);

    final created = await api.create(validHours: 24);
    await api.revoke('invite-id');

    expect(adapter.createdValidHours, 24);
    expect(created.code, 'raw-code-shown-once');
    expect(created.invite.status, 'active');
    expect(adapter.revokedIds, ['invite-id']);
  });
}

class RegistrationInvitesAdapter implements HttpClientAdapter {
  int? requestedPage;
  int? requestedPageSize;
  String? requestedStatus;
  int? createdValidHours;
  final List<String> revokedIds = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    if (options.method == 'DELETE') {
      revokedIds.add(options.path.split('/').last);
      return ResponseBody.fromString('', 204);
    }
    if (options.method == 'POST') {
      final bytes = await requestStream!.fold<List<int>>(
        <int>[],
        (buffer, chunk) => buffer..addAll(chunk),
      );
      final body = jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
      createdValidHours = body['valid_hours'] as int;
      return _jsonResponse({
        'id': 'created-id',
        'code': 'raw-code-shown-once',
        'status': 'active',
        'created_at': '2026-07-17T12:00:00Z',
        'expires_at': '2026-07-18T12:00:00Z',
        'used_at': null,
        'revoked_at': null,
      }, 201);
    }
    requestedPage = options.queryParameters['page'] as int;
    requestedPageSize = options.queryParameters['page_size'] as int;
    requestedStatus = options.queryParameters['status'] as String;
    return _jsonResponse({
      'items': [
        {
          'id': 'invite-id',
          'status': 'active',
          'created_at': '2026-07-17T12:00:00Z',
          'expires_at': '2026-07-18T12:00:00Z',
          'used_at': null,
          'revoked_at': null,
        },
      ],
      'total': 11,
      'page': 2,
      'page_size': 10,
    }, 200);
  }

  ResponseBody _jsonResponse(Object body, int statusCode) {
    return ResponseBody.fromString(
      jsonEncode(body),
      statusCode,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}
