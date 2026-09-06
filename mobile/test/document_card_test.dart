import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/documents/models/document.dart';
import 'package:personal_ai_mobile/features/documents/widgets/document_card.dart';

void main() {
  testWidgets('shows document source type and creation date', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: DocumentCard(
            document: KnowledgeDocument(
              id: 'document-id',
              title: '测试笔记',
              sourceType: 'note',
              status: 'indexed',
              tags: const [],
              createdAt: DateTime.utc(2026, 7, 17),
            ),
            onTap: () {},
          ),
        ),
      ),
    );

    expect(find.text('笔记 · 2026-07-17'), findsOneWidget);
    expect(find.text('已入库'), findsOneWidget);
  });
}
