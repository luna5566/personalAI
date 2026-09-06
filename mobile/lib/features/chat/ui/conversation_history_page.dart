import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/user_error_message.dart';
import '../../../core/widgets/async_state_view.dart';
import '../models/chat.dart';
import '../providers/chat_provider.dart';

class ConversationHistoryPage extends ConsumerStatefulWidget {
  const ConversationHistoryPage({super.key});

  @override
  ConsumerState<ConversationHistoryPage> createState() =>
      _ConversationHistoryPageState();
}

class _ConversationHistoryPageState
    extends ConsumerState<ConversationHistoryPage> {
  final _searchController = TextEditingController();
  String _keyword = '';
  bool _busy = false;
  int _page = 1;
  Timer? _searchDebounce;

  ConversationPageQuery get _pageQuery => (
        keyword: _keyword.isEmpty ? null : _keyword,
        page: _page,
      );

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final conversations =
        ref.watch(filteredConversationPageProvider(_pageQuery));

    return Scaffold(
      appBar: AppBar(title: const Text('会话历史')),
      body: conversations.when(
        data: (conversationPage) {
          final items = conversationPage.items;
          if (items.isEmpty && _keyword.isEmpty && _page == 1) {
            return const EmptyView(title: '还没有会话');
          }
          return RefreshIndicator(
            onRefresh: () => ref.refresh(
              filteredConversationPageProvider(_pageQuery).future,
            ),
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemBuilder: (context, index) {
                if (index == 0) {
                  return _SearchField(
                    controller: _searchController,
                    onChanged: _onSearchChanged,
                    onClear: _clearSearch,
                  );
                }
                if (items.isEmpty) {
                  return const Padding(
                    padding: EdgeInsets.only(top: 80),
                    child: Center(child: Text('没有找到匹配的会话')),
                  );
                }
                if (index == items.length + 1) {
                  return _ConversationPaginationBar(
                    page: conversationPage.page,
                    totalPages: conversationPage.totalPages,
                    total: conversationPage.total,
                    onPrevious: conversationPage.hasPrevious
                        ? () => setState(() => _page -= 1)
                        : null,
                    onNext: conversationPage.hasNext
                        ? () => setState(() => _page += 1)
                        : null,
                  );
                }
                final conversation = items[index - 1];
                return _ConversationTile(
                  conversation: conversation,
                  busy: _busy,
                  onRename: () => _renameConversation(conversation),
                  onDelete: () => _deleteConversation(conversation),
                );
              },
              separatorBuilder: (_, __) => const SizedBox(height: 12),
              itemCount: items.isEmpty ? 2 : items.length + 2,
            ),
          );
        },
        error: (error, _) => ErrorStateView(
          message: userFacingErrorMessage(
            error,
            fallback: '暂时无法加载会话历史',
          ),
          onRetry: () =>
              ref.invalidate(filteredConversationPageProvider(_pageQuery)),
        ),
        loading: () => const LoadingView(),
      ),
    );
  }

  void _onSearchChanged(String value) {
    _searchDebounce?.cancel();
    _searchDebounce = Timer(const Duration(milliseconds: 350), () {
      if (!mounted) {
        return;
      }
      final keyword = value.trim();
      if (keyword == _keyword) {
        return;
      }
      setState(() {
        _keyword = keyword;
        _page = 1;
      });
    });
  }

  void _clearSearch() {
    _searchDebounce?.cancel();
    _searchController.clear();
    setState(() {
      _keyword = '';
      _page = 1;
    });
  }

  Future<void> _renameConversation(ConversationSummary conversation) async {
    final title = await showDialog<String>(
      context: context,
      builder: (context) => _RenameConversationDialog(
        initialTitle: conversation.title,
      ),
    );
    if (title == null) {
      return;
    }
    if (!mounted) {
      return;
    }
    final trimmed = title.trim();
    if (trimmed.isEmpty || trimmed == conversation.title) {
      return;
    }

    setState(() => _busy = true);
    try {
      await ref.read(chatApiProvider).updateConversationTitle(
            conversation.id,
            title: trimmed,
          );
      if (!mounted) {
        return;
      }
      ref.invalidate(conversationHistoryProvider);
      ref.invalidate(conversationPageProvider);
      ref.invalidate(filteredConversationPageProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('会话已重命名')),
      );
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            userFacingErrorMessage(
              error,
              fallback: '重命名会话失败，请稍后重试',
            ),
          ),
        ),
      );
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  Future<void> _deleteConversation(ConversationSummary conversation) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除会话'),
        content: Text('确定删除“${conversation.title}”吗？删除后无法恢复。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) {
      return;
    }
    if (!mounted) {
      return;
    }
    final shouldMoveToPreviousPage = _page > 1 &&
        ref
                .read(filteredConversationPageProvider(_pageQuery))
                .valueOrNull
                ?.items
                .length ==
            1;

    setState(() => _busy = true);
    try {
      await ref.read(chatApiProvider).deleteConversation(conversation.id);
      if (!mounted) {
        return;
      }
      ref.invalidate(conversationHistoryProvider);
      ref.invalidate(conversationPageProvider);
      ref.invalidate(filteredConversationPageProvider);
      ref.invalidate(conversationMessagesProvider(conversation.id));
      if (shouldMoveToPreviousPage) {
        setState(() => _page -= 1);
      }
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('会话已删除')),
      );
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            userFacingErrorMessage(
              error,
              fallback: '删除会话失败，请稍后重试',
            ),
          ),
        ),
      );
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }
}

