import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/user_error_message.dart';
import '../../chat/providers/chat_provider.dart';
import '../../documents/providers/documents_provider.dart';
import '../../documents/widgets/document_card.dart';
import '../../documents/widgets/document_upload_flow.dart';

const _recentDocumentsQuery = (
  tag: null,
  keyword: null,
  sourceType: null,
);

class HomePage extends ConsumerStatefulWidget {
  const HomePage({super.key});

  @override
  ConsumerState<HomePage> createState() => _HomePageState();
}

class _HomePageState extends ConsumerState<HomePage> {
  final _questionController = TextEditingController();
  bool _uploading = false;

  @override
  void dispose() {
    _questionController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final documents = ref.watch(documentsProvider(_recentDocumentsQuery));
    final conversations = ref.watch(conversationHistoryProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('首页')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('今天想整理什么？', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 16),
          TextField(
            controller: _questionController,
            textInputAction: TextInputAction.send,
            decoration: InputDecoration(
              hintText: '直接问我的资料',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: IconButton(
                onPressed: _submitQuestion,
                icon: const Icon(Icons.send),
                tooltip: '发送',
              ),
            ),
            onSubmitted: (_) => _submitQuestion(),
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              FilledButton.icon(
                onPressed: () => context.push('/app/documents/new-note'),
                icon: const Icon(Icons.edit_outlined),
                label: const Text('记一条'),
              ),
              OutlinedButton.icon(
                onPressed: _uploading ? null : _uploadDocument,
                icon: _uploading
                    ? const SizedBox.square(
                        dimension: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.upload_file_outlined),
                label: const Text('上传资料'),
              ),
              OutlinedButton.icon(
                onPressed: () => context.go('/app/chat'),
                icon: const Icon(Icons.chat_bubble_outline),
                label: const Text('提问'),
              ),
              OutlinedButton.icon(
                onPressed: () => context.go('/app/organize'),
                icon: const Icon(Icons.auto_awesome_outlined),
                label: const Text('一键整理'),
              ),
            ],
          ),
          const SizedBox(height: 24),
          Text('最近资料', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 12),
          documents.when(
            data: (items) {
              if (items.isEmpty) {
                return const Text('还没有资料');
              }
              return Column(
                children: [
                  for (final item in items.take(3)) ...[
                    DocumentCard(document: item),
                    const SizedBox(height: 12),
                  ],
                ],
              );
            },
            error: (error, _) => _HomeSectionError(
              message: userFacingErrorMessage(
                error,
                fallback: '暂时无法加载最近资料',
              ),
              retryTooltip: '重新加载最近资料',
              onRetry: () => ref.invalidate(
                documentsProvider(_recentDocumentsQuery),
              ),
            ),
            loading: () => const Center(child: CircularProgressIndicator()),
          ),
          const SizedBox(height: 12),
          Text('最近问答', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 12),
          conversations.when(
            data: (items) {
              if (items.isEmpty) {
                return const Text('还没有问答记录');
              }
              return Column(
                children: [
                  for (final item in items.take(3)) ...[
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.forum_outlined),
                      title: Text(item.title),
                      subtitle: Text(_formatConversationTime(item.updatedAt)),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => context.push('/app/chat/history/${item.id}'),
                    ),
                    const Divider(height: 1),
                  ],
                ],
              );
            },
            error: (error, _) => _HomeSectionError(
              message: userFacingErrorMessage(
                error,
                fallback: '暂时无法加载最近问答',
              ),
              retryTooltip: '重新加载最近问答',
              onRetry: () => ref.invalidate(conversationHistoryProvider),
            ),
            loading: () => const Center(child: CircularProgressIndicator()),
          ),
        ],
      ),
    );
  }

  void _submitQuestion() {
    final question = _questionController.text.trim();
    if (question.isEmpty) {
      return;
    }
    ref.read(chatControllerProvider.notifier).clear();
    ref.read(chatControllerProvider.notifier).ask(question);
    _questionController.clear();
    context.go('/app/chat');
  }

  Future<void> _uploadDocument() async {
    setState(() => _uploading = true);
    try {
      await pickAndUploadDocument(context, ref);
    } finally {
      if (mounted) {
        setState(() => _uploading = false);
      }
    }
  }

  String _formatConversationTime(DateTime value) {
    final local = value.toLocal();
    return '${local.month.toString().padLeft(2, '0')}-'
        '${local.day.toString().padLeft(2, '0')} '
        '${local.hour.toString().padLeft(2, '0')}:'
        '${local.minute.toString().padLeft(2, '0')}';
  }
}

class _HomeSectionError extends StatelessWidget {
  const _HomeSectionError({
    required this.message,
    required this.retryTooltip,
    required this.onRetry,
  });

  final String message;
  final String retryTooltip;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: Text(message)),
        SizedBox.square(
          dimension: 48,
          child: IconButton(
            tooltip: retryTooltip,
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
          ),
        ),
      ],
    );
  }
}
