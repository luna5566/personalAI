import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/user_error_message.dart';
import '../../../core/widgets/async_state_view.dart';
import '../../../core/widgets/markdown_text.dart';
import '../data/chat_api.dart';
import '../models/chat.dart';
import '../providers/chat_provider.dart';

class ConversationDetailPage extends ConsumerStatefulWidget {
  const ConversationDetailPage({required this.conversationId, super.key});

  final String conversationId;

  @override
  ConsumerState<ConversationDetailPage> createState() =>
      _ConversationDetailPageState();
}

class _ConversationDetailPageState
    extends ConsumerState<ConversationDetailPage> {
  MessageHistoryPage? _sourcePage;
  List<ChatHistoryMessage> _items = const [];
  String? _nextCursor;
  bool _loadingOlder = false;
  bool _continuing = false;
  bool _newerMessagesHidden = false;
  String? _olderError;

  @override
  Widget build(BuildContext context) {
    final messages =
        ref.watch(conversationMessagesProvider(widget.conversationId));
    final conversation =
        ref.watch(conversationDetailProvider(widget.conversationId));
    final sourcePage = messages.value;
    if (sourcePage != null && !identical(sourcePage, _sourcePage)) {
      _replaceWithRecentPage(sourcePage);
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('会话详情'),
        actions: [
          IconButton(
            onPressed: _items.isNotEmpty &&
                    conversation.value != null &&
                    !_continuing
                ? () => _continueChat(
                      conversation.value!,
                    )
                : null,
            icon: _continuing
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.forum_outlined),
            tooltip: '继续提问',
          ),
        ],
      ),
      body: messages.when(
        data: (_) {
          if (_items.isEmpty) {
            return const EmptyView(title: '这次会话还没有消息');
          }
          final showHistoryControls = _nextCursor != null ||
              _loadingOlder ||
              _olderError != null ||
              _newerMessagesHidden;
          final leadingItems = showHistoryControls ? 1 : 0;
          return RefreshIndicator(
            onRefresh: _refreshRecent,
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemBuilder: (context, index) {
                if (showHistoryControls && index == 0) {
                  return _OlderMessagesControl(
                    canLoadOlder: _nextCursor != null,
                    loading: _loadingOlder,
                    error: _olderError,
                    onPressed: _loadOlder,
                    showReturnRecent: _newerMessagesHidden,
                    onReturnRecent: _refreshRecent,
                  );
                }
                final messageIndex = index - leadingItems;
                return _HistoryMessageBubble(
                  message: _items[messageIndex].toChatMessage(),
                );
              },
              separatorBuilder: (_, _) => const SizedBox(height: 12),
              itemCount: leadingItems + _items.length,
            ),
          );
        },
        error: (error, _) => ErrorStateView(
          message: userFacingErrorMessage(
            error,
            fallback: '暂时无法加载会话消息',
          ),
          onRetry: () => ref.invalidate(
            conversationMessagesProvider(widget.conversationId),
          ),
        ),
        loading: () => const LoadingView(),
      ),
    );
  }

  void _replaceWithRecentPage(MessageHistoryPage page) {
    _sourcePage = page;
    _items = page.items;
    _nextCursor = page.nextCursor;
    _loadingOlder = false;
    _newerMessagesHidden = false;
    _olderError = null;
  }

  Future<void> _refreshRecent() async {
    final page = await ref.refresh(
      conversationMessagesProvider(widget.conversationId).future,
    );
    if (!mounted) {
      return;
    }
    setState(() => _replaceWithRecentPage(page));
  }

  Future<void> _loadOlder() async {
    final cursor = _nextCursor;
    if (cursor == null || _loadingOlder) {
      return;
    }
    setState(() {
      _loadingOlder = true;
      _olderError = null;
    });
    try {
      final page = await ref.read(chatApiProvider).listMessagePage(
            widget.conversationId,
            cursor: cursor,
          );
      if (!mounted) {
        return;
      }
      final existingIds = _items.map((item) => item.id).toSet();
      final older =
          page.items.where((item) => existingIds.add(item.id)).toList();
      final combined = [...older, ..._items];
      var newerMessagesHidden = _newerMessagesHidden;
      if (combined.length > chatMessageWindowLimit) {
        combined.removeRange(chatMessageWindowLimit, combined.length);
        newerMessagesHidden = true;
      }
      setState(() {
        _items = combined;
        _nextCursor = page.nextCursor;
        _loadingOlder = false;
        _newerMessagesHidden = newerMessagesHidden;
      });
    } catch (error) {
      if (!mounted) {
        return;
      }
      setState(() {
        _loadingOlder = false;
        _olderError = userFacingErrorMessage(
          error,
          fallback: '较早消息加载失败，请重试',
        );
      });
    }
  }

  Future<void> _continueChat(
    ConversationSummary conversation,
  ) async {
    var messages = _items;
    var olderMessagesHidden = _nextCursor != null || _newerMessagesHidden;
    if (_newerMessagesHidden) {
      setState(() => _continuing = true);
      try {
        final recent = await ref
            .read(chatApiProvider)
            .listMessagePage(widget.conversationId);
        messages = recent.items;
        olderMessagesHidden = recent.nextCursor != null;
      } catch (error) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                userFacingErrorMessage(
                  error,
                  fallback: '暂时无法恢复最近消息',
                ),
              ),
            ),
          );
        }
        return;
      } finally {
        if (mounted) {
          setState(() => _continuing = false);
        }
      }
    }
    if (!mounted) {
      return;
    }
    ref.read(chatControllerProvider.notifier).loadConversation(
          conversation: conversation,
          messages: messages,
          olderMessagesHidden: olderMessagesHidden,
        );
    context.go('/app/chat');
  }
}

