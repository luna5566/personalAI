import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/tags/data/tags_api.dart';
import 'package:personal_ai_mobile/features/tags/models/tag.dart';
import 'package:personal_ai_mobile/features/tags/providers/tags_provider.dart';
import 'package:personal_ai_mobile/features/tags/ui/tag_management_page.dart';

void main() {
  testWidgets('tag management paginates and searches on the server',
      (tester) async {
    final api = ManagementTagsApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [tagsApiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: TagManagementPage()),
      ),
    );

    await tester.pumpAndSettle();
    expect(api.requests, [(keyword: null, page: 1)]);
    expect(find.text('标签-1'), findsOneWidget);

    await tester.tap(find.byTooltip('下一页'));
    await tester.pumpAndSettle();
    expect(api.requests.last, (keyword: null, page: 2));
    expect(find.text('标签-2'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '检索');
    await tester.pump(const Duration(milliseconds: 301));
    await tester.pumpAndSettle();
    expect(api.requests.last, (keyword: '检索', page: 1));
    expect(find.text('检索结果'), findsOneWidget);
  });
}

class ManagementTagsApi extends TagsApi {
  ManagementTagsApi() : super(Dio());

  final List<TagsPageQuery> requests = [];

  @override
  Future<TagPage> listTagPage({
    int page = 1,
    int pageSize = 20,
    String? keyword,
  }) async {
    requests.add((keyword: keyword, page: page));
    return TagPage(
      items: [
        KnowledgeTag(
          id: 'tag-$page',
          name: keyword == null ? '标签-$page' : '检索结果',
        ),
      ],
      total: keyword == null ? 21 : 1,
      page: page,
      pageSize: pageSize,
    );
  }
}
