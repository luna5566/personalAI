import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:personal_ai_mobile/features/chat/models/chat.dart';
import 'package:personal_ai_mobile/features/chat/providers/chat_provider.dart';
import 'package:personal_ai_mobile/features/documents/models/document.dart';
import 'package:personal_ai_mobile/features/documents/providers/documents_provider.dart';
import 'package:personal_ai_mobile/features/home/ui/home_page.dart';

void main() {
  testWidgets('renders home quick actions and recent conversations',
      (tester) async {
    final router = GoRouter(
      initialLocation: '/app/home',
      routes: [
        GoRoute(
          path: '/app/home',
          builder: (context, state) => const HomePage(),
        ),
        GoRoute(
          path: '/app/chat',
          builder: (context, state) => const Scaffold(body: Text('chat page')),
        ),
        GoRoute(
          path: '/app/chat/history/:id',
          builder: (context, state) =>
              Scaffold(body: Text('history:${state.pathParameters['id']}')),
        ),
        GoRoute(
          path: '/app/documents/:id',
          builder: (context, state) =>
              Scaffold(body: Text('document:${state.pathParameters['id']}')),
        ),
      ],
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          documentsProvider((tag: null, keyword: null, sourceType: null))
              .overrideWith(
            (ref) async => const [
              KnowledgeDocument(
                id: 'document-id',
                title: '资料 A',
                sourceType: 'note',
                status: 'indexed',
                tags: [],
              ),
            ],
          ),
          conversationHistoryProvider.overrideWith(
            (ref) async => [
              ConversationSummary(
                id: 'conversation-id',
                title: '最近问答标题',
                createdAt: DateTime(2026, 5, 17, 10),
                updatedAt: DateTime(2026, 5, 17, 11, 30),
              ),
            ],
          ),
          chatControllerProvider.overrideWith(FakeChatController.new),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('上传资料'), findsOneWidget);
    expect(find.text('一键整理'), findsOneWidget);
    expect(find.text('最近问答标题'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '快速问题');
    await tester.tap(find.byTooltip('发送'));
    await tester.pumpAndSettle();

    expect(FakeChatController.lastQuestion, '快速问题');
    expect(find.text('chat page'), findsOneWidget);
  });

  testWidgets('retries failed home sections independently', (tester) async {
    var documentAttempts = 0;
    var conversationAttempts = 0;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          documentsProvider((tag: null, keyword: null, sourceType: null))
              .overrideWith(
            (ref) async {
              documentAttempts += 1;
              if (documentAttempts == 1) {
                throw StateError('documents transport details');
              }
              return const [
                KnowledgeDocument(
                  id: 'retried-document',
                  title: '重试后的资料',
                  sourceType: 'note',
                  status: 'indexed',
                  tags: [],
                ),
              ];
            },
          ),
          conversationHistoryProvider.overrideWith(
            (ref) async {
              conversationAttempts += 1;
              if (conversationAttempts == 1) {
                throw StateError('conversation database details');
              }
              return [
                ConversationSummary(
                  id: 'retried-conversation',
                  title: '重试后的问答',
                  createdAt: DateTime(2026, 7, 18, 10),
                  updatedAt: DateTime(2026, 7, 18, 10),
                ),
              ];
            },
          ),
          chatControllerProvider.overrideWith(FakeChatController.new),
        ],
        child: const MaterialApp(home: HomePage()),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('暂时无法加载最近资料'), findsOneWidget);
    expect(find.text('暂时无法加载最近问答'), findsOneWidget);
    expect(find.textContaining('transport details'), findsNothing);
    expect(find.textContaining('database details'), findsNothing);
    expect(find.byTooltip('重新加载最近资料'), findsOneWidget);
    expect(find.byTooltip('重新加载最近问答'), findsOneWidget);

    await tester.tap(find.byTooltip('重新加载最近资料'));
    await tester.pumpAndSettle();

    expect(documentAttempts, 2);
    expect(conversationAttempts, 1);
    expect(find.text('重试后的资料'), findsOneWidget);
    expect(find.text('暂时无法加载最近问答'), findsOneWidget);

    await tester.tap(find.byTooltip('重新加载最近问答'));
    await tester.pumpAndSettle();

    expect(documentAttempts, 2);
    expect(conversationAttempts, 2);
    expect(find.text('重试后的资料'), findsOneWidget);
    expect(find.text('重试后的问答'), findsOneWidget);
  });
}

class FakeChatController extends ChatController {

  static String? lastQuestion;

  @override
  Future<void> ask(
    String question, {
    List<String> tags = const [],
    List<String> documentIds = const [],
    int? recentDays,
    List<String> sourceTypes = const [],
  }) async {
    lastQuestion = question;
  }
}