class _OlderMessagesControl extends StatelessWidget {
  const _OlderMessagesControl({
    required this.canLoadOlder,
    required this.loading,
    required this.error,
    required this.onPressed,
    required this.showReturnRecent,
    required this.onReturnRecent,
  });

  final bool canLoadOlder;
  final bool loading;
  final String? error;
  final VoidCallback onPressed;
  final bool showReturnRecent;
  final VoidCallback onReturnRecent;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        children: [
          if (error != null) ...[
            Text(
              error!,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.error,
                  ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
          ],
          if (canLoadOlder || loading)
            OutlinedButton.icon(
              onPressed: loading ? null : onPressed,
              icon: loading
                  ? const SizedBox.square(
                      dimension: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.history, size: 18),
              label: Text(loading ? '正在加载' : '加载更早消息'),
            ),
          if (showReturnRecent)
            TextButton.icon(
              onPressed: onReturnRecent,
              icon: const Icon(Icons.refresh, size: 18),
              label: const Text('返回最近消息'),
            ),
        ],
      ),
    );
  }
}

class _HistoryMessageBubble extends StatelessWidget {
  const _HistoryMessageBubble({required this.message});

  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == ChatMessageRole.user;
    final colorScheme = Theme.of(context).colorScheme;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: isUser ? colorScheme.primary : Colors.white,
            borderRadius: BorderRadius.circular(8),
            border:
                isUser ? null : Border.all(color: colorScheme.outlineVariant),
          ),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: DefaultTextStyle(
              style: Theme.of(context).textTheme.bodyMedium!.copyWith(
                    color: isUser ? colorScheme.onPrimary : null,
                  ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  isUser
                      ? Text(message.text)
                      : MarkdownText(data: message.text),
                  if (message.contentTruncated) ...[
                    const SizedBox(height: 8),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(Icons.info_outline, size: 16),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            '这条历史消息过长，仅显示前 32000 个字符',
                            style: Theme.of(context).textTheme.labelMedium,
                          ),
                        ),
                      ],
                    ),
                  ],
                  if (message.citations.isNotEmpty) ...[
                    const SizedBox(height: 12),
                    Text(
                      '引用来源',
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                    const SizedBox(height: 8),
                    for (final citation in message.citations)
                      _HistoryCitation(citation: citation),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _HistoryCitation extends StatelessWidget {
  const _HistoryCitation({required this.citation});

  final Citation citation;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () => context.push(
        Uri(
          path: '/app/documents/${citation.documentId}',
          queryParameters: {
            'highlight': citation.text,
            if (citation.startOffset != null)
              'highlightStart': citation.startOffset.toString(),
            if (citation.endOffset != null)
              'highlightEnd': citation.endOffset.toString(),
          },
        ).toString(),
      ),
      borderRadius: BorderRadius.circular(8),
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.only(top: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          border:
              Border.all(color: Theme.of(context).colorScheme.outlineVariant),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    citation.documentTitle,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    citation.metadataLabel,
                    style: Theme.of(context).textTheme.labelSmall?.copyWith(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                  ),
                  const SizedBox(height: 4),
                  Text(citation.text),
                ],
              ),
            ),
            const SizedBox(width: 8),
            const Icon(Icons.chevron_right, size: 18),
          ],
        ),
      ),
    );
  }
}
