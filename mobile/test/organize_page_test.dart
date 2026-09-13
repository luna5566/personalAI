import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:personal_ai_mobile/features/documents/models/document.dart';
import 'package:personal_ai_mobile/features/documents/providers/documents_provider.dart';
import 'package:personal_ai_mobile/features/organize/data/organize_api.dart';
import 'package:personal_ai_mobile/features/organize/providers/organize_provider.dart';
import 'package:personal_ai_mobile/features/organize/ui/organize_page.dart';
import 'package:personal_ai_mobile/features/tags/providers/tags_provider.dart';

void main() {
  setUp(() {
    FakeOrganizeController.lastDocumentIds = const [];
  });

  testWidgets('shows open action after saving organize result', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith((ref) async => const []),
          selectableDocumentsProvider.overrideWith(
            (ref) async => const [],
          ),
          organizeControllerProvider.overrideWith(FakeOrganizeController.new),
        ],
        child: const MaterialApp(home: OrganizePage()),
      ),
    );

    await tester.tap(find.text('保存为新笔记'));
    await tester.pump();
    await tester.tap(find.text('整理最近 10 份资料'));
    await tester.pump();

    expect(find.text('已保存为新笔记'), findsOneWidget);
    expect(find.text('打开'), findsOneWidget);
    expect(find.text('整理结果内容'), findsOneWidget);
  });

  testWidgets('sends selected documents to organize collection',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith((ref) async => const []),
          selectableDocumentsProvider.overrideWith(
            (ref) async => const [
              KnowledgeDocument(
                id: 'document-a',
                title: '资料 A',
                sourceType: 'note',
                status: 'indexed',
                tags: [],
              ),
              KnowledgeDocument(
                id: 'document-b',
                title: '资料 B',
                sourceType: 'note',
                status: 'indexed',
                tags: [],
              ),
            ],
          ),
          organizeControllerProvider.overrideWith(FakeOrganizeController.new),
        ],
        child: const MaterialApp(home: OrganizePage()),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.text('资料 A'));
    await tester.pump();
    await tester.tap(find.text('资料 B'));
    await tester.pump();
    await tester.tap(find.text('整理已选资料'));
    await tester.pump();

    expect(
        FakeOrganizeController.lastDocumentIds, ['document-a', 'document-b']);
  });

  testWidgets('continues asking with the organized source documents',
      (tester) async {
    final router = GoRouter(
      initialLocation: '/organize',
      routes: [
        GoRoute(
          path: '/organize',
          builder: (context, state) => const OrganizePage(),
        ),
        GoRoute(
          path: '/app/chat',
          builder: (context, state) => Scaffold(
            body: Text('scope:${state.uri.queryParameters['documentIds']}'),
          ),
        ),
      ],
    );
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tagsProvider.overrideWith((ref) async => const []),
          selectableDocumentsProvider.overrideWith((ref) async => const []),
          organizeControllerProvider.overrideWith(FakeOrganizeController.new),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.text('整理最近 10 份资料'));
    await tester.pump();
    await tester.tap(find.text('继续追问'));
    await tester.pumpAndSettle();

    expect(find.text('scope:document-a,document-b'), findsOneWidget);
  });
}

class FakeOrganizeController extends OrganizeController {

  static List<String> lastDocumentIds = const [];

  @override
  Future<void> organizeCollection({
    required String mode,
    String? tag,
    List<String> documentIds = const [],
    required bool saveAsNote,
  }) async {
    lastDocumentIds = documentIds;
    state = const AsyncData(
      OrganizeResult(
        mode: 'themes',
        result: '整理结果内容',
        sourceDocumentIds: ['document-a', 'document-b'],
        savedDocumentId: 'saved-document-id',
      ),
    );
  }
}
