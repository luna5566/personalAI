import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/jobs/data/jobs_api.dart';
import 'package:personal_ai_mobile/features/jobs/models/job.dart';
import 'package:personal_ai_mobile/features/jobs/providers/jobs_provider.dart';
import 'package:personal_ai_mobile/features/jobs/ui/job_history_page.dart';

void main() {
  testWidgets('renders job type status progress and failure details',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          jobsPageProvider((page: 1, status: null)).overrideWith(
            (ref) async => JobPage(
              items: [
                IndexJob(
                  id: 'failed-job',
                  jobType: 'index_document',
                  status: 'failed',
                  progress: 100,
                  retryOfJobId: 'original-job',
                  message: '处理失败',
                  errorMessage: '资料中没有可索引内容',
                  updatedAt: DateTime(2026, 7, 17, 10, 5),
                ),
                IndexJob(
                  id: 'cancelled-job',
                  jobType: 'rebuild_embeddings',
                  status: 'cancelled',
                  progress: 35,
                  message: '任务已取消',
                  updatedAt: DateTime(2026, 7, 17, 10, 6),
                ),
              ],
              total: 2,
              page: 1,
              pageSize: 20,
            ),
          ),
        ],
        child: const MaterialApp(home: JobHistoryPage()),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('任务历史'), findsOneWidget);
    expect(find.text('资料解析与索引'), findsOneWidget);
    expect(find.text('失败'), findsWidgets);
    expect(find.text('资料中没有可索引内容'), findsOneWidget);
    expect(find.text('重试任务'), findsOneWidget);
    expect(find.text('100%'), findsOneWidget);
    expect(find.text('个人资料索引重建'), findsOneWidget);
    expect(find.text('已取消'), findsWidgets);
  });

  testWidgets('moves to the next job page', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          jobsPageProvider((page: 1, status: null)).overrideWith(
            (ref) async => const JobPage(
              items: [
                IndexJob(
                  id: 'first-job',
                  jobType: 'index_document',
                  status: 'success',
                  progress: 100,
                  message: '第一页任务',
                ),
              ],
              total: 21,
              page: 1,
              pageSize: 20,
            ),
          ),
          jobsPageProvider((page: 2, status: null)).overrideWith(
            (ref) async => const JobPage(
              items: [
                IndexJob(
                  id: 'second-job',
                  jobType: 'rebuild_all_embeddings',
                  status: 'success',
                  progress: 100,
                  message: '第二页任务',
                ),
              ],
              total: 21,
              page: 2,
              pageSize: 20,
            ),
          ),
        ],
        child: const MaterialApp(home: JobHistoryPage()),
      ),
    );

    await tester.pumpAndSettle();
    expect(find.text('第一页任务'), findsOneWidget);

    await tester.tap(find.byTooltip('下一页'));
    await tester.pumpAndSettle();

    expect(find.text('第二页任务'), findsOneWidget);
    expect(find.text('全部资料索引重建'), findsOneWidget);
    expect(find.text('第 2 / 2 页，共 21 条'), findsOneWidget);
  });
}
