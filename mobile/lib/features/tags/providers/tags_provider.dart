import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/cache_state.dart';
import '../data/tags_api.dart';
import '../models/tag.dart';

final tagsApiProvider = Provider<TagsApi>((ref) {
  ref.watch(cacheRevalidationProvider);
  return TagsApi(ref.watch(dioProvider));
});

final tagsProvider = FutureProvider.autoDispose<List<KnowledgeTag>>((ref) {
  return ref.watch(tagsApiProvider).listTags();
});

typedef TagsPageQuery = ({String? keyword, int page});

final tagsPageProvider =
    FutureProvider.autoDispose.family<TagPage, TagsPageQuery>((ref, query) {
  return ref.watch(tagsApiProvider).listTagPage(
        page: query.page,
        keyword: query.keyword,
      );
});
