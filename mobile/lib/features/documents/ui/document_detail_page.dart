import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/user_error_message.dart';
import '../../../core/widgets/async_state_view.dart';
import '../models/document.dart';
import '../../chat/providers/chat_provider.dart';
import '../../organize/providers/organize_provider.dart';
import '../../tags/providers/tags_provider.dart';
import '../providers/documents_provider.dart';

class DocumentDetailPage extends ConsumerStatefulWidget {
  const DocumentDetailPage({
    required this.documentId,
    this.highlightText,
    this.highlightStart,
    this.highlightEnd,
    super.key,
  });

  final String documentId;
  final String? highlightText;
  final int? highlightStart;
  final int? highlightEnd;

  @override
  ConsumerState<DocumentDetailPage> createState() => _DocumentDetailPageState();
}

class _DocumentDetailPageState extends ConsumerState<DocumentDetailPage> {
  static const _citationLeadingContextLength = 5000;

  bool _organizing = false;
  bool _savingMeta = false;
  late int _contentOffset;

  DocumentDetailQuery get _detailQuery => (
        id: widget.documentId,
        contentOffset: _contentOffset,
      );

  @override
  void initState() {
    super.initState();
    _contentOffset = _initialContentOffset();
  }

  @override
  void didUpdateWidget(covariant DocumentDetailPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.documentId != widget.documentId ||
        oldWidget.highlightStart != widget.highlightStart) {
      _contentOffset = _initialContentOffset();
    }
  }

  @override
  Widget build(BuildContext context) {
    final document = ref.watch(documentDetailProvider(_detailQuery));

    return Scaffold(
      appBar: AppBar(
        title: const Text('资料详情'),
        actions: [
          IconButton(
            onPressed: document.valueOrNull?.isIndexed == true
                ? () => _askDocument(document.valueOrNull!)
                : null,
            icon: const Icon(Icons.chat_bubble_outline),
            tooltip: '针对这份资料提问',
          ),
          IconButton(
            onPressed: _savingMeta || document.valueOrNull == null
                ? null
                : () => _editDocument(document.valueOrNull!),
            icon: _savingMeta
                ? const SizedBox.square(
                    dimension: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.edit_outlined),
            tooltip: '编辑资料',
          ),
          PopupMenuButton<String>(
            enabled: !_organizing && document.valueOrNull?.isIndexed == true,
            icon: _organizing
                ? const SizedBox.square(
                    dimension: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.auto_awesome_outlined),
            tooltip: '整理',
            onSelected: _organize,
            itemBuilder: (context) => const [
              PopupMenuItem(value: 'summary', child: Text('总结')),
              PopupMenuItem(value: 'outline', child: Text('大纲')),
              PopupMenuItem(value: 'key_points', child: Text('要点')),
              PopupMenuItem(value: 'action_items', child: Text('行动项')),
              PopupMenuItem(value: 'related', child: Text('找相关资料')),
            ],
          ),
          IconButton(
            onPressed: _deleteDocument,
            icon: const Icon(Icons.delete_outline),
            tooltip: '删除资料',
          ),
        ],
      ),
      body: document.when(
        data: (item) => _DocumentDetailContent(
          document: item,
          highlightText: widget.highlightText,
          highlightStart: widget.highlightStart,
          highlightEnd: widget.highlightEnd,
          onContentOffsetChanged: _loadContentWindow,
        ),
        error: (error, _) => ErrorStateView(
          message: userFacingErrorMessage(
            error,
            fallback: '暂时无法加载资料详情',
          ),
          onRetry: () => ref.invalidate(documentDetailProvider(_detailQuery)),
        ),
        loading: () => const LoadingView(),
      ),
    );
  }

  int _initialContentOffset() {
    final highlightStart = widget.highlightStart;
    if (highlightStart == null || highlightStart <= 0) {
      return 0;
    }
    return highlightStart > _citationLeadingContextLength
        ? highlightStart - _citationLeadingContextLength
        : 0;
  }

  void _loadContentWindow(int contentOffset) {
    if (contentOffset == _contentOffset) {
      return;
    }
    setState(() => _contentOffset = contentOffset);
  }

  Future<void> _editDocument(KnowledgeDocument document) async {
    final result = await showDialog<_DocumentEditResult>(
      context: context,
      builder: (context) => _DocumentEditDialog(document: document),
    );
    if (result == null) {
      return;
    }

    setState(() => _savingMeta = true);
    try {
      await ref.read(documentsApiProvider).updateDocument(
            widget.documentId,
            title: result.title,
            tags: result.tags,
          );
      ref.invalidate(documentDetailProvider(_detailQuery));
      ref.invalidate(documentsProvider);
      ref.invalidate(documentsPageProvider);
      ref.invalidate(tagsProvider);
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('资料信息已更新')),
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
              fallback: '更新资料失败，请稍后重试',
            ),
          ),
        ),
      );
    } finally {
      if (mounted) {
        setState(() => _savingMeta = false);
      }
    }
  }

  void _askDocument(KnowledgeDocument document) {
    ref.read(chatControllerProvider.notifier).clear();
    context.go(
      Uri(
        path: '/app/chat',
        queryParameters: {'documentId': document.id},
      ).toString(),
    );
  }

  Future<void> _organize(String mode) async {
    setState(() => _organizing = true);
    try {
      if (mode == 'related') {
        await _showRelatedDocuments();
        return;
      }
      final result = await ref.read(organizeApiProvider).organizeDocument(
            documentId: widget.documentId,
            mode: mode,
          );
      if (!mounted) {
        return;
      }
      final saveAsNote = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('整理结果'),
          content: SingleChildScrollView(child: Text(result.result)),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(context).pop(false),
              child: const Text('关闭'),
            ),
            FilledButton.icon(
              onPressed: () => Navigator.of(context).pop(true),
              icon: const Icon(Icons.save_outlined),
              label: const Text('保存为笔记'),
            ),
          ],
        ),
      );
      if (saveAsNote == true && mounted) {
        await _saveOrganizeResult(
          mode,
          result.result,
          result.sourceDocumentIds,
        );
      }
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            userFacingErrorMessage(
              error,
              fallback: '整理资料失败，请稍后重试',
            ),
          ),
        ),
      );
    } finally {
      if (mounted) {
        setState(() => _organizing = false);
      }
    }
  }

  Future<void> _showRelatedDocuments() async {
    final related = await ref
        .read(documentsApiProvider)
        .getRelatedDocuments(widget.documentId);
    if (!mounted) {
      return;
    }
    final selectedDocumentId = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('相关资料'),
        content: SizedBox(
          width: 520,
          child: related.isEmpty
              ? const Text('暂未找到相关资料')
              : ListView.separated(
                  shrinkWrap: true,
                  itemBuilder: (context, index) {
                    final item = related[index];
                    return ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(item.title),
                      subtitle: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${item.sourceTypeLabel} · '
                            '相关度 ${(item.score.clamp(0, 1) * 100).round()}%',
                          ),
                          const SizedBox(height: 4),
                          Text(
                            item.matchedText,
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ],
                      ),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => Navigator.of(context).pop(item.documentId),
                    );
                  },
                  separatorBuilder: (_, __) => const Divider(height: 1),
                  itemCount: related.length,
                ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('关闭'),
          ),
        ],
      ),
    );
    if (selectedDocumentId != null && mounted) {
      context.push('/app/documents/$selectedDocumentId');
    }
  }

  Future<void> _saveOrganizeResult(
    String mode,
    String content,
    List<String> sourceDocumentIds,
  ) async {
    final source = ref.read(documentDetailProvider(_detailQuery)).valueOrNull;
    final title = '${source?.title ?? '资料整理'} - ${_modeLabel(mode)}';
    try {
      final savedDocumentId = await ref.read(organizeApiProvider).saveResult(
            title: title,
            result: content,
            sourceDocumentIds: sourceDocumentIds,
          );
      ref.invalidate(documentsProvider);
      ref.invalidate(documentsPageProvider);
      ref.invalidate(selectableDocumentsProvider);
      ref.invalidate(documentStatsProvider);
      ref.invalidate(tagsProvider);
      if (mounted) {
        context.push('/app/documents/$savedDocumentId');
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              userFacingErrorMessage(
                error,
                fallback: '保存整理结果失败，请稍后重试',
              ),
            ),
          ),
        );
      }
    }
  }

  String _modeLabel(String mode) {
    return switch (mode) {
      'summary' => '总结',
      'outline' => '大纲',
      'key_points' => '要点',
      'action_items' => '行动项',
      _ => '整理',
    };
  }

  Future<void> _deleteDocument() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除资料'),
        content: const Text('删除后会同时移除相关切片和索引，确定继续吗？'),
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
      await ref.read(documentsApiProvider).deleteDocument(widget.documentId);
      ref.invalidate(documentsProvider);
      ref.invalidate(documentsPageProvider);
      ref.invalidate(documentDetailProvider);
      if (!mounted) {
        return;
      }
      context.go('/app/documents');
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            userFacingErrorMessage(
              error,
              fallback: '删除资料失败，请稍后重试',
            ),
          ),
        ),
      );
    }
  }
}

