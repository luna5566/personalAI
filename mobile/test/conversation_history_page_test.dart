import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:personal_ai_mobile/features/chat/data/chat_api.dart';
import 'package:personal_ai_mobile/features/chat/models/chat.dart';
import 'package:personal_ai_mobile/features/chat/providers/chat_provider.dart';
import 'package:personal_ai_mobile/features/chat/ui/chat_page.dart';
import 'package:personal_ai_mobile/features/chat/ui/conversation_detail_page.dart';
import 'package:personal_ai_mobile/features/chat/ui/conversation_history_page.dart';
import 'package:personal_ai_mobile/features/documents/providers/documents_provider.dart';
import 'package:personal_ai_mobile/features/tags/models/tag.dart';
import 'package:personal_ai_mobile/features/tags/providers/tags_provider.dart';

void main() {
  setUp(FakeChatApi.reset);

  testWidgets('renders conversation history items', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          filteredConversationPageProvider((keyword: null, page: 1))
              .overrideWith(
            (ref) async => ConversationPage(
              items: [
                ConversationSummary(
                  id: 'conversation-id',
                  title: '最近的笔记有哪些主题？',
                  createdAt: DateTime(2026, 5, 17, 10),
                  updatedAt: DateTime(2026, 5, 17, 11, 30),
                ),
              ],
              total: 1,
              page: 1,
              pageSize: 20,
            ),
          ),
        ],
        child: const MaterialApp(home: ConversationHistoryPage()),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('会话历史'), findsOneWidget);
    expect(find.text('最近的笔记有哪些主题？'), findsOneWidget);
    expect(find.byIcon(Icons.chevron_right), findsWidgets);
  });

  testWidgets('filters conversation history by title', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          filteredConversationPageProvider((keyword: null, page: 1))
              .overrideWith(
            (ref) async => ConversationPage(
              items: [
                ConversationSummary(
                  id: 'conversation-a',
                  title: '英语学习计划',
                  createdAt: DateTime(2026, 5, 17, 10),
                  updatedAt: DateTime(2026, 5, 17, 11, 30),
                ),
                ConversationSummary(
                  id: 'conversation-b',
                  title: '产品灵感整理',
                  createdAt: DateTime(2026, 5, 18, 10),
                  updatedAt: DateTime(2026, 5, 18, 11, 30),
                ),
              ],
              total: 2,
              page: 1,
              pageSize: 20,
            ),
          ),
          filteredConversationPageProvider((keyword: '英语', page: 1))
              .overrideWith(
            (ref) async => ConversationPage(
              items: [
                ConversationSummary(
                  id: 'conversation-a',
                  title: '英语学习计划',
                  createdAt: DateTime(2026, 5, 17, 10),
                  updatedAt: DateTime(2026, 5, 17, 11, 30),
                ),
              ],
              total: 1,
              page: 1,
              pageSize: 20,
            ),
          ),
        ],
        child: const MaterialApp(home: ConversationHistoryPage()),
      ),
    );

    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '英语');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();

    expect(find.text('英语学习计划'), findsOneWidget);
    expect(find.text('产品灵感整理'), findsNothing);
  });

  testWidgets('debounces server-side conversation searches', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [chatApiProvider.overrideWithValue(FakeChatApi())],
        child: const MaterialApp(home: ConversationHistoryPage()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), '英');
    await tester.pump(const Duration(milliseconds: 100));
    await tester.enterText(find.byType(TextField), '英语');
    await tester.pump(const Duration(milliseconds: 100));

    expect(FakeChatApi.searchKeywords.whereType<String>(), isEmpty);

    await tester.pump(const Duration(milliseconds: 300));
    await tester.pumpAndSettle();

    expect(FakeChatApi.searchKeywords.whereType<String>(), ['英语']);
  });

  testWidgets('moves to the next conversation page', (tester) async {
    final first = ConversationSummary(
      id: 'conversation-a',
      title: '第一页会话',
      createdAt: DateTime(2026, 5, 17, 10),
      updatedAt: DateTime(2026, 5, 17, 11),
    );
    final second = ConversationSummary(
      id: 'conversation-b',
      title: '第二页会话',
      createdAt: DateTime(2026, 5, 18, 10),
      updatedAt: DateTime(2026, 5, 18, 11),
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          filteredConversationPageProvider((keyword: null, page: 1))
              .overrideWith(
            (ref) async => ConversationPage(
              items: [first],
              total: 21,
              page: 1,
              pageSize: 20,
            ),
          ),
          filteredConversationPageProvider((keyword: null, page: 2))
              .overrideWith(
            (ref) async => ConversationPage(
              items: [second],
              total: 21,
              page: 2,
              pageSize: 20,
            ),
          ),
        ],
        child: const MaterialApp(home: ConversationHistoryPage()),
      ),
    );

    await tester.pumpAndSettle();
    expect(find.text('第一页会话'), findsOneWidget);

    await tester.tap(find.byTooltip('下一页'));
    await tester.pumpAndSettle();

    expect(find.text('第二页会话'), findsOneWidget);
    expect(find.text('第 2 / 2 页，共 21 条'), findsOneWidget);
  });

  testWidgets('renames a conversation from history menu', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          filteredConversationPageProvider((keyword: null, page: 1))
              .overrideWith(
            (ref) async => ConversationPage(
              items: [
                ConversationSummary(
                  id: 'conversation-id',
                  title: '旧标题',
                  createdAt: DateTime(2026, 5, 17, 10),
                  updatedAt: DateTime(2026, 5, 17, 11, 30),
                ),
              ],
              total: 1,
              page: 1,
              pageSize: 20,
            ),
          ),
          chatApiProvider.overrideWithValue(FakeChatApi()),
        ],
        child: const MaterialApp(home: ConversationHistoryPage()),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('更多操作'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('重命名'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).last, '新标题');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();

    expect(FakeChatApi.renamedConversationId, 'conversation-id');
    expect(FakeChatApi.renamedTitle, '新标题');
  });

  testWidgets('deletes a conversation from history menu', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          filteredConversationPageProvider((keyword: null, page: 1))
              .overrideWith(
            (ref) async => ConversationPage(
              items: [
                ConversationSummary(
                  id: 'conversation-id',
                  title: '待删除会话',
                  createdAt: DateTime(2026, 5, 17, 10),
                  updatedAt: DateTime(2026, 5, 17, 11, 30),
                ),
              ],
              total: 1,
              page: 1,
              pageSize: 20,
            ),
          ),
          chatApiProvider.overrideWithValue(FakeChatApi()),
        ],
        child: const MaterialApp(home: ConversationHistoryPage()),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('更多操作'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除').last);
    await tester.pumpAndSettle();

    expect(FakeChatApi.deletedConversationId, 'conversation-id');
  });

  testWidgets('continues a conversation from history detail', (tester) async {
    final router = GoRouter(
      initialLocation: '/app/chat/history/conversation-id',
      routes: [
        GoRoute(
          path: '/app/chat',
          builder: (context, state) => const ChatPage(),
        ),
        GoRoute(
          path: '/app/chat/history/:id',
          builder: (context, state) => ConversationDetailPage(
            conversationId: state.pathParameters['id']!,
          ),
        ),
        GoRoute(
          path: '/app/documents/:id',
          builder: (context, state) => Scaffold(
            body: Text('document:${state.pathParameters['id']}'),
          ),
        ),
      ],
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith(
            (ref) async => const [
              KnowledgeTag(id: 'tag-learning', name: '学习'),
            ],
          ),
          selectableDocumentsProvider.overrideWith(
            (ref) async => const [],
          ),
          chatControllerProvider.overrideWith(FakeChatController.new),
          conversationMessagesProvider('conversation-id').overrideWith(
            (ref) async => MessageHistoryPage(
              items: [
                ChatHistoryMessage(
                  id: 'message-1',
                  conversationId: 'conversation-id',
                  role: 'user',
                  content: '这组资料的主线是什么？',
                  citations: const [],
                  createdAt: DateTime(2026, 5, 17, 11),
                ),
                ChatHistoryMessage(
                  id: 'message-2',
                  conversationId: 'conversation-id',
                  role: 'assistant',
                  content: '主线是把零散笔记整理成可复用的知识结构。',
                  citations: const [],
                  createdAt: DateTime(2026, 5, 17, 11, 1),
                ),
              ],
              nextCursor: 'older-page',
            ),
          ),
          conversationDetailProvider('conversation-id').overrideWith(
            (ref) async => ConversationSummary(
              id: 'conversation-id',
              title: '历史会话',
              createdAt: DateTime(2026, 5, 17, 10),
              updatedAt: DateTime(2026, 5, 17, 11),
              tags: const ['学习'],
            ),
          ),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.forum_outlined));
    await tester.pumpAndSettle();

    expect(find.text('正在继续历史会话'), findsOneWidget);
    final restoredTag = tester.widget<FilterChip>(
      find.widgetWithText(FilterChip, '学习'),
    );
    expect(restoredTag.selected, isTrue);
    expect(find.text('这组资料的主线是什么？'), findsOneWidget);
    expect(find.text('主线是把零散笔记整理成可复用的知识结构。'), findsOneWidget);
    expect(find.text('较早消息未显示'), findsOneWidget);
  });

  testWidgets('loads older messages on demand and bounds the history window',
      (tester) async {
    final api = PagedMessageChatApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          chatApiProvider.overrideWithValue(api),
          conversationDetailProvider('conversation-id').overrideWith(
            (ref) async => ConversationSummary(
              id: 'conversation-id',
              title: '长会话',
              createdAt: DateTime(2026, 5, 17, 10),
              updatedAt: DateTime(2026, 5, 17, 11),
            ),
          ),
        ],
        child: const MaterialApp(
          home: ConversationDetailPage(
            conversationId: 'conversation-id',
          ),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(api.cursors, [null]);
    expect(find.text('加载更早消息'), findsOneWidget);
    expect(find.text('返回最近消息'), findsNothing);

    for (var page = 0; page < 4; page += 1) {
      await tester.tap(find.text('加载更早消息'));
      await tester.pumpAndSettle();
    }

    expect(api.cursors, [null, 'page-2', 'page-3', 'page-4', 'page-5']);
    expect(find.text('加载更早消息'), findsNothing);
    expect(find.text('返回最近消息'), findsOneWidget);

    await tester.tap(find.text('返回最近消息'));
    await tester.pumpAndSettle();

    expect(api.cursors.last, isNull);
    expect(api.cursors, hasLength(6));
    expect(find.text('加载更早消息'), findsOneWidget);
    expect(find.text('返回最近消息'), findsNothing);
  });

  testWidgets('marks an oversized legacy message as truncated', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          conversationMessagesProvider('conversation-id').overrideWith(
            (ref) async => MessageHistoryPage(
              items: [
                ChatHistoryMessage(
                  id: 'message-1',
                  conversationId: 'conversation-id',
                  role: 'assistant',
                  content: '历史回答前缀',
                  contentTruncated: true,
                  citations: const [],
                  createdAt: DateTime(2026, 5, 17, 11),
                ),
              ],
              nextCursor: null,
            ),
          ),
          conversationDetailProvider('conversation-id').overrideWith(
            (ref) async => ConversationSummary(
              id: 'conversation-id',
              title: '历史会话',
              createdAt: DateTime(2026, 5, 17, 10),
              updatedAt: DateTime(2026, 5, 17, 11),
            ),
          ),
        ],
        child: const MaterialApp(
          home: ConversationDetailPage(
            conversationId: 'conversation-id',
          ),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('历史回答前缀'), findsOneWidget);
    expect(
      find.text('这条历史消息过长，仅显示前 32000 个字符'),
      findsOneWidget,
    );
    expect(find.byIcon(Icons.info_outline), findsOneWidget);
  });

  testWidgets('opens the source document from a history citation',
      (tester) async {
    final router = GoRouter(
      initialLocation: '/app/chat/history/conversation-id',
      routes: [
        GoRoute(
          path: '/app/chat/history/:id',
          builder: (context, state) => ConversationDetailPage(
            conversationId: state.pathParameters['id']!,
          ),
        ),
        GoRoute(
          path: '/app/documents/:id',
          builder: (context, state) => Scaffold(
            body: Text('document:${state.pathParameters['id']}'),
          ),
        ),
      ],
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          conversationMessagesProvider('conversation-id').overrideWith(
            (ref) async => MessageHistoryPage(
              items: [
                ChatHistoryMessage(
                  id: 'message-1',
                  conversationId: 'conversation-id',
                  role: 'assistant',
                  content: '历史回答',
                  citations: const [
                    Citation(
                      documentId: 'history-source-id',
                      documentTitle: '历史来源资料',
                      text: '历史引用片段',
                      score: 0.8,
                    ),
                  ],
                  createdAt: DateTime(2026, 5, 17, 11),
                ),
              ],
              nextCursor: null,
            ),
          ),
          conversationDetailProvider('conversation-id').overrideWith(
            (ref) async => ConversationSummary(
              id: 'conversation-id',
              title: '历史会话',
              createdAt: DateTime(2026, 5, 17, 10),
              updatedAt: DateTime(2026, 5, 17, 11),
            ),
          ),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.text('历史来源资料'));
    await tester.pumpAndSettle();

    expect(find.text('document:history-source-id'), findsOneWidget);
  });
}

