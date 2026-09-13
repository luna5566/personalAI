import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/cache_state.dart';
import '../../../core/network/user_error_message.dart';
import '../data/chat_api.dart';
import '../models/chat.dart';

const chatMessageWindowLimit = 200;

final chatApiProvider = Provider<ChatApi>((ref) {
  ref.watch(cacheRevalidationProvider);
  return ChatApi(ref.watch(dioProvider));
});

final conversationHistoryProvider =
    FutureProvider.autoDispose<List<ConversationSummary>>((ref) {
  return ref.watch(chatApiProvider).listConversations();
});

final conversationPageProvider =
    FutureProvider.autoDispose.family<ConversationPage, int>((ref, page) {
  return ref.watch(chatApiProvider).listConversationPage(page: page);
});

typedef ConversationPageQuery = ({String? keyword, int page});

final filteredConversationPageProvider = FutureProvider.autoDispose
    .family<ConversationPage, ConversationPageQuery>((ref, query) {
  return ref.watch(chatApiProvider).listConversationPage(
        page: query.page,
        keyword: query.keyword,
      );
});

final conversationMessagesProvider =
    FutureProvider.autoDispose.family<MessageHistoryPage, String>(
  (ref, id) => ref.watch(chatApiProvider).listMessagePage(id),
);

final conversationDetailProvider =
    FutureProvider.autoDispose.family<ConversationSummary, String>(
  (ref, id) => ref.watch(chatApiProvider).getConversation(id),
);

final chatControllerProvider =
    NotifierProvider<ChatController, ChatState>(ChatController.new);

class ChatState {
  const ChatState({
    this.messages = const [],
    this.conversationId,
    this.loading = false,
    this.error,
    this.resumedFromHistory = false,
    this.olderMessagesHidden = false,
    this.scopeTags = const [],
    this.scopeDocumentIds = const [],
    this.scopeSourceTypes = const [],
    this.scopeRecentDays,
  });

  final List<ChatMessage> messages;
  final String? conversationId;
  final bool loading;
  final String? error;
  final bool resumedFromHistory;
  final bool olderMessagesHidden;
  final List<String> scopeTags;
  final List<String> scopeDocumentIds;
  final List<String> scopeSourceTypes;
  final int? scopeRecentDays;

  bool get isEmpty => messages.isEmpty;

  ChatState copyWith({
    List<ChatMessage>? messages,
    String? conversationId,
    bool? loading,
    String? error,
    bool clearError = false,
    bool? resumedFromHistory,
    bool? olderMessagesHidden,
    List<String>? scopeTags,
    List<String>? scopeDocumentIds,
    List<String>? scopeSourceTypes,
    int? scopeRecentDays,
    bool clearRecentDays = false,
  }) {
    return ChatState(
      messages: messages ?? this.messages,
      conversationId: conversationId ?? this.conversationId,
      loading: loading ?? this.loading,
      error: clearError ? null : error ?? this.error,
      resumedFromHistory: resumedFromHistory ?? this.resumedFromHistory,
      olderMessagesHidden: olderMessagesHidden ?? this.olderMessagesHidden,
      scopeTags: scopeTags ?? this.scopeTags,
      scopeDocumentIds: scopeDocumentIds ?? this.scopeDocumentIds,
      scopeSourceTypes: scopeSourceTypes ?? this.scopeSourceTypes,
      scopeRecentDays: clearRecentDays
          ? null
          : scopeRecentDays ?? this.scopeRecentDays,
    );
  }
}

class ChatController extends Notifier<ChatState> {
  @override
  ChatState build() => const ChatState();