class _DocumentEditResult {
  const _DocumentEditResult({
    required this.title,
    required this.tags,
  });

  final String title;
  final List<String> tags;
}

class _DocumentEditDialog extends StatefulWidget {
  const _DocumentEditDialog({required this.document});

  final KnowledgeDocument document;

  @override
  State<_DocumentEditDialog> createState() => _DocumentEditDialogState();
}

class _DocumentEditDialogState extends State<_DocumentEditDialog> {
  late final TextEditingController _titleController;
  late final TextEditingController _tagsController;

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(text: widget.document.title);
    _tagsController =
        TextEditingController(text: widget.document.tags.join(', '));
  }

  @override
  void dispose() {
    _titleController.dispose();
    _tagsController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('编辑资料'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _titleController,
              decoration: const InputDecoration(labelText: '标题'),
              textInputAction: TextInputAction.next,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _tagsController,
              decoration: const InputDecoration(labelText: '标签，逗号分隔'),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: _submit,
          child: const Text('保存'),
        ),
      ],
    );
  }

  void _submit() {
    final title = _titleController.text.trim();
    if (title.isEmpty) {
      return;
    }
    final tags = _tagsController.text
        .replaceAll('，', ',')
        .split(',')
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();
    Navigator.of(context).pop(_DocumentEditResult(title: title, tags: tags));
  }
}

