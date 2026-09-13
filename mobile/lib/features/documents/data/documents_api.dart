import 'dart:typed_data';

import 'package:dio/dio.dart';

import '../models/document.dart';

class DocumentsApi {
  const DocumentsApi(this._dio);

  final Dio _dio;

  Future<List<KnowledgeDocument>> listDocuments({
    String? tag,
    String? keyword,
    String? sourceType,
  }) async {
    final page = await listDocumentsPage(
      tag: tag,
      keyword: keyword,
      sourceType: sourceType,
    );
    return page.items;
  }

  Future<DocumentPage> listDocumentsPage({
    int page = 1,
    int pageSize = 20,
    String? tag,
    String? keyword,
    String? sourceType,
    String? status,
  }) async {
    final response = await _dio.get<Map<String, dynamic>>(
      '/documents',
      queryParameters: {
        'page': page,
        'page_size': pageSize,
        if (tag != null && tag.isNotEmpty) 'tag': tag,
        if (keyword != null && keyword.isNotEmpty) 'keyword': keyword,
        if (sourceType != null && sourceType.isNotEmpty)
          'source_type': sourceType,
        if (status != null && status.isNotEmpty) 'status': status,
      },
    );
    return DocumentPage.fromJson(response.data!);
  }

  /// 下载整份资料的 Markdown 导出（后端 /documents/{id}/export.md）。
  Future<Uint8List> exportMarkdownBytes(String id) async {
    final response = await _dio.get<List<int>>(
      '/documents/$id/export.md',
      options: Options(responseType: ResponseType.bytes),
    );
    return Uint8List.fromList(response.data ?? const <int>[]);
  }

  Future<KnowledgeDocument> getDocument(
    String id, {
    int contentOffset = 0,
    int contentLimit = documentDetailContentPageSize,
  }) async {
    final response = await _dio.get<Map<String, dynamic>>(
      '/documents/$id',
      queryParameters: {
        'content_offset': contentOffset,
        'content_limit': contentLimit,
      },
    );
    return KnowledgeDocument.fromJson(response.data!);
  }

  Future<DocumentStats> getDocumentStats() async {
    final response = await _dio.get<Map<String, dynamic>>('/documents/stats');
    return DocumentStats.fromJson(response.data!);
  }

  Future<List<RelatedKnowledgeDocument>> getRelatedDocuments(
    String id, {
    int limit = 5,
  }) async {
    final response = await _dio.get<List<dynamic>>(
      '/documents/$id/related',
      queryParameters: {'limit': limit},
    );
    return response.data!
        .map(
          (item) => RelatedKnowledgeDocument.fromJson(
            item as Map<String, dynamic>,
          ),
        )
        .toList();
  }

  Future<KnowledgeDocument> updateDocument(
    String id, {
    String? title,
    List<String>? tags,
  }) async {
    final response = await _dio.patch<Map<String, dynamic>>(
      '/documents/$id',
      data: {
        'title': ?title,
        'tags': ?tags,
      },
    );
    return KnowledgeDocument.fromJson(response.data!);
  }

  Future<void> deleteDocument(String id) async {
    await _dio.delete<void>('/documents/$id');
  }

  Future<KnowledgeDocument> createNote({
    required String title,
    required String content,
    List<String> tags = const [],
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/documents/note',
      data: {'title': title, 'content': content, 'tags': tags},
    );
    return KnowledgeDocument.fromJson(response.data!);
  }

  Future<DocumentUploadResult> uploadDocument({
    String? filePath,
    Uint8List? fileBytes,
    required String filename,
    String? title,
    List<String> tags = const [],
  }) async {
    final file = await _multipartFile(
      filePath: filePath,
      fileBytes: fileBytes,
      filename: filename,
    );
    final formData = FormData.fromMap({
      'file': file,
      if (title != null && title.trim().isNotEmpty) 'title': title.trim(),
      if (tags.isNotEmpty) 'tags': tags.join(','),
    });
    final response = await _dio.post<Map<String, dynamic>>(
      '/documents/upload',
      data: formData,
    );
    return DocumentUploadResult.fromJson(response.data!);
  }

  Future<MultipartFile> _multipartFile({
    required String filename,
    String? filePath,
    Uint8List? fileBytes,
  }) {
    if (fileBytes != null) {
      return Future.value(
        MultipartFile.fromBytes(fileBytes, filename: filename),
      );
    }
    if (filePath != null) {
      return MultipartFile.fromFile(filePath, filename: filename);
    }
    throw ArgumentError('Upload requires either a file path or file bytes.');
  }
}

class DocumentPage {
  const DocumentPage({
    required this.items,
    required this.total,
    required this.page,
    required this.pageSize,
  });

  final List<KnowledgeDocument> items;
  final int total;
  final int page;
  final int pageSize;

  int get totalPages => total == 0 ? 1 : (total + pageSize - 1) ~/ pageSize;
  bool get hasPrevious => page > 1;
  bool get hasNext => page < totalPages;

  factory DocumentPage.fromJson(Map<String, dynamic> json) {
    final items = json['items'] as List<dynamic>;
    return DocumentPage(
      items: items
          .map((item) =>
              KnowledgeDocument.fromJson(item as Map<String, dynamic>))
          .toList(),
      total: json['total'] as int,
      page: json['page'] as int,
      pageSize: json['page_size'] as int,
    );
  }
}

class DocumentUploadResult {
  const DocumentUploadResult({
    required this.documentId,
    required this.jobId,
    required this.filename,
    required this.status,
  });

  final String documentId;
  final String jobId;
  final String filename;
  final String status;

  factory DocumentUploadResult.fromJson(Map<String, dynamic> json) {
    return DocumentUploadResult(
      documentId: json['document_id'] as String,
      jobId: json['job_id'] as String,
      filename: json['filename'] as String,
      status: json['status'] as String,
    );
  }
}
