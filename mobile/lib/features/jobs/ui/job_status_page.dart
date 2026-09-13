import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/user_error_message.dart';
import '../../../core/widgets/async_state_view.dart';
import '../../documents/providers/documents_provider.dart';
import '../models/job.dart';
import '../providers/jobs_provider.dart';

class JobStatusPage extends ConsumerStatefulWidget {
  const JobStatusPage({
    required this.jobId,
    this.documentId,
    super.key,
  });

  final String jobId;
  final String? documentId;

  @override
  ConsumerState<JobStatusPage> createState() => _JobStatusPageState();
}

class _JobStatusPageState extends ConsumerState<JobStatusPage> {
  Timer? _timer;
  bool _actionBusy = false;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) {
      final value = ref.read(jobProvider(widget.jobId));
      if (value.value?.isFinished == true) {
        _timer?.cancel();
      } else {
        ref.invalidate(jobProvider(widget.jobId));
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final job = ref.watch(jobProvider(widget.jobId));

    return Scaffold(
      appBar: AppBar(title: const Text('处理进度')),
      body: job.when(
        data: (item) => _JobStatusContent(
          job: item,
          documentId: widget.documentId ?? item.documentId,
          onRefresh: () => ref.invalidate(jobProvider(widget.jobId)),
          actionBusy: _actionBusy,
          onCancel: item.canCancel ? () => _cancelJob(item) : null,
          onRetry: item.canRetry ? () => _retryJob(item) : null,
          onOpenDocuments: () {
            ref.invalidate(documentsProvider);
            ref.invalidate(documentsPageProvider);
            context.go('/app/documents');
          },
          onOpenDocument: (documentId) {
            ref.invalidate(documentsProvider);
            ref.invalidate(documentsPageProvider);
            context.go('/app/documents/$documentId');
          },
        ),
        error: (error, _) => ErrorStateView(
          message: userFacingErrorMessage(
            error,
            fallback: '暂时无法加载任务状态',
          ),
          onRetry: () => ref.invalidate(jobProvider(widget.jobId)),
        ),
        loading: () => const LoadingView(),
      ),
    );
  }

  Future<void> _cancelJob(IndexJob job) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('取消任务'),
        content: const Text('确定停止这个任务吗？当前步骤完成后任务会安全退出。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('继续处理'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('取消任务'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) {
      return;
    }
    setState(() => _actionBusy = true);
    try {
      await ref.read(jobsApiProvider).cancelJob(job.id);
      if (!mounted) {
        return;
      }
      ref.invalidate(jobProvider(job.id));
      ref.invalidate(jobsPageProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('已提交取消请求')),
      );
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              userFacingErrorMessage(
                error,
                fallback: '取消任务失败，请稍后重试',
              ),
            ),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _actionBusy = false);
      }
    }
  }

  Future<void> _retryJob(IndexJob job) async {
    setState(() => _actionBusy = true);
    try {
      final retry = await ref.read(jobsApiProvider).retryJob(job.id);
      if (!mounted) {
        return;
      }
      ref.invalidate(jobsPageProvider);
      final documentQuery = retry.documentId == null
          ? ''
          : '?documentId=${Uri.encodeQueryComponent(retry.documentId!)}';
      context.replace('/app/jobs/${retry.id}$documentQuery');
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              userFacingErrorMessage(
                error,
                fallback: '重新执行任务失败，请稍后重试',
              ),
            ),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _actionBusy = false);
      }
    }
  }
}

class _JobStatusContent extends StatelessWidget {
  const _JobStatusContent({
    required this.job,
    required this.documentId,
    required this.onRefresh,
    required this.actionBusy,
    required this.onCancel,
    required this.onRetry,
    required this.onOpenDocuments,
    required this.onOpenDocument,
  });

  final IndexJob job;
  final String? documentId;
  final VoidCallback onRefresh;
  final bool actionBusy;
  final VoidCallback? onCancel;
  final VoidCallback? onRetry;
  final VoidCallback onOpenDocuments;
  final ValueChanged<String> onOpenDocument;

  @override
  Widget build(BuildContext context) {
    final progress = (job.progress.clamp(0, 100)) / 100;
    final documentReady = job.status == 'success' && documentId != null;
    final isRebuildJob = job.jobType == 'rebuild_embeddings' ||
        job.jobType == 'rebuild_all_embeddings';
    final rebuildReady = isRebuildJob && job.status == 'success';

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        if (isRebuildJob) ...[
          Text(
            job.jobType == 'rebuild_all_embeddings' ? '全部资料索引重建' : '资料索引重建',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
        ],
        if (job.retryOfJobId != null) ...[
          Row(
            children: [
              Icon(
                Icons.restart_alt,
                size: 18,
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
              const SizedBox(width: 6),
              Text(
                '由历史任务重新执行',
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ],
          ),
          const SizedBox(height: 12),
        ],
        Text(_statusText(job.status, isRebuildJob),
            style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: 16),
        LinearProgressIndicator(
            value: progress == 0 && !job.isFinished ? null : progress),
        const SizedBox(height: 8),
        Text('${job.progress.clamp(0, 100)}%'),
        const SizedBox(height: 16),
        if (job.message != null && job.message!.isNotEmpty) Text(job.message!),
        if (job.errorMessage != null && job.errorMessage!.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text(job.errorMessage!,
              style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ],
        const SizedBox(height: 24),
        FilledButton.icon(
          onPressed: documentReady
              ? () => onOpenDocument(documentId!)
              : rebuildReady
                  ? onOpenDocuments
                  : null,
          icon: Icon(
            isRebuildJob ? Icons.folder_outlined : Icons.description_outlined,
          ),
          label: Text(isRebuildJob ? '重建完成后返回资料库' : '打开资料'),
        ),
        const SizedBox(height: 8),
        if (onRetry != null) ...[
          FilledButton.tonalIcon(
            onPressed: actionBusy ? null : onRetry,
            icon: const Icon(Icons.restart_alt),
            label: const Text('重新执行'),
          ),
          const SizedBox(height: 8),
        ],
        if (onCancel != null) ...[
          OutlinedButton.icon(
            onPressed: actionBusy ? null : onCancel,
            icon: const Icon(Icons.cancel_outlined),
            label: const Text('取消任务'),
          ),
          const SizedBox(height: 8),
        ],
        OutlinedButton.icon(
          onPressed: onRefresh,
          icon: const Icon(Icons.refresh),
          label: const Text('刷新'),
        ),
      ],
    );
  }

  String _statusText(String status, bool isRebuildJob) {
    return switch (status) {
      'pending' => '等待处理',
      'running' => isRebuildJob ? '正在重建索引' : '正在解析和索引',
      'cancel_requested' => '正在安全取消',
      'cancelled' => '任务已取消',
      'success' => '处理完成',
      'failed' => '处理失败',
      _ => status,
    };
  }
}
