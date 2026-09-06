import 'package:dio/dio.dart';

class OrganizeApi {
  const OrganizeApi(this._dio);

  final Dio _dio;

  Future<OrganizeResult> organizeCollection({
    String mode = 'themes',
    String? tag,
    List<String> documentIds = const [],
    bool saveAsNote = false,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/organize/collection',
      data: {
        'document_ids': documentIds,
        if (tag != null && tag.isNotEmpty) 'tag': tag,
        'mode': mode,
        'save_as_note': saveAsNote,
      },
    );
    return OrganizeResult.fromJson(response.data!);
  }

  Future<OrganizeResult> organizeDocument({
    required String documentId,
    String mode = 'summary',
    bool saveAsNote = false,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/organize/document',
      data: {
        'document_id': documentId,
        'mode': mode,
        'save_as_note': saveAsNote,
      },
    );
    return OrganizeResult.fromJson(response.data!);
  }

  Future<String> saveResult({
    required String title,
    required String result,
    required List<String> sourceDocumentIds,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/organize/save-result',
      data: {
        'title': title,
        'result': result,
        'source_document_ids': sourceDocumentIds,
      },
    );
    return response.data!['saved_document_id'] as String;
  }
}

class OrganizeResult {
  const OrganizeResult({
    required this.mode,
    required this.result,
    required this.sourceDocumentIds,
    this.savedDocumentId,
  });

  final String mode;
  final String result;
  final List<String> sourceDocumentIds;
  final String? savedDocumentId;

  factory OrganizeResult.fromJson(Map<String, dynamic> json) {
    return OrganizeResult(
      mode: json['mode'] as String,
      result: json['result'] as String,
      sourceDocumentIds: (json['source_document_ids'] as List<dynamic>)
          .map((item) => item.toString())
          .toList(),
      savedDocumentId: json['saved_document_id'] as String?,
    );
  }
}
