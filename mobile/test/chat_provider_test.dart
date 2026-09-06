import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/chat/data/chat_api.dart';
import 'package:personal_ai_mobile/features/chat/models/chat.dart';
import 'package:personal_ai_mobile/features/chat/providers/chat_provider.dart';

void main() {
  test('retries a failed question without duplicating the user message',
      () async {
    final api = RetryChatApi();
    final container = ProviderContainer(
      overrides: [chatApiProvider.overrideWithValue(api)],
    );
    addTearDown(container.dispose);
    final controller = container.read(chatControllerProvider.notifier);

    await controller.ask('失败后重试', tags: const ['测试']);

    expect(
      container.read(chatControllerProvider).error,
      '提问失败，请稍后重试',
    );
    expect(
      container.read(chatControllerProvider).error,
      isNot(contains('temporary failure')),
    );
    expect(container.read(chatControllerProvider).messages, hasLength(1));

    await controller.retryLast(tags: const ['测试']);

    final state = container.read(chatControllerProvider);
    expect(api.queryCount, 2);
    expect(api.lastTags, ['测试']);
    expect(state.error, isNull);
    expect(state.messages, hasLength(2));
    expect(
      state.messages.where((message) => message.role == ChatMessageRole.user),
      hasLength(1),
    );
    expect(state.messages.last.text, '重试成功');
  });

  test('keeps only the latest live chat messages', () async {
    final api = SuccessfulChatApi();
    final container = ProviderContainer(
      overrides: [chatApiProvider.overrideWithValue(api)],
    );
    addTearDown(container.dispose);
    final controller = container.read(chatControllerProvider.notifier);

    for (var index = 0; index < 101; index += 1) {
      await controller.ask('问题-$index');
    }

    final state = container.read(chatControllerProvider);
    expect(state.messages, hasLength(chatMessageWindowLimit));
    expect(state.messages.first.text, '问题-1');
    expect(state.messages.last.text, '回答-100');
    expect(state.olderMessagesHidden, isTrue);
  });

  test('bounds an oversized history before restoring it into live chat', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final controller = container.read(chatControllerProvider.notifier);
    final history = [
      for (var index = 0; index < 250; index += 1)
        ChatHistoryMessage(
          id: 'message-$index',
          conversationId: 'conversation-id',
          role: index.isEven ? 'user' : 'assistant',
          content: 'message-$index',
          citations: const [],
          createdAt: DateTime(2026, 7, 19).add(Duration(seconds: index)),
        ),
    ];

    controller.loadConversation(
      conversation: ConversationSummary(
        id: 'conversation-id',
        title: '长会话',
        createdAt: DateTime(2026, 7, 19),
        updatedAt: DateTime(2026, 7, 19),
      ),
      messages: history,
    );

    final state = container.read(chatControllerProvider);
    expect(state.messages, hasLength(chatMessageWindowLimit));
    expect(state.messages.first.text, 'message-50');
    expect(state.messages.last.text, 'message-249');
    expect(state.olderMessagesHidden, isTrue);
  });
}

class RetryChatApi extends ChatApi {
  RetryChatApi() : super(Dio());

  int queryCount = 0;
  List<String> lastTags = const [];

  @override
  Stream<ChatStreamEvent> queryStream(
    String question, {
    String? conversationId,
    List<String> tags = const [],
    List<String> documentIds = const [],
    List<String> sourceTypes = const [],
    int? recentDays,
  }) async* {
    final response = await query(
      question,
      conversationId: conversationId,
      tags: tags,
      documentIds: documentIds,
      recentDays: recentDays,
      sourceTypes: sourceTypes,
    );
    yield ChatStreamEvent.done(
      conversationId: response.conversationId,
      answer: response.answer,
      citations: response.citations,
      suggestedQuestions: response.suggestedQuestions,
    );
  }

  @override
  Future<ChatResponse> query(
    String question, {
    String? conversationId,
    List<String> tags = const [],
    List<String> documentIds = const [],
    int? recentDays,
    List<String> sourceTypes = const [],
  }) async {
    queryCount += 1;
    lastTags = tags;
    if (queryCount == 1) {
      throw Exception('temporary failure');
    }
    return const ChatResponse(
      conversationId: 'conversation-id',
      answer: '重试成功',
      citations: [],
      suggestedQuestions: [],
    );
  }
}

class SuccessfulChatApi extends ChatApi {
  SuccessfulChatApi() : super(Dio());

  int answerIndex = 0;

  @override
  Stream<ChatStreamEvent> queryStream(
    String question, {
    String? conversationId,
    List<String> tags = const [],
    List<String> documentIds = const [],
    List<String> sourceTypes = const [],
    int? recentDays,
  }) async* {
    final response = await query(
      question,
      conversationId: conversationId,
      tags: tags,
      documentIds: documentIds,
      recentDays: recentDays,
      sourceTypes: sourceTypes,
    );
    yield ChatStreamEvent.done(
      conversationId: response.conversationId,
      answer: response.answer,
      citations: response.citations,
      suggestedQuestions: response.suggestedQuestions,
    );
  }

  @override
  Future<ChatResponse> query(
    String question, {
    String? conversationId,
    List<String> tags = const [],
    List<String> documentIds = const [],
    int? recentDays,
    List<String> sourceTypes = const [],
  }) async {
    final index = answerIndex;
    answerIndex += 1;
    return ChatResponse(
      conversationId: 'conversation-id',
      answer: '回答-$index',
      citations: const [],
      suggestedQuestions: const [],
    );
  }
}
