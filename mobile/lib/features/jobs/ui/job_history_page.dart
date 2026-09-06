import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/user_error_message.dart';
import '../../../core/widgets/async_state_view.dart';
import '../data/jobs_api.dart';
import '../models/job.dart';
import '../providers/jobs_provider.dart';

class JobHistoryPage extends ConsumerStatefulWidget {
  const JobHistoryPage({super.key});

  @override
  ConsumerState<JobHistoryPage> createState() => _JobHistoryPageState();
}

class _JobHistoryPageState extends ConsumerState<JobHistoryPage> {
  int _page = 1;
  String _status = 'all';
  Timer? _refreshTimer;

  JobsPageQuery get _query => (
        page: _page,
        status: _status == 'all' ? null : _status,
      );

  @override
  void initState() {
    super.initState();
    _refreshTimer = Timer.periodic(const Duration(seconds: 5), (_) {
      ref.invalidate(jobsPageProvider(_query));
    });
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final jobs = ref.watch(jobsPageProvider(_query));
    return Scaffold(
      appBar: AppBar(title: const Text('任务历史')),
      body: jobs.when(
        data: _buildContent,
        error: (error, _) => ErrorStateView(
          message: userFacingErrorMessage(
            error,
            fallback: '暂时无法加载任务历史',
          ),
          onRetry: () => ref.invalidate(jobsPageProvider(_query)),
        ),
        loading: () => const LoadingView(),
      ),
    );
  }

  Widget _buildContent(JobPage jobPage) {
    return RefreshIndicator(
      onRefresh: () => ref.refresh(jobsPageProvider(_query).future),
      child: ListView.separated(
        padding: const EdgeInsets.all(16),
        itemCount: jobPage.items.isEmpty ? 2 : jobPage.items.length + 2,
        separatorBuilder: (_, __) => const SizedBox(height: 10),
        itemBuilder: (context, index) {
          if (index == 0) {
            return DropdownButtonFormField<String>(
              key: const ValueKey('job-status-filter'),
              initialValue: _status,
              decoration: const InputDecoration(
                labelText: '任务状态',
                prefixIcon: Icon(Icons.filter_list),
              ),
              items: const [
                DropdownMenuItem(value: 'all', child: Text('全部状态')),
                DropdownMenuItem(value: 'pending', child: Text('等待处理')),
                DropdownMenuItem(value: 'running', child: Text('处理中')),
                DropdownMenuItem(
                    value: 'cancel_requested', child: Text('正在取消')),
                DropdownMenuItem(value: 'cancelled', child: Text('已取消')),
                DropdownMenuItem(value: 'success', child: Text('已完成')),
                DropdownMenuItem(value: 'failed', child: Text('失败')),
              ],
              onChanged: (value) {
                if (value == null) {
                  return;
                }
                setState(() {
                  _status = value;
                  _page = 1;
                });
              },
            );
          }
          if (jobPage.items.isEmpty) {
            return Padding(
              padding: const EdgeInsets.only(top: 80),
              child: Center(
                child: Text(_status == 'all' ? '还没有任务记录' : '当前状态下没有任务'),
              ),
            );
          }
          if (index == jobPage.items.length + 1) {
            return _JobPaginationBar(
              page: jobPage.page,
              totalPages: jobPage.totalPages,
              total: jobPage.total,
              onPrevious:
                  jobPage.hasPrevious ? () => setState(() => _page -= 1) : null,
              onNext: jobPage.hasNext ? () => setState(() => _page += 1) : null,
            );
          }
          final job = jobPage.items[index - 1];
          return _JobHistoryTile(
            job: job,
            onTap: () => context.push('/app/jobs/${job.id}'),
          );
        },
      ),
    );
  }
}

class _JobHistoryTile extends StatelessWidget {
  const _JobHistoryTile({required this.job, required this.onTap});

  final IndexJob job;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(context, job.status);
    final timestamp = job.updatedAt ?? job.createdAt;
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(8),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(_statusIcon(job.status), color: color),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _jobTypeLabel(job.jobType),
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    if (job.retryOfJobId != null) ...[
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          Icon(
                            Icons.restart_alt,
                            size: 16,
                            color:
                                Theme.of(context).colorScheme.onSurfaceVariant,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            '重试任务',
                            style: Theme.of(context).textTheme.bodySmall,
                          ),
                        ],
                      ),
                    ],
                    const SizedBox(height: 4),
                    if (job.message != null && job.message!.isNotEmpty)
                      Text(
                        job.message!,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    if (job.errorMessage != null &&
                        job.errorMessage!.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      Text(
                        job.errorMessage!,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                            color: Theme.of(context).colorScheme.error),
                      ),
                    ],
                    if (timestamp != null) ...[
                      const SizedBox(height: 6),
                      Text(
                        _formatTimestamp(timestamp),
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                    ],
                    if (!job.isFinished) ...[
                      const SizedBox(height: 8),
                      LinearProgressIndicator(
                        value: job.progress == 0
                            ? null
                            : job.progress.clamp(0, 100) / 100,
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 12),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    _statusLabel(job.status),
                    style: TextStyle(color: color, fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 4),
                  Text('${job.progress.clamp(0, 100)}%'),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _JobPaginationBar extends StatelessWidget {
  const _JobPaginationBar({
    required this.page,
    required this.totalPages,
    required this.total,
    required this.onPrevious,
    required this.onNext,
  });

  final int page;
  final int totalPages;
  final int total;
  final VoidCallback? onPrevious;
  final VoidCallback? onNext;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        IconButton(
          onPressed: onPrevious,
          icon: const Icon(Icons.chevron_left),
          tooltip: '上一页',
        ),
        Expanded(
          child: Text(
            '第 $page / $totalPages 页，共 $total 条',
            textAlign: TextAlign.center,
          ),
        ),
        IconButton(
          onPressed: onNext,
          icon: const Icon(Icons.chevron_right),
          tooltip: '下一页',
        ),
      ],
    );
  }
}

String _jobTypeLabel(String jobType) {
  return switch (jobType) {
    'index_document' => '资料解析与索引',
    'rebuild_embeddings' => '个人资料索引重建',
    'rebuild_all_embeddings' => '全部资料索引重建',
    _ => jobType,
  };
}

String _statusLabel(String status) {
  return switch (status) {
    'pending' => '等待处理',
    'running' => '处理中',
    'cancel_requested' => '正在取消',
    'cancelled' => '已取消',
    'success' => '已完成',
    'failed' => '失败',
    _ => status,
  };
}

IconData _statusIcon(String status) {
  return switch (status) {
    'pending' => Icons.schedule_outlined,
    'running' => Icons.sync,
    'cancel_requested' => Icons.pending_outlined,
    'cancelled' => Icons.cancel_outlined,
    'success' => Icons.check_circle_outline,
    'failed' => Icons.error_outline,
    _ => Icons.task_outlined,
  };
}

Color _statusColor(BuildContext context, String status) {
  return switch (status) {
    'success' => Colors.green.shade700,
    'failed' => Theme.of(context).colorScheme.error,
    'running' => Theme.of(context).colorScheme.primary,
    'cancel_requested' => Theme.of(context).colorScheme.tertiary,
    'cancelled' => Theme.of(context).colorScheme.onSurfaceVariant,
    _ => Theme.of(context).colorScheme.onSurfaceVariant,
  };
}

String _formatTimestamp(DateTime value) {
  final local = value.toLocal();
  String two(int number) => number.toString().padLeft(2, '0');
  return '${local.year}-${two(local.month)}-${two(local.day)} '
      '${two(local.hour)}:${two(local.minute)}';
}
