import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/documents/data/documents_api.dart';
import 'package:personal_ai_mobile/features/documents/models/document.dart';
import 'package:personal_ai_mobile/features/documents/providers/documents_provider.dart';
import 'package:personal_ai_mobile/features/documents/ui/documents_page.dart';
import 'package:personal_ai_mobile/features/tags/models/tag.dart';
import 'package:personal_ai_mobile/features/tags/providers/tags_provider.dart';

void main() {
  setUp(FakeDocumentsApi.reset);

  testWidgets('deletes selected documents in batch', (tester) async {
    await _pumpDocumentsPage(tester);

    await tester.longPress(find.text('资料 A'));
    await tester.pump();
    await tester.tap(find.text('资料 B'));
    await tester.pump();

    expect(find.text('已选 2 条'), findsWidgets);

    await tester.tap(find.byTooltip('批量删除'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();

    expect(FakeDocumentsApi.deletedIds, ['document-a', 'document-b']);
  });

  testWidgets('appends tags to selected documents in batch', (tester) async {
    await _pumpDocumentsPage(tester);

    await tester.tap(find.byTooltip('批量管理'));
    await tester.pump();
    await tester.tap(find.byTooltip('批量改标签'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilterChip, '重要').last);
    await tester.pump();
    await tester.tap(find.text('追加标签'));
    await tester.pumpAndSettle();

    expect(FakeDocumentsApi.updatedTags['document-a'], ['旧标签', '重要']);
    expect(FakeDocumentsApi.updatedTags['document-b'], ['重要']);
  });

  testWidgets('shows source type filters', (tester) async {
    await _pumpDocumentsPage(tester);

    expect(find.widgetWithText(FilterChip, '全部类型'), findsOneWidget);
    expect(find.widgetWithText(FilterChip, '笔记'), findsOneWidget);
    expect(find.widgetWithText(FilterChip, 'PDF'), findsOneWidget);
    expect(find.widgetWithText(FilterChip, '图片'), findsOneWidget);
    expect(find.widgetWithText(FilterChip, '音频'), findsOneWidget);
    expect(find.widgetWithText(FilterChip, 'AI 生成'), findsOneWidget);
  });

  testWidgets('moves to the next document page', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith((ref) async => const []),
          documentsPageProvider((
            tag: null,
            keyword: null,
            page: 1,
            sourceType: null,
          )).overrideWith(
            (ref) async => DocumentPage(
              items: [_documents.first],
              total: 21,
              page: 1,
              pageSize: 20,
            ),
          ),
          documentsPageProvider((
            tag: null,
            keyword: null,
            page: 2,
            sourceType: null,
          )).overrideWith(
            (ref) async => DocumentPage(
              items: [_documents.last],
              total: 21,
              page: 2,
              pageSize: 20,
            ),
          ),
        ],
        child: const MaterialApp(home: DocumentsPage()),
      ),
    );

    await tester.pumpAndSettle();
    expect(find.text('资料 A'), findsOneWidget);

    await tester.tap(find.byTooltip('下一页'));
    await tester.pumpAndSettle();

    expect(find.text('资料 B'), findsOneWidget);
    expect(find.text('第 2 / 2 页，共 21 条'), findsOneWidget);
  });
}

Future<void> _pumpDocumentsPage(WidgetTester tester) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        tagsProvider.overrideWith(
          (ref) async => const [KnowledgeTag(id: 'tag-important', name: '重要')],
        ),
        documentsPageProvider((
          tag: null,
          keyword: null,
          page: 1,
          sourceType: null,
        )).overrideWith(
          (ref) async => const DocumentPage(
            items: _documents,
            total: 2,
            page: 1,
            pageSize: 20,
          ),
        ),
        documentsApiProvider.overrideWithValue(FakeDocumentsApi()),
      ],
      child: const MaterialApp(home: DocumentsPage()),
    ),
  );
  await tester.pumpAndSettle();
}

const _documents = [
  KnowledgeDocument(
    id: 'document-a',
    title: '资料 A',
    sourceType: 'note',
    status: 'indexed',
    tags: ['旧标签'],
  ),
  KnowledgeDocument(
    id: 'document-b',
    title: '资料 B',
    sourceType: 'note',
    status: 'indexed',
    tags: [],
  ),
];

class FakeDocumentsApi extends DocumentsApi {
  FakeDocumentsApi() : super(Dio());

  static List<String> deletedIds = [];
  static Map<String, List<String>> updatedTags = {};

  static void reset() {
    deletedIds = [];
    updatedTags = {};
  }

  @override
  Future<KnowledgeDocument> updateDocument(
    String id, {
    String? title,
    List<String>? tags,
  }) async {
    updatedTags[id] = tags ?? const [];
    return _documents.firstWhere((document) => document.id == id);
  }

  @override
  Future<void> deleteDocument(String id) async {
    deletedIds.add(id);
  }
}