class _DocumentDetailContent extends StatefulWidget {
  const _DocumentDetailContent({
    required this.document,
    this.highlightText,
    this.highlightStart,
    this.highlightEnd,
    required this.onContentOffsetChanged,
  });

  final KnowledgeDocument document;
  final String? highlightText;
  final int? highlightStart;
  final int? highlightEnd;
  final ValueChanged<int> onContentOffsetChanged;

  @override
  State<_DocumentDetailContent> createState() => _DocumentDetailContentState();
}

class _DocumentDetailContentState extends State<_DocumentDetailContent> {
  final _scrollController = ScrollController();
  final _highlightKey = GlobalKey();
  bool _didScrollToHighlight = false;

  @override
  void didUpdateWidget(covariant _DocumentDetailContent oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.document.contentOffset != widget.document.contentOffset ||
        oldWidget.highlightStart != widget.highlightStart ||
        oldWidget.highlightEnd != widget.highlightEnd) {
      _didScrollToHighlight = false;
    }
  }

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final content = widget.document.content ?? widget.document.summary;
    final bodyText = content == null || content.isEmpty ? '暂无内容' : content;
    final highlight = _cleanHighlight(widget.highlightText);
    final range = _resolveHighlightRange(bodyText, highlight);
    final contentLength = widget.document.contentLength;
    final contentOffset = widget.document.contentOffset;
    final contentEnd = contentOffset + (widget.document.content?.length ?? 0);
    final hasPrevious = contentOffset > 0;
    final hasNext = widget.document.contentTruncated;
    _scheduleScrollToHighlight(range);

    return ListView(
      controller: _scrollController,
      padding: const EdgeInsets.all(16),
      children: [
        Text(widget.document.title, style: theme.textTheme.headlineSmall),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            Chip(label: Text(widget.document.sourceTypeLabel)),
            Chip(label: Text(widget.document.statusLabel)),
            for (final tag in widget.document.tags) Chip(label: Text(tag)),
          ],
        ),
        if (widget.document.errorMessage != null &&
            widget.document.errorMessage!.isNotEmpty) ...[
          const SizedBox(height: 16),
          _InfoPanel(
            title: '处理失败原因',
            text: widget.document.errorMessage!,
            isError: true,
          ),
        ],
        if (widget.document.summary != null &&
            widget.document.summary!.isNotEmpty) ...[
          const SizedBox(height: 16),
          _InfoPanel(title: '摘要', text: widget.document.summary!),
        ],
        if (highlight != null) ...[
          const SizedBox(height: 16),
          _InfoPanel(
            title: range != null ? '引用片段' : '引用片段（未在原文中精确定位）',
            text: highlight,
          ),
        ],
        const SizedBox(height: 16),
        Text('正文', style: theme.textTheme.titleMedium),
        if (hasPrevious || hasNext) ...[
          const SizedBox(height: 4),
          Row(
            children: [
              Expanded(
                child: Text(
                  contentEnd > contentOffset
                      ? '字符 ${contentOffset + 1}-$contentEnd / $contentLength'
                      : '字符 0 / $contentLength',
                  style: theme.textTheme.bodySmall,
                ),
              ),
              IconButton(
                onPressed: hasPrevious
                    ? () => widget.onContentOffsetChanged(
                          contentOffset > documentDetailContentPageSize
                              ? contentOffset - documentDetailContentPageSize
                              : 0,
                        )
                    : null,
                icon: const Icon(Icons.chevron_left),
                tooltip: '上一段',
              ),
              IconButton(
                onPressed: hasNext
                    ? () => widget.onContentOffsetChanged(
                          contentOffset + documentDetailContentPageSize,
                        )
                    : null,
                icon: const Icon(Icons.chevron_right),
                tooltip: '下一段',
              ),
            ],
          ),
        ],
        const SizedBox(height: 8),
        _HighlightedDocumentText(
          text: bodyText,
          highlightRange: range,
          highlightKey: _highlightKey,
        ),
      ],
    );
  }

  String? _cleanHighlight(String? value) {
    final compact = value?.trim();
    if (compact == null || compact.isEmpty) {
      return null;
    }
    return compact.endsWith('...')
        ? compact.substring(0, compact.length - 3)
        : compact;
  }

  _HighlightRange? _resolveHighlightRange(String text, String? highlight) {
    final start = widget.highlightStart;
    final end = widget.highlightEnd;
    final contentOffset = widget.document.contentOffset;
    final localStart = start == null ? null : start - contentOffset;
    final localEnd = end == null ? null : end - contentOffset;
    if (localStart != null &&
        localEnd != null &&
        localStart >= 0 &&
        localEnd > localStart &&
        localEnd <= text.length) {
      return _HighlightRange(localStart, localEnd);
    }

    final needle = highlight?.trim();
    if (needle == null || needle.isEmpty) {
      return null;
    }
    final matchIndex = text.toLowerCase().indexOf(needle.toLowerCase());
    if (matchIndex < 0) {
      return null;
    }
    return _HighlightRange(matchIndex, matchIndex + needle.length);
  }

  void _scheduleScrollToHighlight(_HighlightRange? range) {
    if (range == null || _didScrollToHighlight) {
      return;
    }
    _didScrollToHighlight = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final context = _highlightKey.currentContext;
      if (context == null) {
        return;
      }
      Scrollable.ensureVisible(
        context,
        duration: const Duration(milliseconds: 260),
        curve: Curves.easeOut,
        alignment: 0.25,
      );
    });
  }
}

