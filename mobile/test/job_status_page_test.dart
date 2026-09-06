import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/jobs/models/job.dart';
import 'package:personal_ai_mobile/features/jobs/providers/jobs_provider.dart';
import 'package:personal_ai_mobile/features/jobs/ui/job_status_page.dart';

void main() {
  testWidgets('global rebuild can return to documents after success',
      (tester) async {
    const jobId = 'global-job';
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          jobProvider(jobId).overrideWith(
            (ref) async => const IndexJob(
              id: jobId,
              jobType: 'rebuild_all_embeddings',
              status: 'success',
              progress: 100,
              message: '已重建全部资料索引',
            ),
          ),
        ],
        child: const MaterialApp(
          home: JobStatusPage(jobId: jobId),
        ),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('全部资料索引重建'), findsOneWidget);
    final button = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, '重建完成后返回资料库'),
    );
    expect(button.onPressed, isNotNull);
  });

  testWidgets('running job exposes cancellation action', (tester) async {
    const jobId = 'running-job';
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          jobProvider(jobId).overrideWith(
            (ref) async => const IndexJob(
              id: jobId,
              jobType: 'index_document',
              status: 'running',
              progress: 45,
              message: '正在切片',
            ),
          ),
        ],
        child: const MaterialApp(home: JobStatusPage(jobId: jobId)),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('取消任务'), findsOneWidget);
    expect(find.text('重新执行'), findsNothing);
  });

  testWidgets('cancelled job exposes retry action', (tester) async {
    const jobId = 'cancelled-job';
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          jobProvider(jobId).overrideWith(
            (ref) async => const IndexJob(
              id: jobId,
              jobType: 'index_document',
              status: 'cancelled',
              progress: 45,
              retryOfJobId: 'original-job',
              message: '资料处理已取消',
            ),
          ),
        ],
        child: const MaterialApp(home: JobStatusPage(jobId: jobId)),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('任务已取消'), findsOneWidget);
    expect(find.text('由历史任务重新执行'), findsOneWidget);
    expect(find.text('重新执行'), findsOneWidget);
    expect(find.text('取消任务'), findsNothing);
  });
}
