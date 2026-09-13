import 'dart:convert';

import 'package:dio/dio.dart';

import '../models/chat.dart';

const messageHistoryPageSize = 50;

class ChatApi {
  const ChatApi(this._dio);

  final Dio _dio;

  Future<ChatResponse> query(
    String question, {
    String? conversationId,
    List<String> tags = const [],
    List<String> documentIds = const [],
    List<String> sourceTypes = const [],
    int? recentDays,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/chat/query',
      data: {
        'question': question,
        'conversation_id': ?conversationId,
        'scope': {
          'document_ids': documentIds,
          'tags': tags,
          'source_types': sourceTypes,
          'recent_days': ?recentDays,
        },
      },
    );
    return ChatResponse.fromJson(response.data!);
  }

  /// Stream chat answer as SSE events from `/chat/query/stream`.
  ///
  /// Falls back to non-streaming [query] if the stream endpoint is unavailable.
  Stream<ChatStreamEvent> queryStream(
    String question, {
    String? conversationId,
    List<String> tags = const [],
    List<String> documentIds = const [],
    List<String> sourceTypes = const [],
    int? recentDays,
  }) async* {
    try {
      final response = await _dio.post<ResponseBody>(
        '/chat/query/stream',
        data: {
          'question': question,
          'conversation_id': ?conversationId,
          'scope': {
            'document_ids': documentIds,
            'tags': tags,
            'source_types': sourceTypes,
            'recent_days': ?recentDays,
          },
        },
        options: Options(
          responseType: ResponseType.stream,
          receiveTimeout: const Duration(minutes: 3),
        ),
      );
      final body = response.data;
      if (body == null) {
        throw StateError('empty stream body');
      }
      yield* _parseSse(body);
    } on DioException catch (error) {
      final status = error.response?.statusCode;
      if (status == 404 || status == 405) {
        final fallback = await query(
          question,
          conversationId: conversationId,
          tags: tags,
          documentIds: documentIds,
          sourceTypes: sourceTypes,
          recentDays: recentDays,
        );
        yield ChatStreamEvent.done(
          conversationId: fallback.conversationId,
          answer: fallback.answer,
          citations: fallback.citations,
          suggestedQuestions: fallback.suggestedQuestions,
        );
        return;
      }
      rethrow;
    }
  }

  Stream<ChatStreamEvent> _parseSse(ResponseBody body) async* {
    final buffer = StringBuffer();
    await for (final chunk in body.stream) {
      buffer.write(utf8.decode(chunk, allowMalformed: true));
      var content = buffer.toString();
      var separator = content.indexOf('\n\n');
      while (separator >= 0) {
        final frame = content.substring(0, separator);
        content = content.substring(separator + 2);
        final event = _parseSseFrame(frame);
        if (event != null) {
          yield event;
        }
        separator = content.indexOf('\n\n');
      }
      buffer
        ..clear()
        ..write(content);
    }
    final trailing = buffer.toString().trim();
    if (trailing.isNotEmpty) {
      final event = _parseSseFrame(trailing);
      if (event != null) {
        yield event;
      }
    }
  }

  ChatStreamEvent? _parseSseFrame(String frame) {
    String? eventType;
    final dataLines = <String>[];
    for (final rawLine in frame.split('\n')) {
      final line = rawLine.trimRight();
      if (line.isEmpty || line.startsWith(':')) {
        continue;
      }
      if (line.startsWith('event:')) {
        eventType = line.substring(6).trim();
      } else if (line.startsWith('data:')) {
        dataLines.add(line.substring(5).trimLeft());
      }
    }
    if (dataLines.isEmpty) {
      return null;
    }
    final raw = dataLines.join('\n');
    Map<String, dynamic> json;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) {
        return null;
      }
      json = decoded;
    } catch (_) {
      return null;
    }
    final type = eventType ?? json['type']?.toString() ?? 'message';
    return ChatStreamEvent.fromJson(type, json);
  }

  Future<List<ConversationSummary>> listConversations() async {
    final page = await listConversationPage();
    return page.items;
  }

  Future<ConversationPage> listConversationPage({
    int page = 1,
    int pageSize = 20,
    String? keyword,
  }) async {
    final response = await _dio.get<Map<String, dynamic>>(
      '/chat/conversations',
      queryParameters: {
        'page': page,
        'page_size': pageSize,
        if (keyword != null && keyword.isNotEmpty) 'keyword': keyword,
      },
    );
    return ConversationPage.fromJson(response.data!);
  }

  Future<ConversationSummary> updateConversationTitle(
    String conversationId, {
    required String title,
  }) async {
    final response = await _dio.patch<Map<String, dynamic>>(
      '/chat/conversations/$conversationId',
      data: {'title': title},
    );
    return ConversationSummary.fromJson(response.data!);
  }

  Future<ConversationSummary> getConversation(String conversationId) async {
    final response = await _dio.get<Map<String, dynamic>>(
      '/chat/conversations/$conversationId',
    );
    return ConversationSummary.fromJson(response.data!);
  }

  Future<void> deleteConversation(String conversationId) async {
    await _dio.delete<void>('/chat/conversations/$conversationId');
  }

  Future<MessageHistoryPage> listMessagePage(
    String conversationId, {
    String? cursor,
  }) async {
    final response = await _dio.get<Map<String, dynamic>>(
      '/chat/conversations/$conversationId/messages/recent',
      queryParameters: {
        'page_size': messageHistoryPageSize,
        'cursor': ?cursor,
      },
    );
    return MessageHistoryPage.fromJson(response.data!);
  }

  Future<List<ChatHistoryMessage>> listMessages(String conversationId) async {
    final page = await listMessagePage(conversationId);
    return page.items;
  }
}

class MessageHistoryPage {
  const MessageHistoryPage({
    required this.items,
    required this.nextCursor,
  });

  final List<ChatHistoryMessage> items;
  final String? nextCursor;

  factory MessageHistoryPage.fromJson(Map<String, dynamic> json) {
    final items = json['items'] as List<dynamic>;
    return MessageHistoryPage(
      items: items
          .map(
            (item) => ChatHistoryMessage.fromJson(item as Map<String, dynamic>),
          )
          .toList(),
      nextCursor: json['next_cursor'] as String?,
    );
  }
}

class ConversationPage {
  const ConversationPage({
    required this.items,
    required this.total,
    required this.page,
    required this.pageSize,
  });

  final List<ConversationSummary> items;
  final int total;
  final int page;
  final int pageSize;

  int get totalPages => total == 0 ? 1 : (total + pageSize - 1) ~/ pageSize;
  bool get hasPrevious => page > 1;
  bool get hasNext => page < totalPages;

  factory ConversationPage.fromJson(Map<String, dynamic> json) {
    final items = json['items'] as List<dynamic>;
    return ConversationPage(
      items: items
          .map((item) =>
              ConversationSummary.fromJson(item as Map<String, dynamic>))
          .toList(),
      total: json['total'] as int,
      page: json['page'] as int,
      pageSize: json['page_size'] as int,
    );
  }
}
