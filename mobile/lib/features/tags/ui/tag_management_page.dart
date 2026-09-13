import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/user_error_message.dart';
import '../../../core/widgets/async_state_view.dart';
import '../../documents/providers/documents_provider.dart';
import '../models/tag.dart';
import '../providers/tags_provider.dart';

class TagManagementPage extends ConsumerStatefulWidget {
  const TagManagementPage({super.key});

  @override
  ConsumerState<TagManagementPage> createState() => _TagManagementPageState();
}

class _TagManagementPageState extends ConsumerState<TagManagementPage> {
  Timer? _debounce;
  String? _keyword;
  int _page = 1;

  TagsPageQuery get _query => (keyword: _keyword, page: _page);

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final tags = ref.watch(tagsPageProvider(_query));

    return Scaffold(
      appBar: AppBar(title: const Text('标签管理')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
            child: TextField(
              decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                hintText: '搜索标签',
              ),
              onChanged: _search,
            ),
          ),
          Expanded(
            child: tags.when(
              data: (value) {
                if (value.items.isEmpty) {
                  return EmptyView(
                    title: _keyword == null ? '还没有标签' : '没有匹配的标签',
                  );
                }
                return RefreshIndicator(
                  onRefresh: () => ref.refresh(
                    tagsPageProvider(_query).future,
                  ),
                  child: ListView.separated(
                    padding: const EdgeInsets.all(16),
                    itemBuilder: (context, index) => _TagTile(
                      tag: value.items[index],
                      onMutated: _reload,
                    ),
                    separatorBuilder: (_, _) => const SizedBox(height: 8),
                    itemCount: value.items.length,
                  ),
                );
              },
              error: (error, _) => ErrorStateView(
                message: userFacingErrorMessage(
                  error,
                  fallback: '暂时无法加载标签',
                ),
                onRetry: _reload,
              ),
              loading: () => const LoadingView(),
            ),
          ),
          tags.maybeWhen(
            data: (value) => SafeArea(
              top: false,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    IconButton(
                      onPressed: value.hasPrevious ? _previousPage : null,
                      icon: const Icon(Icons.chevron_left),
                      tooltip: '上一页',
                    ),
                    SizedBox(
                      width: 96,
                      child: Text(
                        '${value.page}/${value.totalPages}',
                        textAlign: TextAlign.center,
                      ),
                    ),
                    IconButton(
                      onPressed: value.hasNext ? _nextPage : null,
                      icon: const Icon(Icons.chevron_right),
                      tooltip: '下一页',
                    ),
                  ],
                ),
              ),
            ),
            orElse: () => const SizedBox.shrink(),
          ),
        ],
      ),
    );
  }

  void _search(String value) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      if (!mounted) {
        return;
      }
      final keyword = value.trim();
      setState(() {
        _keyword = keyword.isEmpty ? null : keyword;
        _page = 1;
      });
    });
  }

  void _reload() => ref.invalidate(tagsPageProvider(_query));

  void _previousPage() => setState(() => _page -= 1);

  void _nextPage() => setState(() => _page += 1);
}

class _TagTile extends ConsumerWidget {
  const _TagTile({required this.tag, required this.onMutated});

  final KnowledgeTag tag;
  final VoidCallback onMutated;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Card(
      child: ListTile(
        leading: const Icon(Icons.label_outline),
        title: Text(tag.name),
        trailing: Wrap(
          spacing: 4,
          children: [
            IconButton(
              onPressed: () => _rename(context, ref),
              icon: const Icon(Icons.edit_outlined),
              tooltip: '重命名',
            ),
            IconButton(
              onPressed: () => _delete(context, ref),
              icon: const Icon(Icons.delete_outline),
              tooltip: '删除',
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _rename(BuildContext context, WidgetRef ref) async {
    final controller = TextEditingController(text: tag.name);
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('重命名标签'),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(labelText: '标签名称'),
          autofocus: true,
          onSubmitted: (value) => Navigator.of(context).pop(value.trim()),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(controller.text.trim()),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    controller.dispose();

    if (name == null || name.isEmpty || name == tag.name) {
      return;
    }
    try {
      await ref.read(tagsApiProvider).updateTag(tag.id, name: name);
      _invalidateKnowledgeProviders(ref);
      onMutated();
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('标签已更新')),
        );
      }
    } catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              userFacingErrorMessage(
                error,
                fallback: '重命名标签失败，请稍后重试',
              ),
            ),
          ),
        );
      }
    }
  }

  Future<void> _delete(BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除标签'),
        content: Text('删除后，资料会移除“${tag.name}”标签，但资料本身不会被删除。'),
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
    try {
      await ref.read(tagsApiProvider).deleteTag(tag.id);
      _invalidateKnowledgeProviders(ref);
      onMutated();
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('标签已删除')),
        );
      }
    } catch (error) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              userFacingErrorMessage(
                error,
                fallback: '删除标签失败，请稍后重试',
              ),
            ),
          ),
        );
      }
    }
  }

  void _invalidateKnowledgeProviders(WidgetRef ref) {
    ref.invalidate(tagsProvider);
    ref.invalidate(tagsPageProvider);
    ref.invalidate(documentsProvider);
    ref.invalidate(documentsPageProvider);
    ref.invalidate(selectableDocumentsProvider);
  }
}