  Future<void> ask(
    String question, {
    List<String> tags = const [],
    List<String> documentIds = const [],
    List<String> sourceTypes = const [],
    int? recentDays,
  }) async {
    final trimmed = question.trim();
    if (trimmed.isEmpty || state.loading) {
      return;
    }

    final pendingWindow = _boundedChatMessages([
      ...state.messages,
      ChatMessage(role: ChatMessageRole.user, text: trimmed),
    ]);
    final pendingMessages = pendingWindow.messages;
    final olderMessagesHidden =
        state.olderMessagesHidden || pendingWindow.truncated;
    state = state.copyWith(
      messages: pendingMessages,
      loading: true,
      clearError: true,
      scopeTags: tags,
      scopeDocumentIds: documentIds,
      scopeSourceTypes: sourceTypes,
      scopeRecentDays: recentDays,
      clearRecentDays: recentDays == null,
      olderMessagesHidden: olderMessagesHidden,
    );

    try {
      var conversationId = state.conversationId;
      var answerBuffer = '';
      var citations = const <Citation>[];
      var suggestedQuestions = const <String>[];
      var sawDone = false;

      await for (final event in ref.read(chatApiProvider).queryStream(
            trimmed,
            conversationId: conversationId,
            tags: tags,
            documentIds: documentIds,
            sourceTypes: sourceTypes,
            recentDays: recentDays,
          )) {
        if (event.isError) {
          throw Exception(event.message ?? '提问失败，请稍后重试');
        }
        if (event.isMeta && event.conversationId != null) {
          conversationId = event.conversationId;
          state = state.copyWith(conversationId: conversationId);
          continue;
        }
        if (event.isDelta && event.deltaText != null) {
          answerBuffer += event.deltaText!;
          final streamingWindow = _boundedChatMessages([
            ...pendingMessages,
            ChatMessage(
              role: ChatMessageRole.assistant,
              text: answerBuffer,
            ),
          ]);
          state = ChatState(
            conversationId: conversationId,
            resumedFromHistory: state.resumedFromHistory,
            olderMessagesHidden:
                olderMessagesHidden || streamingWindow.truncated,
            loading: true,
            scopeTags: tags,
            scopeDocumentIds: documentIds,
            scopeSourceTypes: sourceTypes,
            scopeRecentDays: recentDays,
            messages: streamingWindow.messages,
          );
          continue;
        }
        if (event.isDone) {
          sawDone = true;
          conversationId = event.conversationId ?? conversationId;
          answerBuffer = event.answer ?? answerBuffer;
          citations = event.citations;
          suggestedQuestions = event.suggestedQuestions;
        }
      }

      if (!sawDone && answerBuffer.isEmpty) {
        throw Exception('提问失败，请稍后重试');
      }

      final completedWindow = _boundedChatMessages([
        ...pendingMessages,
        ChatMessage(
          role: ChatMessageRole.assistant,
          text: answerBuffer,
          citations: citations,
          suggestedQuestions: suggestedQuestions,
        ),
      ]);
      state = ChatState(
        conversationId: conversationId,
        resumedFromHistory: state.resumedFromHistory,
        olderMessagesHidden: olderMessagesHidden || completedWindow.truncated,
        scopeTags: tags,
        scopeDocumentIds: documentIds,
        scopeSourceTypes: sourceTypes,
        scopeRecentDays: recentDays,
        messages: completedWindow.messages,
      );
      ref.invalidate(conversationHistoryProvider);
      ref.invalidate(conversationPageProvider);
      ref.invalidate(filteredConversationPageProvider);
    } catch (error) {
      state = ChatState(
        conversationId: state.conversationId,
        resumedFromHistory: state.resumedFromHistory,
        olderMessagesHidden: olderMessagesHidden,
        messages: pendingMessages,
        error: userFacingErrorMessage(
          error,
          fallback: '提问失败，请稍后重试',
        ),
        scopeTags: tags,
        scopeDocumentIds: documentIds,
        scopeSourceTypes: sourceTypes,
        scopeRecentDays: recentDays,
      );
    }
  }

  Future<void> retryLast({
    List<String> tags = const [],
    List<String> documentIds = const [],
    List<String> sourceTypes = const [],
    int? recentDays,
  }) async {
    if (state.loading || state.error == null || state.messages.isEmpty) {
      return;
    }
    final failedMessage = state.messages.last;
    if (failedMessage.role != ChatMessageRole.user) {
      return;
    }
    final previousMessages =
        state.messages.sublist(0, state.messages.length - 1);
    state = ChatState(
      messages: previousMessages,
      conversationId: state.conversationId,
      resumedFromHistory: state.resumedFromHistory,
      olderMessagesHidden: state.olderMessagesHidden,
      scopeTags: state.scopeTags,
      scopeDocumentIds: state.scopeDocumentIds,
      scopeSourceTypes: state.scopeSourceTypes,
      scopeRecentDays: state.scopeRecentDays,
    );
    await ask(
      failedMessage.text,
      tags: tags,
      documentIds: documentIds,
      sourceTypes: sourceTypes,
      recentDays: recentDays ?? state.scopeRecentDays,
    );
  }

  void clear() {
    state = const ChatState();
  }

  void loadConversation({
    required ConversationSummary conversation,
    required List<ChatHistoryMessage> messages,
    bool olderMessagesHidden = false,
  }) {
    final loadedWindow = _boundedChatMessages(
      messages
          .where((message) => message.role != 'system')
          .map((message) => message.toChatMessage()),
    );
    state = ChatState(
      conversationId: conversation.id,
      resumedFromHistory: true,
      olderMessagesHidden: olderMessagesHidden || loadedWindow.truncated,
      scopeTags: conversation.tags,
      scopeDocumentIds: conversation.documentIds,
      scopeSourceTypes: conversation.sourceTypes,
      scopeRecentDays: conversation.recentDays,
      messages: loadedWindow.messages,
    );
  }
}

({List<ChatMessage> messages, bool truncated}) _boundedChatMessages(
  Iterable<ChatMessage> values,
) {
  final messages = values.toList(growable: false);
  if (messages.length <= chatMessageWindowLimit) {
    return (messages: messages, truncated: false);
  }
  return (
    messages: messages.sublist(messages.length - chatMessageWindowLimit),
    truncated: true,
  );
}
