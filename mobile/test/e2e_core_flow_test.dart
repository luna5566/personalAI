// 全栈端到端流程测试：登录 → 建笔记 → 提问 → 点开引用。
//
// 通过自定义 Dio HttpClientAdapter 在内存中返回固定响应：不依赖设备或
// 模拟器，CI 的 `flutter test` 即可执行；除 TCP 传输层外，认证拦截器、
// 缓存层、Provider 链路、路由导航与页面渲染全部走真实实现。
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:personal_ai_mobile/app.dart';
import 'package:personal_ai_mobile/core/network/api_client.dart';

const _documentId = '11111111-1111-1111-1111-111111111111';
const _documentTitle = '光合作用笔记';
const _documentContent = '光合作用是植物利用光能将二氧化碳和水转化为有机物的过程。';

class _FakeApiResult {
  const _FakeApiResult(this.status, this.json);

  final int status;
  final Map<String, dynamic> json;
}

/// 按 method + path 路由的假后端；未匹配的请求记录下来由测试断言。
class _FakeApiAdapter implements HttpClientAdapter {
  _FakeApiAdapter(this.routes, this.unmatched);

  final Map<String, _FakeApiResult Function(String body)> routes;
  final List<String> unmatched;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final body = await utf8.decodeStream(requestStream ?? const Stream.empty());
    final route = routes['${options.method} ${options.uri.path}'];
    if (route == null) {
      unmatched.add('${options.method} ${options.uri.path}');
      return ResponseBody.fromString(
        jsonEncode({'detail': 'Not Found'}),
        404,
        headers: const {
          Headers.contentTypeHeader: <String>[Headers.jsonContentType],
        },
      );
    }
    final result = route(body);
    return ResponseBody.fromString(
      jsonEncode(result.json),
      result.status,
      headers: {
        Headers.contentTypeHeader: <String>[Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  late _FakeApiAdapter adapter;
  late List<String> unmatchedRequests;

  Map<String, dynamic> documentJson() => {
        'id': _documentId,
        'title': _documentTitle,
        'source_type': 'note',
        'status': 'indexed',
        'tags': <String>['植物'],
        'summary': '关于光合作用的笔记',
        'content': _documentContent,
        'content_offset': 0,
        'content_length': _documentContent.length,
        'content_truncated': false,
        'created_at': '2026-09-13T10:00:00Z',
        'updated_at': '2026-09-13T10:00:00Z',
      };

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    unmatchedRequests = <String>[];
    final documentPage = {
      'items': <Map<String, dynamic>>[documentJson()],
      'total': 1,
      'page': 1,
      'page_size': 20,
    };
    adapter = _FakeApiAdapter(
      {
        'GET /api/auth/config': (_) => const _FakeApiResult(200, {
              'registration_enabled': true,
              'registration_invite_required': false,
            }),
        'POST /api/auth/login': (_) => const _FakeApiResult(200, {
              'access_token': 'e2e-access-token',
              'user': {
                'id': '00000000-0000-0000-0000-00000000000e',
                'email': 'e2e@example.com',
                'name': '端到端用户',
                'is_admin': true,
              },
            }),
        'GET /api/documents': (_) => _FakeApiResult(200, documentPage),
        'GET /api/documents/stats': (_) => const _FakeApiResult(200, {
              'total': 1,
              'indexed': 1,
              'processing': 0,
              'failed': 0,
              'cancelled': 0,
              'storage_bytes': 128,
            }),
        'GET /api/documents/$_documentId': (_) =>
            _FakeApiResult(200, documentJson()),
        'GET /api/documents/$_documentId/related': (_) =>
            const _FakeApiResult(200, {
              'items': <Map<String, dynamic>>[],
              'total': 0,
            }),
        'POST /api/documents/note': (_) => _FakeApiResult(200, documentJson()),
        'GET /api/tags': (_) => const _FakeApiResult(200, {
              'items': <Map<String, dynamic>>[
                {'id': 'tag-1', 'name': '植物'},
              ],
              'total': 1,
              'page': 1,
              'page_size': 50,
            }),
        'GET /api/chat/conversations': (_) => const _FakeApiResult(200, {
              'items': <Map<String, dynamic>>[],
              'total': 0,
              'page': 1,
              'page_size': 20,
            }),
        'POST /api/chat/query': (_) => const _FakeApiResult(200, {
              'conversation_id': 'conv-1',
              'answer':
                  '光合作用把光能转化为化学能。这是一段足够长的回答，用来验证回答区域渲染正常。',
              'citations': <Map<String, dynamic>>[
                {
                  'document_id': _documentId,
                  'document_title': _documentTitle,
                  'text': _documentContent,
                  'score': 0.9,
                  'chunk_id': 'chunk-1',
                  'chunk_index': 0,
                  'start_offset': 0,
                  'end_offset': _documentContent.length,
                  'source_type': 'note',
                },
              ],
              'suggested_questions': <String>['什么是暗反应？'],
            }),
        'POST /api/chat/query/stream': (_) =>
            const _FakeApiResult(404, {'detail': 'Not Found'}),
      },
      unmatchedRequests,
    );
  });

  testWidgets('login → create note → ask question → open citation',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          dioProvider.overrideWith(
            (ref) => Dio(
              BaseOptions(
                baseUrl: 'http://fake-api.local/api',
                connectTimeout: const Duration(seconds: 10),
                receiveTimeout: const Duration(seconds: 30),
              ),
            )..httpClientAdapter = adapter,
          ),
        ],
        child: const PersonalAiApp(),
      ),
    );
    await tester.pumpAndSettle();

    // 1. 登录
    expect(find.text('登录'), findsWidgets);
    await tester.enterText(
      find.widgetWithText(TextField, '邮箱').first,
      'e2e@example.com',
    );
    await tester.enterText(
      find.widgetWithText(TextField, '密码').first,
      'secret-123',
    );
    await tester.tap(find.widgetWithText(FilledButton, '登录'));
    await tester.pumpAndSettle();
    expect(find.text('首页'), findsWidgets);

    // 2. 资料 → 新建笔记
    await tester.tap(find.text('资料'));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('记一条'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextField, '标题').first,
      _documentTitle,
    );
    await tester.enterText(
      find.widgetWithText(TextField, '内容').first,
      _documentContent,
    );
    await tester.tap(find.widgetWithText(FilledButton, '保存'));
    await tester.pumpAndSettle();
    expect(find.text(_documentTitle), findsWidgets);

    // 3. 提问
    await tester.tap(find.text('提问'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextField, '问我的资料'),
      '光合作用是怎么发生的？',
    );
    await tester.tap(find.byTooltip('发送'));
    await tester.pumpAndSettle();

    // 回答与引用来源都渲染出来
    expect(find.textContaining('光能转化为化学能'), findsOneWidget);
    expect(find.text('引用来源'), findsOneWidget);
    expect(find.textContaining(_documentTitle), findsWidgets);
    expect(find.textContaining('相关度'), findsOneWidget);

    // 4. 点开引用 → 资料详情并高亮引用片段
    await tester.tap(find.textContaining(_documentTitle).last);
    await tester.pumpAndSettle();
    expect(
      find.textContaining(_documentContent, findRichText: true),
      findsWidgets,
      reason: '资料详情应展示引用片段对应的正文',
    );

    expect(unmatchedRequests, isEmpty);
  });
}
