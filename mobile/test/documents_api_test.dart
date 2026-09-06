import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/documents/data/documents_api.dart';

void main() {
  test('loads a bounded document content window', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = DocumentDetailAdapter();
    dio.httpClientAdapter = adapter;

    final document = await DocumentsApi(dio).getDocument(
      'document-id',
      contentOffset: 55000,
    );

    expect(adapter.requestedContentOffset, 55000);
    expect(adapter.requestedContentLimit, 50000);
    expect(document.content, 'window content');
    expect(document.contentOffset, 55000);
    expect(document.contentLength, 120000);
    expect(document.contentTruncated, isTrue);
  });
}

class DocumentDetailAdapter implements HttpClientAdapter {
  int? requestedContentOffset;
  int? requestedContentLimit;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    expect(options.path, '/documents/document-id');
    requestedContentOffset = options.queryParameters['content_offset'] as int;
    requestedContentLimit = options.queryParameters['content_limit'] as int;
    return ResponseBody.fromString(
      jsonEncode({
        'id': 'document-id',
        'title': '大资料',
        'source_type': 'note',
        'status': 'indexed',
        'tags': <String>[],
        'content': 'window content',
        'content_source': 'cleaned_text',
        'content_offset': 55000,
        'content_length': 120000,
        'content_truncated': true,
      }),
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}
