import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/documents/data/documents_api.dart';
import 'package:personal_ai_mobile/features/documents/models/document.dart';
import 'package:personal_ai_mobile/features/documents/providers/documents_provider.dart';
import 'package:personal_ai_mobile/features/documents/ui/new_note_page.dart';

void main() {
  testWidgets('rejects an empty note before calling the API', (tester) async {
    final api = FakeNoteApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [documentsApiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: NewNotePage()),
      ),
    );

    await tester.tap(find.text('保存'));
    await tester.pump();

    expect(api.createCount, 0);
    expect(find.text('请输入笔记内容'), findsOneWidget);
  });

  testWidgets('shows a save error and re-enables the action', (tester) async {
    final api = FakeNoteApi(shouldFail: true);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [documentsApiProvider.overrideWithValue(api)],
        child: const MaterialApp(home: NewNotePage()),
      ),
    );

    await tester.enterText(find.byType(TextField).last, '有效内容');
    await tester.tap(find.text('保存'));
    await tester.pumpAndSettle();

    expect(api.createCount, 1);
    expect(find.text('保存笔记失败，请稍后重试'), findsOneWidget);
    expect(find.textContaining('network unavailable'), findsNothing);
    final button = tester.widget<FilledButton>(find.byType(FilledButton));
    expect(button.onPressed, isNotNull);
    expect(find.text('保存'), findsOneWidget);
  });
}

class FakeNoteApi extends DocumentsApi {
  FakeNoteApi({this.shouldFail = false}) : super(Dio());

  final bool shouldFail;
  int createCount = 0;

  @override
  Future<KnowledgeDocument> createNote({
    required String title,
    required String content,
    List<String> tags = const [],
  }) async {
    createCount += 1;
    if (shouldFail) {
      throw Exception('network unavailable');
    }
    return const KnowledgeDocument(
      id: 'note-id',
      title: '笔记',
      sourceType: 'note',
      status: 'indexed',
      tags: [],
    );
  }
}
