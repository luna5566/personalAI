import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:personal_ai_mobile/features/chat/models/chat.dart';
import 'package:personal_ai_mobile/features/chat/providers/chat_provider.dart';
import 'package:personal_ai_mobile/features/chat/services/speech_input_service.dart';
import 'package:personal_ai_mobile/features/chat/ui/chat_page.dart';
import 'package:personal_ai_mobile/features/documents/models/document.dart';
import 'package:personal_ai_mobile/features/documents/providers/documents_provider.dart';
import 'package:personal_ai_mobile/features/tags/providers/tags_provider.dart';

void main() {
  testWidgets('clears the question input after sending', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith((ref) async => const []),
          selectableDocumentsProvider.overrideWith(
            (ref) async => const [],
          ),
          chatControllerProvider.overrideWith(FakeChatController.new),
        ],
        child: const MaterialApp(home: ChatPage()),
      ),
    );

    await tester.enterText(find.byType(TextField), 'git');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();

    final textField = tester.widget<TextField>(find.byType(TextField));
    expect(textField.controller?.text, isEmpty);
    expect(FakeChatController.lastQuestion, 'git');
    expect(find.text('git'), findsOneWidget);
    expect(find.text('测试回答'), findsOneWidget);
    expect(find.text('正在继续历史会话'), findsNothing);
    expect(find.text('当前范围：全部资料'), findsOneWidget);
  });

  testWidgets('sends selected document scope with the question',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith((ref) async => const []),
          selectableDocumentsProvider.overrideWith(
            (ref) async => const [
              KnowledgeDocument(
                id: 'document-id',
                title: '线性代数笔记',
                sourceType: 'note',
                status: 'indexed',
                tags: [],
              ),
            ],
          ),
          chatControllerProvider.overrideWith(FakeChatController.new),
        ],
        child: const MaterialApp(
          home: ChatPage(initialDocumentId: 'document-id'),
        ),
      ),
    );

    await tester.pumpAndSettle();
    final selectedDocument = tester.widget<FilterChip>(
      find.widgetWithText(FilterChip, '线性代数笔记'),
    );
    expect(selectedDocument.selected, isTrue);
    expect(find.text('当前范围：线性代数笔记'), findsOneWidget);
    await tester.enterText(find.byType(TextField), '矩阵怎么理解？');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();

    expect(FakeChatController.lastQuestion, '矩阵怎么理解？');
    expect(FakeChatController.lastDocumentIds, ['document-id']);
  });

  testWidgets('sends every document supplied by an organize result',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith((ref) async => const []),
          selectableDocumentsProvider.overrideWith(
            (ref) async => const [
              KnowledgeDocument(
                id: 'document-a',
                title: '资料 A',
                sourceType: 'note',
                status: 'indexed',
                tags: [],
              ),
              KnowledgeDocument(
                id: 'document-b',
                title: '资料 B',
                sourceType: 'note',
                status: 'indexed',
                tags: [],
              ),
            ],
          ),
          chatControllerProvider.overrideWith(FakeChatController.new),
        ],
        child: const MaterialApp(
          home: ChatPage(
            initialDocumentIds: ['document-a', 'document-b'],
          ),
        ),
      ),
    );

    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '继续分析');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();

    expect(FakeChatController.lastDocumentIds, ['document-a', 'document-b']);
  });

  testWidgets('sends selected source type scope with the question',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith((ref) async => const []),
          selectableDocumentsProvider.overrideWith((ref) async => const []),
          chatControllerProvider.overrideWith(FakeChatController.new),
        ],
        child: const MaterialApp(home: ChatPage()),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilterChip, 'PDF'));
    await tester.enterText(find.byType(TextField), '总结 PDF');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();

    expect(FakeChatController.lastSourceTypes, ['pdf']);
  });

  testWidgets('opens the source document from a citation', (tester) async {
    final router = GoRouter(
      initialLocation: '/app/chat',
      routes: [
        GoRoute(
          path: '/app/chat',
          builder: (context, state) => const ChatPage(),
        ),
        GoRoute(
          path: '/app/documents/:id',
          builder: (context, state) => Scaffold(
            body: Text(
              'document:${state.pathParameters['id']}:'
              '${state.uri.queryParameters['highlightStart']}:'
              '${state.uri.queryParameters['highlightEnd']}',
            ),
          ),
        ),
      ],
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith((ref) async => const []),
          selectableDocumentsProvider.overrideWith(
            (ref) async => const [],
          ),
          chatControllerProvider.overrideWith(CitationChatController.new),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.enterText(find.byType(TextField), '引用测试');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();
    expect(find.text('PDF · 第 3 页 · 相关度 90%'), findsOneWidget);
    await tester.tap(find.text('来源资料'));
    await tester.pumpAndSettle();

    expect(find.text('document:source-document-id:6:12'), findsOneWidget);
  });

  testWidgets('fills the question from microphone recognition', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith((ref) async => const []),
          selectableDocumentsProvider.overrideWith((ref) async => const []),
          chatControllerProvider.overrideWith(FakeChatController.new),
          speechInputServiceProvider
              .overrideWithValue(FakeSpeechInputService()),
        ],
        child: const MaterialApp(home: ChatPage()),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('语音输入'));
    await tester.pump();

    final input = tester.widget<TextField>(find.byType(TextField));
    expect(input.controller?.text, '语音问题');
    expect(find.byTooltip('停止语音输入'), findsOneWidget);
  });

  testWidgets('shows a history entry when older live messages are hidden',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith((ref) async => const []),
          selectableDocumentsProvider.overrideWith((ref) async => const []),
          chatControllerProvider.overrideWith(HiddenHistoryChatController.new),
          speechInputServiceProvider
              .overrideWithValue(FakeSpeechInputService()),
        ],
        child: const MaterialApp(home: ChatPage()),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('较早消息未显示'), findsOneWidget);
    expect(find.byTooltip('查看会话历史'), findsOneWidget);
  });
}

