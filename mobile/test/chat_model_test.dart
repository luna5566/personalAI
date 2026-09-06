import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/chat/models/chat.dart';

void main() {
  test('conversation list item accepts an omitted scope', () {
    final conversation = ConversationSummary.fromJson({
      'id': 'conversation-id',
      'title': '会话',
      'created_at': '2026-07-19T12:00:00Z',
      'updated_at': '2026-07-19T12:05:00Z',
    });

    expect(conversation.tags, isEmpty);
    expect(conversation.documentIds, isEmpty);
    expect(conversation.sourceTypes, isEmpty);
  });
}
