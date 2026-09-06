import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/chat/data/chat_api.dart';
import 'package:personal_ai_mobile/features/documents/data/documents_api.dart';
import 'package:personal_ai_mobile/features/tags/data/tags_api.dart';

void main() {
  test('bounds catalog selectors and the recent message page', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = PaginatedAdapter();
    dio.httpClientAdapter = adapter;

    final tags = await TagsApi(dio).listTags();
    final messagePage = await ChatApi(dio).listMessagePage('conversation-id');
    final documents = await DocumentsApi(dio).listDocumentsPage(
      pageSize: 100,
      status: 'indexed',
    );

    expect(tags.length, 100);
    expect(tags.last.name, 'tag-100');
    expect(messagePage.items.length, 50);
    expect(messagePage.items.first.content, 'message-52');
    expect(messagePage.items.last.content, 'message-101');
    expect(messagePage.nextCursor, 'messages-page-2');
    expect(documents.items.length, 100);
    expect(documents.items.last.title, 'document-100');
    expect(documents.total, 101);
    expect(adapter.tagRequests, 1);
    expect(adapter.messageRequests, 1);
    expect(adapter.messageCursors, [null]);
    expect(adapter.documentRequests, 1);
  });

  test('loads an older message page only for an explicit cursor', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = PaginatedAdapter();
    dio.httpClientAdapter = adapter;
    final api = ChatApi(dio);

    final recent = await api.listMessagePage('conversation-id');
    final older = await api.listMessagePage(
      'conversation-id',
      cursor: recent.nextCursor,
    );

    expect(older.items.single.content, 'message-51');
    expect(older.nextCursor, isNull);
    expect(adapter.messageRequests, 2);
    expect(adapter.messageCursors, [null, 'messages-page-2']);
  });
}

class PaginatedAdapter implements HttpClientAdapter {
  int tagRequests = 0;
  int messageRequests = 0;
  int documentRequests = 0;
  final List<String?> messageCursors = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final cursor = options.queryParameters['cursor'] as String?;
    final page = cursor == null ? 1 : 2;
    if (options.path == '/tags') {
      expect(options.queryParameters['page_size'], 100);
      expect(options.queryParameters['page'], 1);
      tagRequests += 1;
      final items = List.generate(100, (index) {
        final number = index + 1;
        return {
          'id': 'tag-$number',
          'name': 'tag-$number',
          'created_at': '2026-07-17T00:00:00Z',
        };
      });
      return _jsonResponse(
        items,
        extraHeaders: {
          'x-total-count': ['101'],
        },
      );
    }

    if (options.path == '/documents') {
      expect(options.queryParameters['page_size'], 100);
      expect(options.queryParameters['page'], 1);
      documentRequests += 1;
      expect(options.queryParameters['status'], 'indexed');
      final items = List.generate(100, (index) {
        final number = index + 1;
        return {
          'id': 'document-$number',
          'title': 'document-$number',
          'source_type': 'note',
          'status': 'indexed',
          'tags': <dynamic>[],
        };
      });
      return _jsonResponse({
        'items': items,
        'total': 101,
        'page': 1,
        'page_size': 100,
      });
    }

    expect(
      options.path,
      '/chat/conversations/conversation-id/messages/recent',
    );
    expect(options.queryParameters['page_size'], 50);
    messageRequests += 1;
    messageCursors.add(cursor);
    final start = page == 1 ? 52 : 51;
    final count = page == 1 ? 50 : 1;
    final items = List.generate(count, (index) {
      final number = start + index;
      return {
        'id': 'message-$number',
        'conversation_id': 'conversation-id',
        'role': number.isOdd ? 'user' : 'assistant',
        'content': 'message-$number',
        'citations': <dynamic>[],
        'created_at': '2026-07-17T00:00:00Z',
      };
    });
    return _jsonResponse({
      'items': items,
      'next_cursor': page == 1 ? 'messages-page-2' : null,
    });
  }

  ResponseBody _jsonResponse(
    Object data, {
    Map<String, List<String>> extraHeaders = const {},
  }) {
    return ResponseBody.fromString(
      jsonEncode(data),
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
        ...extraHeaders,
      },
    );
  }

  @override
  void close({bool force = false}) {}
}