class FakeChatController extends ChatController {
}

class FakeChatApi extends ChatApi {
  FakeChatApi() : super(Dio());

  static String? renamedConversationId;
  static String? renamedTitle;
  static String? deletedConversationId;
  static List<String?> searchKeywords = [];

  static void reset() {
    renamedConversationId = null;
    renamedTitle = null;
    deletedConversationId = null;
    searchKeywords = [];
  }

  @override
  Future<ConversationPage> listConversationPage({
    int page = 1,
    int pageSize = 20,
    String? keyword,
  }) async {
    searchKeywords.add(keyword);
    return ConversationPage(
      items: [
        ConversationSummary(
          id: 'search-conversation',
          title: keyword == null ? '初始会话' : '英语学习计划',
          createdAt: DateTime(2026, 5, 17, 10),
          updatedAt: DateTime(2026, 5, 17, 11),
        ),
      ],
      total: 1,
      page: page,
      pageSize: pageSize,
    );
  }

  @override
  Future<ConversationSummary> updateConversationTitle(
    String conversationId, {
    required String title,
  }) async {
    renamedConversationId = conversationId;
    renamedTitle = title;
    return ConversationSummary(
      id: conversationId,
      title: title,
      createdAt: DateTime(2026, 5, 17, 10),
      updatedAt: DateTime(2026, 5, 17, 11, 30),
    );
  }

  @override
  Future<void> deleteConversation(String conversationId) async {
    deletedConversationId = conversationId;
  }
}

class PagedMessageChatApi extends ChatApi {
  PagedMessageChatApi() : super(Dio());

  final List<String?> cursors = [];

  @override
  Future<MessageHistoryPage> listMessagePage(
    String conversationId, {
    String? cursor,
  }) async {
    cursors.add(cursor);
    final page = cursor == null ? 1 : int.parse(cursor.split('-').last);
    final end = 300 - page * 50;
    final start = end - 49;
    final items = [
      for (var number = start; number <= end; number += 1)
        ChatHistoryMessage(
          id: 'message-$number',
          conversationId: conversationId,
          role: number.isEven ? 'assistant' : 'user',
          content: 'message-$number',
          citations: const [],
          createdAt: DateTime(2026, 5, 17).add(
            Duration(minutes: number),
          ),
        ),
    ];
    return MessageHistoryPage(
      items: items,
      nextCursor: page < 5 ? 'page-${page + 1}' : null,
    );
  }
}
