import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/cache_state.dart';
import '../data/documents_api.dart';
import '../models/document.dart';

final documentsApiProvider = Provider<DocumentsApi>((ref) {
  ref.watch(cacheRevalidationProvider);
  return DocumentsApi(ref.watch(dioProvider));
});

typedef DocumentsQuery = ({String? keyword, String? sourceType, String? tag});
typedef DocumentsPageQuery = ({
  String? keyword,
  int page,
  String? sourceType,
  String? tag,
});

final documentsProvider = FutureProvider.autoDispose
    .family<List<KnowledgeDocument>, DocumentsQuery>((ref, query) {
  return ref.watch(documentsApiProvider).listDocuments(
        tag: query.tag,
        keyword: query.keyword,
        sourceType: query.sourceType,
      );
});

final documentsPageProvider = FutureProvider.autoDispose
    .family<DocumentPage, DocumentsPageQuery>((ref, query) {
  return ref.watch(documentsApiProvider).listDocumentsPage(
        page: query.page,
        tag: query.tag,
        keyword: query.keyword,
        sourceType: query.sourceType,
      );
});

typedef DocumentDetailQuery = ({String id, int contentOffset});

final documentDetailProvider = FutureProvider.autoDispose
    .family<KnowledgeDocument, DocumentDetailQuery>((ref, query) {
  return ref.watch(documentsApiProvider).getDocument(
        query.id,
        contentOffset: query.contentOffset,
      );
});

final documentStatsProvider = FutureProvider.autoDispose<DocumentStats>((ref) {
  return ref.watch(documentsApiProvider).getDocumentStats();
});

final selectableDocumentsProvider =
    FutureProvider.autoDispose<List<KnowledgeDocument>>((ref) {
  return ref
      .watch(documentsApiProvider)
      .listDocumentsPage(pageSize: 100, status: 'indexed')
      .then((page) => page.items);
});

typedef SelectableDocumentsPageQuery = ({String? keyword, int page});

final selectableDocumentsPageProvider = FutureProvider.autoDispose
    .family<DocumentPage, SelectableDocumentsPageQuery>((ref, query) {
  return ref.watch(documentsApiProvider).listDocumentsPage(
        page: query.page,
        pageSize: 20,
        keyword: query.keyword,
        status: 'indexed',
      );
});
