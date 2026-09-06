import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:personal_ai_mobile/features/documents/data/documents_api.dart';
import 'package:personal_ai_mobile/features/documents/models/document.dart';
import 'package:personal_ai_mobile/features/documents/providers/documents_provider.dart';
import 'package:personal_ai_mobile/features/documents/ui/document_detail_page.dart';
import 'package:personal_ai_mobile/features/organize/data/organize_api.dart';
import 'package:personal_ai_mobile/features/organize/providers/organize_provider.dart';

void main() {
  testWidgets('highlights citation text by exact offsets', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          documentDetailProvider(
            (id: 'document-id', contentOffset: 0),
          ).overrideWith(
            (ref) async => const KnowledgeDocument(
              id: 'document-id',
              title: '测试资料',
              sourceType: 'note',
              status: 'indexed',
              tags: [],
              content: '前置 内容这是精确引用片段后续内容',
            ),
          ),
        ],
        child: const MaterialApp(
          home: DocumentDetailPage(
            documentId: 'document-id',
            highlightText: '这是精确引用片段',
            highlightStart: 5,
            highlightEnd: 13,
          ),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('引用片段'), findsOneWidget);
    expect(find.text('这是精确引用片段'), findsNWidgets(2));
    expect(find.text('前置 内容'), findsOneWidget);
    expect(find.text('后续内容'), findsOneWidget);
  });

  testWidgets('opens chat scoped to the current indexed document',
      (tester) async {
    final router = GoRouter(
      initialLocation: '/detail',
      routes: [
        GoRoute(
          path: '/detail',
          builder: (context, state) => const DocumentDetailPage(
            documentId: 'document-id',
          ),
        ),
        GoRoute(
          path: '/app/chat',
          builder: (context, state) => Scaffold(
            body: Text('scope:${state.uri.queryParameters['documentId']}'),
          ),
        ),
      ],
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          documentDetailProvider(
            (id: 'document-id', contentOffset: 0),
          ).overrideWith(
            (ref) async => const KnowledgeDocument(
              id: 'document-id',
              title: '测试资料',
              sourceType: 'note',
              status: 'indexed',
              tags: [],
              content: '资料内容',
            ),
          ),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('针对这份资料提问'));
    await tester.pumpAndSettle();

    expect(find.text('scope:document-id'), findsOneWidget);
  });

  testWidgets('saves organize result as a new note', (tester) async {
    final router = GoRouter(
      initialLocation: '/detail',
      routes: [
        GoRoute(
          path: '/detail',
          builder: (context, state) => const DocumentDetailPage(
            documentId: 'document-id',
          ),
        ),
        GoRoute(
          path: '/app/documents/:id',
          builder: (context, state) => Scaffold(
            body: Text('saved:${state.pathParameters['id']}'),
          ),
        ),
      ],
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          documentDetailProvider(
            (id: 'document-id', contentOffset: 0),
          ).overrideWith(
            (ref) async => const KnowledgeDocument(
              id: 'document-id',
              title: '测试资料',
              sourceType: 'note',
              status: 'indexed',
              tags: [],
              content: '资料内容',
            ),
          ),
          organizeApiProvider.overrideWithValue(FakeOrganizeApi()),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('整理'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('总结'));
    await tester.pump(const Duration(milliseconds: 300));
    await tester.tap(find.text('保存为笔记'));
    await tester.pumpAndSettle();

    expect(FakeOrganizeApi.savedContent, '整理后的内容');
    expect(FakeOrganizeApi.savedSourceDocumentIds, ['document-id']);
    expect(find.text('saved:saved-note-id'), findsOneWidget);
  });

  testWidgets('opens a related document from the organize menu',
      (tester) async {
    final router = GoRouter(
      initialLocation: '/detail',
      routes: [
        GoRoute(
          path: '/detail',
          builder: (context, state) => const DocumentDetailPage(
            documentId: 'document-id',
          ),
        ),
        GoRoute(
          path: '/app/documents/:id',
          builder: (context, state) => Scaffold(
            body: Text('related:${state.pathParameters['id']}'),
          ),
        ),
      ],
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          documentDetailProvider(
            (id: 'document-id', contentOffset: 0),
          ).overrideWith(
            (ref) async => const KnowledgeDocument(
              id: 'document-id',
              title: '测试资料',
              sourceType: 'note',
              status: 'indexed',
              tags: [],
              content: '资料内容',
            ),
          ),
          documentsApiProvider.overrideWithValue(RelatedDocumentsApi()),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('整理'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('找相关资料'));
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('RAG 关联笔记'), findsOneWidget);
    expect(find.textContaining('相关度 82%'), findsOneWidget);
    await tester.tap(find.text('RAG 关联笔记'));
    await tester.pumpAndSettle();

    expect(find.text('related:related-id'), findsOneWidget);
  });

  testWidgets('loads a citation window from its global offset', (tester) async {
    const contentOffset = 55000;
    const highlight = '精确深层引用';
    final prefix = List.filled(5000, '前').join();
    final content = '$prefix$highlight后文';

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          documentDetailProvider(
            (id: 'document-id', contentOffset: contentOffset),
          ).overrideWith(
            (ref) async => KnowledgeDocument(
              id: 'document-id',
              title: '大资料',
              sourceType: 'note',
              status: 'indexed',
              tags: const [],
              content: content,
              contentOffset: contentOffset,
              contentLength: 60008,
            ),
          ),
        ],
        child: const MaterialApp(
          home: DocumentDetailPage(
            documentId: 'document-id',
            highlightText: highlight,
            highlightStart: 60000,
            highlightEnd: 60006,
          ),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text(highlight), findsOneWidget);
    expect(find.text(prefix), findsOneWidget);
    expect(find.text('后文'), findsOneWidget);
  });

  testWidgets('loads previous and next content windows', (tester) async {
    const firstQuery = (id: 'document-id', contentOffset: 0);
    const secondQuery = (id: 'document-id', contentOffset: 50000);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          documentDetailProvider(firstQuery).overrideWith(
            (ref) async => const KnowledgeDocument(
              id: 'document-id',
              title: '大资料',
              sourceType: 'note',
              status: 'indexed',
              tags: [],
              content: '第一段正文',
              contentLength: 100000,
              contentTruncated: true,
            ),
          ),
          documentDetailProvider(secondQuery).overrideWith(
            (ref) async => const KnowledgeDocument(
              id: 'document-id',
              title: '大资料',
              sourceType: 'note',
              status: 'indexed',
              tags: [],
              content: '第二段正文',
              contentOffset: 50000,
              contentLength: 100000,
            ),
          ),
        ],
        child: const MaterialApp(
          home: DocumentDetailPage(documentId: 'document-id'),
        ),
      ),
    );

    await tester.pumpAndSettle();
    expect(find.text('第一段正文'), findsOneWidget);

    await tester.tap(find.byTooltip('下一段'));
    await tester.pumpAndSettle();
    expect(find.text('第二段正文'), findsOneWidget);

    await tester.tap(find.byTooltip('上一段'));
    await tester.pumpAndSettle();
    expect(find.text('第一段正文'), findsOneWidget);
  });
}

class FakeOrganizeApi extends OrganizeApi {
  FakeOrganizeApi() : super(Dio());

  static String? savedContent;
  static List<String>? savedSourceDocumentIds;

  @override
  Future<OrganizeResult> organizeDocument({
    required String documentId,
    String mode = 'summary',
    bool saveAsNote = false,
  }) async {
    return const OrganizeResult(
      mode: 'summary',
      result: '整理后的内容',
      sourceDocumentIds: ['document-id'],
    );
  }

  @override
  Future<String> saveResult({
    required String title,
    required String result,
    required List<String> sourceDocumentIds,
  }) async {
    savedContent = result;
    savedSourceDocumentIds = sourceDocumentIds;
    return 'saved-note-id';
  }
}

class RelatedDocumentsApi extends DocumentsApi {
  RelatedDocumentsApi() : super(Dio());

  @override
  Future<List<RelatedKnowledgeDocument>> getRelatedDocuments(
    String id, {
    int limit = 5,
  }) async {
    return const [
      RelatedKnowledgeDocument(
        documentId: 'related-id',
        title: 'RAG 关联笔记',
        sourceType: 'note',
        matchedText: '混合检索与重排相关内容',
        score: 0.82,
      ),
    ];
  }
}
