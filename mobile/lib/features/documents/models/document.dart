const documentDetailContentPageSize = 50000;

class KnowledgeDocument {
  const KnowledgeDocument({
    required this.id,
    required this.title,
    required this.sourceType,
    required this.status,
    required this.tags,
    this.summary,
    this.content,
    this.contentSource,
    this.contentOffset = 0,
    this.contentLength = 0,
    this.contentTruncated = false,
    this.errorMessage,
    this.createdAt,
    this.updatedAt,
  });

  final String id;
  final String title;
  final String sourceType;
  final String status;
  final List<String> tags;
  final String? summary;
  final String? content;
  final String? contentSource;
  final int contentOffset;
  final int contentLength;
  final bool contentTruncated;
  final String? errorMessage;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  bool get isFailed => status == 'failed';

  bool get isCancelled => status == 'cancelled';

  bool get isIndexed => status == 'indexed';

  bool get isProcessing => !isFailed && !isCancelled && !isIndexed;

  String get statusLabel {
    return switch (status) {
      'uploaded' => '已上传',
      'parsing' => '解析中',
      'parsed' => '已解析',
      'summarizing' => '总结中',
      'chunking' => '切片中',
      'embedding' => '索引中',
      'indexed' => '已入库',
      'cancelled' => '已取消',
      'failed' => '处理失败',
      _ => status,
    };
  }

  String get sourceTypeLabel {
    return switch (sourceType) {
      'note' => '笔记',
      'pdf' => 'PDF',
      'txt' => 'TXT',
      'markdown' => 'Markdown',
      'image' => '图片',
      'audio' => '音频',
      'docx' => 'Word',
      'html' => '网页',
      'excel' => '表格',
      'epub' => 'EPUB',
      'ai_generated' => 'AI 生成',
      _ => sourceType,
    };
  }

  factory KnowledgeDocument.fromJson(Map<String, dynamic> json) {
    return KnowledgeDocument(
      id: json['id'] as String,
      title: json['title'] as String,
      sourceType: json['source_type'] as String,
      status: json['status'] as String,
      tags: (json['tags'] as List? ?? const [])
          .map((item) => item.toString())
          .toList(),
      summary: json['summary'] as String?,
      content: json['content'] as String? ??
          json['cleaned_text'] as String? ??
          json['raw_text'] as String?,
      contentSource: json['content_source'] as String?,
      contentOffset: json['content_offset'] as int? ?? 0,
      contentLength: json['content_length'] as int? ?? 0,
      contentTruncated: json['content_truncated'] as bool? ?? false,
      errorMessage: json['error_message'] as String?,
      createdAt: json['created_at'] == null
          ? null
          : DateTime.parse(json['created_at'] as String),
      updatedAt: json['updated_at'] == null
          ? null
          : DateTime.parse(json['updated_at'] as String),
    );
  }
}

class DocumentStats {
  const DocumentStats({
    required this.total,
    required this.indexed,
    required this.processing,
    required this.failed,
    required this.storageBytes,
    this.cancelled = 0,
  });

  final int total;
  final int indexed;
  final int processing;
  final int failed;
  final int cancelled;
  final int storageBytes;

  factory DocumentStats.fromJson(Map<String, dynamic> json) {
    return DocumentStats(
      total: json['total'] as int,
      indexed: json['indexed'] as int,
      processing: json['processing'] as int,
      failed: json['failed'] as int,
      cancelled: json['cancelled'] as int? ?? 0,
      storageBytes: json['storage_bytes'] as int? ?? 0,
    );
  }
}

class RelatedKnowledgeDocument {
  const RelatedKnowledgeDocument({
    required this.documentId,
    required this.title,
    required this.sourceType,
    required this.matchedText,
    required this.score,
  });

  final String documentId;
  final String title;
  final String sourceType;
  final String matchedText;
  final double score;

  String get sourceTypeLabel {
    return switch (sourceType) {
      'note' => '笔记',
      'pdf' => 'PDF',
      'txt' => 'TXT',
      'markdown' => 'Markdown',
      'image' => '图片',
      'audio' => '音频',
      'docx' => 'Word',
      'html' => '网页',
      'excel' => '表格',
      'epub' => 'EPUB',
      'ai_generated' => 'AI 生成',
      _ => sourceType,
    };
  }

  factory RelatedKnowledgeDocument.fromJson(Map<String, dynamic> json) {
    return RelatedKnowledgeDocument(
      documentId: json['document_id'] as String,
      title: json['title'] as String,
      sourceType: json['source_type'] as String,
      matchedText: json['matched_text'] as String,
      score: (json['score'] as num).toDouble(),
    );
  }
}
