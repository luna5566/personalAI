import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/core/widgets/markdown_text.dart';

Widget _wrap(Widget child) => MaterialApp(
      theme: ThemeData(colorSchemeSeed: Colors.blue, useMaterial3: true),
      home: Scaffold(body: SingleChildScrollView(child: child)),
    );

void main() {
  testWidgets('renders headings, emphasis and list items as styled text', (
    tester,
  ) async {
    await tester.pumpWidget(
      _wrap(
        const MarkdownText(
          data: '# 标题\n\n**加粗** 内容\n\n- 第一项\n- 第二项\n',
        ),
      ),
    );
    await tester.pump();

    expect(find.text('标题'), findsOneWidget);
    expect(find.text('第一项'), findsOneWidget);
    expect(find.text('第二项'), findsOneWidget);
    expect(find.text('标题', findRichText: true), findsOneWidget);
    // 不应把 Markdown 标记符号原样显示出来。
    expect(find.textContaining('**'), findsNothing);
    expect(find.textContaining('# 标题'), findsNothing);
  });

  testWidgets('renders fenced code blocks as monospace sections', (
    tester,
  ) async {
    await tester.pumpWidget(
      _wrap(
        const MarkdownText(data: '说明：\n\n```dart\nprint("hi");\n```\n'),
      ),
    );
    await tester.pump();

    expect(find.textContaining('print("hi");'), findsOneWidget);
  });

  testWidgets('empty data renders nothing visible', (tester) async {
    await tester.pumpWidget(_wrap(const MarkdownText(data: '   \n')));
    await tester.pump();

    expect(find.byType(MarkdownText), findsOneWidget);
    expect(find.byType(RichText), findsNothing);
  });
}