class FakeChatController extends ChatController {
  FakeChatController(super.ref);

  static String? lastQuestion;
  static List<String> lastDocumentIds = const [];
  static List<String> lastSourceTypes = const [];

  @override
  Future<void> ask(
    String question, {
    List<String> tags = const [],
    List<String> documentIds = const [],
    List<String> sourceTypes = const [],
  }) async {
    lastQuestion = question;
    lastDocumentIds = documentIds;
    lastSourceTypes = sourceTypes;
    state = ChatState(
      messages: [
        ChatMessage(role: ChatMessageRole.user, text: question),
        const ChatMessage(
          role: ChatMessageRole.assistant,
          text: '测试回答',
          suggestedQuestions: ['继续追问'],
        ),
      ],
    );
  }
}

class CitationChatController extends ChatController {
  CitationChatController(super.ref);

  @override
  Future<void> ask(
    String question, {
    List<String> tags = const [],
    List<String> documentIds = const [],
    List<String> sourceTypes = const [],
  }) async {
    state = ChatState(
      messages: [
        ChatMessage(role: ChatMessageRole.user, text: question),
        const ChatMessage(
          role: ChatMessageRole.assistant,
          text: '带引用的回答',
          citations: [
            Citation(
              documentId: 'source-document-id',
              documentTitle: '来源资料',
              text: '这是引用片段',
              score: 0.9,
              startOffset: 6,
              endOffset: 12,
              sourceType: 'pdf',
              pageNumber: 3,
            ),
          ],
        ),
      ],
    );
  }
}

class HiddenHistoryChatController extends ChatController {
  HiddenHistoryChatController(super.ref) {
    state = const ChatState(
      conversationId: 'conversation-id',
      messages: [
        ChatMessage(role: ChatMessageRole.assistant, text: '最近回答'),
      ],
      olderMessagesHidden: true,
    );
  }
}

class FakeSpeechInputService extends SpeechInputService {
  @override
  Future<bool> start({
    required void Function(String text) onText,
    required void Function() onStopped,
    required void Function(String message) onError,
  }) async {
    onText('语音问题');
    return true;
  }

  @override
  Future<void> stop() async {}
}