class _ConversationPaginationBar extends StatelessWidget {
  const _ConversationPaginationBar({
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

class _SearchField extends StatelessWidget {
  const _SearchField({
    required this.controller,
    required this.onChanged,
    required this.onClear,
  });

  final TextEditingController controller;
  final ValueChanged<String> onChanged;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      textInputAction: TextInputAction.search,
      decoration: InputDecoration(
        hintText: '搜索会话标题',
        prefixIcon: const Icon(Icons.search),
        suffixIcon: ValueListenableBuilder<TextEditingValue>(
          valueListenable: controller,
          builder: (context, value, child) {
            if (value.text.isEmpty) {
              return const SizedBox.shrink();
            }
            return IconButton(
              onPressed: onClear,
              icon: const Icon(Icons.close),
              tooltip: '清空搜索',
            );
          },
        ),
      ),
      onChanged: onChanged,
    );
  }
}

class _ConversationTile extends StatelessWidget {
  const _ConversationTile({
    required this.conversation,
    required this.busy,
    required this.onRename,
    required this.onDelete,
  });

  final ConversationSummary conversation;
  final bool busy;
  final VoidCallback onRename;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        title: Text(conversation.title),
        subtitle: Text(_formatDateTime(conversation.updatedAt)),
        trailing: SizedBox(
          width: 88,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              PopupMenuButton<_ConversationAction>(
                enabled: !busy,
                icon: const Icon(Icons.more_vert),
                tooltip: '更多操作',
                onSelected: (action) {
                  switch (action) {
                    case _ConversationAction.rename:
                      onRename();
                    case _ConversationAction.delete:
                      onDelete();
                  }
                },
                itemBuilder: (context) => const [
                  PopupMenuItem(
                    value: _ConversationAction.rename,
                    child: Text('重命名'),
                  ),
                  PopupMenuItem(
                    value: _ConversationAction.delete,
                    child: Text('删除'),
                  ),
                ],
              ),
              const Icon(Icons.chevron_right),
            ],
          ),
        ),
        onTap: () => context.push('/app/chat/history/${conversation.id}'),
      ),
    );
  }

  String _formatDateTime(DateTime value) {
    final local = value.toLocal();
    return '${local.year}-${_two(local.month)}-${_two(local.day)} '
        '${_two(local.hour)}:${_two(local.minute)}';
  }

  String _two(int value) => value.toString().padLeft(2, '0');
}

enum _ConversationAction { rename, delete }

class _RenameConversationDialog extends StatefulWidget {
  const _RenameConversationDialog({required this.initialTitle});

  final String initialTitle;

  @override
  State<_RenameConversationDialog> createState() =>
      _RenameConversationDialogState();
}

class _RenameConversationDialogState extends State<_RenameConversationDialog> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialTitle);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('重命名会话'),
      content: TextField(
        controller: _controller,
        decoration: const InputDecoration(labelText: '会话标题'),
        maxLength: 255,
        textInputAction: TextInputAction.done,
        onSubmitted: (_) => _confirm(),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: _confirm,
          child: const Text('保存'),
        ),
      ],
    );
  }

  void _confirm() {
    Navigator.of(context).pop(_controller.text.trim());
  }
}
