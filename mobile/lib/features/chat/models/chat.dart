class Citation {
  const Citation({
    required this.documentId,
    required this.documentTitle,
    required this.text,
    required this.score,
    this.chunkId,
    this.chunkIndex,
    this.startOffset,
    this.endOffset,
    this.sourceType,
    this.pageNumber,
    this.sectionTitle,
  });

  final String documentId;
  final String documentTitle;
  final String text;
  final double score;
  final String? chunkId;
  final int? chunkIndex;
  final int? startOffset;
  final int? endOffset;
  final String? sourceType;
  final int? pageNumber;
  final String? sectionTitle;

  String get metadataLabel {
    final sourceLabel = switch (sourceType) {
      'note' => '笔记',
      'pdf' => 'PDF',
      'txt' => 'TXT',
      'markdown' => 'Markdown',
      'image' => '图片',
      'audio' => '音频',
      'ai_generated' => 'AI 生成',
      _ => null,
    };
    final locationLabel = pageNumber != null
        ? '第 $pageNumber 页'
        : sectionTitle != null && sectionTitle!.isNotEmpty
            ? sectionTitle
            : chunkIndex != null
                ? '片段 ${chunkIndex! + 1}'
                : null;
    return [
      ?sourceLabel,
      ?locationLabel,
      '相关度 ${(score.clamp(0, 1) * 100).round()}%',
    ].join(' · ');
  }

  factory Citation.fromJson(Map<String, dynamic> json) {
    return Citation(
      documentId: json['document_id'] as String,
      documentTitle: json['document_title'] as String,
      text: json['text'] as String,
      score: (json['score'] as num).toDouble(),
      chunkId: json['chunk_id'] as String?,
      chunkIndex: json['chunk_index'] as int?,
      startOffset: json['start_offset'] as int?,
      endOffset: json['end_offset'] as int?,
      sourceType: json['source_type'] as String?,
      pageNumber: json['page_number'] as int?,
      sectionTitle: json['section_title'] as String?,
    );
  }
}

class ChatResponse {
  const ChatResponse({
    required this.conversationId,
    required this.answer,
    required this.citations,
    required this.suggestedQuestions,
  });

  final String conversationId;
  final String answer;
  final List<Citation> citations;
  final List<String> suggestedQuestions;

  factory ChatResponse.fromJson(Map<String, dynamic> json) {
    return ChatResponse(
      conversationId: json['conversation_id'] as String,
      answer: json['answer'] as String,
      citations: (json['citations'] as List<dynamic>)
          .map((item) => Citation.fromJson(item as Map<String, dynamic>))
          .toList(),
      suggestedQuestions: (json['suggested_questions'] as List<dynamic>)
          .map((item) => item.toString())
          .toList(),
    );
  }
}

class ConversationSummary {
  const ConversationSummary({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.updatedAt,
    this.tags = const [],
    this.documentIds = const [],
    this.sourceTypes = const [],
    this.recentDays,
  });

  final String id;
  final String title;
  final DateTime createdAt;
  final DateTime updatedAt;
  final List<String> tags;
  final List<String> documentIds;
  final List<String> sourceTypes;
  final int? recentDays;

  factory ConversationSummary.fromJson(Map<String, dynamic> json) {
    final scope = json['scope'] as Map<String, dynamic>? ?? const {};
    final rawRecentDays = scope['recent_days'];
    int? recentDays;
    if (rawRecentDays is int) {
      recentDays = rawRecentDays;
    } else if (rawRecentDays is num) {
      recentDays = rawRecentDays.toInt();
    }
    return ConversationSummary(
      id: json['id'] as String,
      title: json['title'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
      updatedAt: DateTime.parse(json['updated_at'] as String),
      tags: (scope['tags'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(),
      documentIds: (scope['document_ids'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(),
      sourceTypes: (scope['source_types'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(),
      recentDays: recentDays,
    );
  }
}

class ChatStreamEvent {
  const ChatStreamEvent._({
    required this.type,
    this.conversationId,
    this.deltaText,
    this.answer,
    this.citations = const [],
    this.suggestedQuestions = const [],
    this.message,
  });

  final String type;
  final String? conversationId;
  final String? deltaText;
  final String? answer;
  final List<Citation> citations;
  final List<String> suggestedQuestions;
  final String? message;

  bool get isMeta => type == 'meta';
  bool get isDelta => type == 'delta';
  bool get isDone => type == 'done';
  bool get isError => type == 'error';

  factory ChatStreamEvent.done({
    required String conversationId,
    required String answer,
    required List<Citation> citations,
    required List<String> suggestedQuestions,
  }) {
    return ChatStreamEvent._(
      type: 'done',
      conversationId: conversationId,
      answer: answer,
      citations: citations,
      suggestedQuestions: suggestedQuestions,
    );
  }

  factory ChatStreamEvent.fromJson(String type, Map<String, dynamic> json) {
    return ChatStreamEvent._(
      type: type,
      conversationId: json['conversation_id'] as String?,
      deltaText: json['text'] as String?,
      answer: json['answer'] as String?,
      citations: (json['citations'] as List<dynamic>? ?? const [])
          .map((item) => Citation.fromJson(item as Map<String, dynamic>))
          .toList(),
      suggestedQuestions: (json['suggested_questions'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(),
      message: json['message'] as String?,
    );
  }
}

class ChatHistoryMessage {
  const ChatHistoryMessage({
    required this.id,
    required this.conversationId,
    required this.role,
    required this.content,
    required this.citations,
    required this.createdAt,
    this.contentTruncated = false,
  });

  final String id;
  final String conversationId;
  final String role;
  final String content;
  final bool contentTruncated;
  final List<Citation> citations;
  final DateTime createdAt;

  ChatMessage toChatMessage() {
    return ChatMessage(
      role: role == 'assistant'
          ? ChatMessageRole.assistant
          : ChatMessageRole.user,
      text: content,
      contentTruncated: contentTruncated,
      citations: citations,
    );
  }

  factory ChatHistoryMessage.fromJson(Map<String, dynamic> json) {
    return ChatHistoryMessage(
      id: json['id'] as String,
      conversationId: json['conversation_id'] as String,
      role: json['role'] as String,
      content: json['content'] as String,
      contentTruncated: json['content_truncated'] as bool? ?? false,
      citations: (json['citations'] as List<dynamic>? ?? const [])
          .map((item) => Citation.fromJson(item as Map<String, dynamic>))
          .toList(),
      createdAt: DateTime.parse(json['created_at'] as String),
    );
  }
}

enum ChatMessageRole { user, assistant }

class ChatMessage {
  const ChatMessage({
    required this.role,
    required this.text,
    this.citations = const [],
    this.suggestedQuestions = const [],
    this.contentTruncated = false,
  });

  final ChatMessageRole role;
  final String text;
  final bool contentTruncated;
  final List<Citation> citations;
  final List<String> suggestedQuestions;
}