class _HighlightedDocumentText extends StatelessWidget {
  const _HighlightedDocumentText({
    required this.text,
    required this.highlightRange,
    required this.highlightKey,
  });

  final String text;
  final _HighlightRange? highlightRange;
  final GlobalKey highlightKey;

  @override
  Widget build(BuildContext context) {
    final range = highlightRange;
    if (range == null) {
      return Text(text);
    }

    final colorScheme = Theme.of(context).colorScheme;
    final before = text.substring(0, range.start);
    final match = text.substring(range.start, range.end);
    final after = text.substring(range.end);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (before.isNotEmpty) Text(before),
        DecoratedBox(
          key: highlightKey,
          decoration: BoxDecoration(
            color: colorScheme.tertiaryContainer,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
            child: Text(
              match,
              style: TextStyle(
                color: colorScheme.onTertiaryContainer,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ),
        if (after.isNotEmpty) Text(after),
      ],
    );
  }
}

class _HighlightRange {
  const _HighlightRange(this.start, this.end);

  final int start;
  final int end;
}

class _InfoPanel extends StatelessWidget {
  const _InfoPanel({
    required this.title,
    required this.text,
    this.isError = false,
  });

  final String title;
  final String text;
  final bool isError;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final borderColor =
        isError ? colorScheme.error : colorScheme.outlineVariant;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: borderColor),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  color: isError ? colorScheme.error : null,
                ),
          ),
          const SizedBox(height: 6),
          Text(text),
        ],
      ),
    );
  }
}
