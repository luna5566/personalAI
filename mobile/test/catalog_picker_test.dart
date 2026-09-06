import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/documents/data/documents_api.dart';
import 'package:personal_ai_mobile/features/documents/models/document.dart';
import 'package:personal_ai_mobile/features/documents/providers/documents_provider.dart';
import 'package:personal_ai_mobile/features/documents/widgets/document_picker_dialog.dart';
import 'package:personal_ai_mobile/features/tags/data/tags_api.dart';
import 'package:personal_ai_mobile/features/tags/models/tag.dart';
import 'package:personal_ai_mobile/features/tags/providers/tags_provider.dart';
import 'package:personal_ai_mobile/features/tags/widgets/tag_picker_dialog.dart';

void main() {
  testWidgets('tag picker searches and selects beyond the first page',
      (tester) async {
    final api = PickerTagsApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [tagsApiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: _TagPickerHost()),
      ),
    );

    await tester.tap(find.text('打开标签'));
    await tester.pumpAndSettle();
    expect(api.requests, [(keyword: null, page: 1)]);
    expect(find.text('tag-001'), findsOneWidget);

    await tester.tap(find.byTooltip('下一页'));
    await tester.pumpAndSettle();
    expect(api.requests.last, (keyword: null, page: 2));
    expect(find.text('tag-021'), findsOneWidget);

    await tester.enterText(find.byType(TextField).last, '远端');
    await tester.pump(const Duration(milliseconds: 301));
    await tester.pumpAndSettle();
    expect(api.requests.last, (keyword: '远端', page: 1));
    expect(find.text('远端标签'), findsOneWidget);

    await tester.tap(find.text('远端标签'));
    await tester.tap(find.text('确定'));
    await tester.pumpAndSettle();
    expect(find.text('标签结果：远端标签'), findsOneWidget);
  });

  testWidgets('document picker searches and returns a cross-page selection',
      (tester) async {
    final api = PickerDocumentsApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [documentsApiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: _DocumentPickerHost()),
      ),
    );

    await tester.tap(find.text('打开资料'));
    await tester.pumpAndSettle();
    expect(api.requests, [(keyword: null, page: 1)]);

    await tester.tap(find.byTooltip('下一页'));
    await tester.pumpAndSettle();
    expect(api.requests.last, (keyword: null, page: 2));
    expect(find.text('document-021'), findsOneWidget);

    await tester.enterText(find.byType(TextField).last, '目标');
    await tester.pump(const Duration(milliseconds: 301));
    await tester.pumpAndSettle();
    expect(api.requests.last, (keyword: '目标', page: 1));
    expect(find.text('目标资料'), findsOneWidget);

    await tester.tap(find.text('目标资料'));
    await tester.tap(find.text('确定'));
    await tester.pumpAndSettle();
    expect(find.text('资料结果：target-document'), findsOneWidget);
  });
}

class _TagPickerHost extends StatefulWidget {
  const _TagPickerHost();

  @override
  State<_TagPickerHost> createState() => _TagPickerHostState();
}

class _TagPickerHostState extends State<_TagPickerHost> {
  String _result = '';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          TextButton(
            onPressed: () async {
              final result = await showTagPickerDialog(
                context,
                selectedNames: const {},
                maxSelection: 20,
              );
              if (mounted && result != null) {
                setState(() => _result = result.join(','));
              }
            },
            child: const Text('打开标签'),
          ),
          Text('标签结果：$_result'),
        ],
      ),
    );
  }
}

class _DocumentPickerHost extends StatefulWidget {
  const _DocumentPickerHost();

  @override
  State<_DocumentPickerHost> createState() => _DocumentPickerHostState();
}

class _DocumentPickerHostState extends State<_DocumentPickerHost> {
  String _result = '';

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Column(
        children: [
          TextButton(
            onPressed: () async {
              final result = await showDocumentPickerDialog(
                context,
                selectedIds: const {},
                maxSelection: 20,
              );
              if (mounted && result != null) {
                setState(() => _result = result.ids.join(','));
              }
            },
            child: const Text('打开资料'),
          ),
          Text('资料结果：$_result'),
        ],
      ),
    );
  }
}

class PickerTagsApi extends TagsApi {
  PickerTagsApi() : super(Dio());

  final List<TagsPageQuery> requests = [];

  @override
  Future<TagPage> listTagPage({
    int page = 1,
    int pageSize = 20,
    String? keyword,
  }) async {
    requests.add((keyword: keyword, page: page));
    if (keyword != null) {
      return TagPage(
        items: const [KnowledgeTag(id: 'remote-tag', name: '远端标签')],
        total: 1,
        page: page,
        pageSize: pageSize,
      );
    }
    final start = (page - 1) * pageSize + 1;
    return TagPage(
      items: [
        for (var number = start; number < start + pageSize; number += 1)
          KnowledgeTag(
            id: 'tag-$number',
            name: 'tag-${number.toString().padLeft(3, '0')}',
          ),
      ],
      total: 41,
      page: page,
      pageSize: pageSize,
    );
  }
}

class PickerDocumentsApi extends DocumentsApi {
  PickerDocumentsApi() : super(Dio());

  final List<SelectableDocumentsPageQuery> requests = [];

  @override
  Future<DocumentPage> listDocumentsPage({
    int page = 1,
    int pageSize = 20,
    String? tag,
    String? keyword,
    String? sourceType,
    String? status,
  }) async {
    requests.add((keyword: keyword, page: page));
    if (keyword != null) {
      return DocumentPage(
        items: const [
          KnowledgeDocument(
            id: 'target-document',
            title: '目标资料',
            sourceType: 'note',
            status: 'indexed',
            tags: [],
          ),
        ],
        total: 1,
        page: page,
        pageSize: pageSize,
      );
    }
    final start = (page - 1) * pageSize + 1;
    return DocumentPage(
      items: [
        for (var number = start; number < start + pageSize; number += 1)
          KnowledgeDocument(
            id: 'document-$number',
            title: 'document-${number.toString().padLeft(3, '0')}',
            sourceType: 'note',
            status: 'indexed',
            tags: const [],
          ),
      ],
      total: 41,
      page: page,
      pageSize: pageSize,
    );
  }
}
