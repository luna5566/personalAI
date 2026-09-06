import 'package:dio/dio.dart';

import '../models/tag.dart';

class TagsApi {
  const TagsApi(this._dio);

  final Dio _dio;

  Future<List<KnowledgeTag>> listTags() async {
    final page = await listTagPage(pageSize: 100);
    return page.items;
  }

  Future<TagPage> listTagPage({
    int page = 1,
    int pageSize = 20,
    String? keyword,
  }) async {
    final response = await _dio.get<List<dynamic>>(
      '/tags',
      queryParameters: {
        'page': page,
        'page_size': pageSize,
        if (keyword != null && keyword.trim().isNotEmpty)
          'keyword': keyword.trim(),
      },
    );
    final total = int.tryParse(
          response.headers.value('x-total-count') ?? '',
        ) ??
        0;
    return TagPage(
      items: response.data!
          .map(
            (item) => KnowledgeTag.fromJson(item as Map<String, dynamic>),
          )
          .toList(),
      total: total,
      page: page,
      pageSize: pageSize,
    );
  }

  Future<KnowledgeTag> updateTag(String id, {required String name}) async {
    final response = await _dio.patch<Map<String, dynamic>>(
      '/tags/$id',
      data: {'name': name},
    );
    return KnowledgeTag.fromJson(response.data!);
  }

  Future<void> deleteTag(String id) async {
    await _dio.delete<void>('/tags/$id');
  }
}

class TagPage {
  const TagPage({
    required this.items,
    required this.total,
    required this.page,
    required this.pageSize,
  });

  final List<KnowledgeTag> items;
  final int total;
  final int page;
  final int pageSize;

  int get totalPages => total == 0 ? 1 : (total + pageSize - 1) ~/ pageSize;
  bool get hasPrevious => page > 1;
  bool get hasNext => page < totalPages;
}
