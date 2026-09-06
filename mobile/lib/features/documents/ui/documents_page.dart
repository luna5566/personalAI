import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/user_error_message.dart';
import '../../../core/widgets/async_state_view.dart';
import '../../tags/models/tag.dart';
import '../../tags/providers/tags_provider.dart';
import '../../tags/widgets/tag_picker_dialog.dart';
import '../models/document.dart';
import '../providers/documents_provider.dart';
import '../widgets/document_card.dart';
import '../widgets/document_upload_flow.dart';

class DocumentsPage extends ConsumerStatefulWidget {
  const DocumentsPage({super.key});

  @override
  ConsumerState<DocumentsPage> createState() => _DocumentsPageState();
}

class _DocumentsPageState extends ConsumerState<DocumentsPage> {
  final _searchController = TextEditingController();
  Timer? _searchDebounce;
  bool _uploading = false;
  bool _bulkBusy = false;
  String? _selectedTag;
  String? _selectedSourceType;
  String? _keyword;
  int _page = 1;
  final Set<String> _selectedDocumentIds = {};

  DocumentsQuery get _query => (
        tag: _selectedTag,
        keyword: _keyword,
        sourceType: _selectedSourceType,
      );
  DocumentsPageQuery get _pageQuery => (
        tag: _selectedTag,
        keyword: _keyword,
        page: _page,
        sourceType: _selectedSourceType,
      );
  bool get _selectionMode => _selectedDocumentIds.isNotEmpty;

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final documents = ref.watch(documentsPageProvider(_pageQuery));
    final tags = ref.watch(tagsProvider);
    final visibleItems =
        documents.valueOrNull?.items ?? const <KnowledgeDocument>[];

    return Scaffold(
      appBar: AppBar(
        leading: _selectionMode
            ? IconButton(
                onPressed: _clearSelection,
                icon: const Icon(Icons.close),
                tooltip: '退出多选',
              )
            : null,
        title: Text(
            _selectionMode ? '已选 ${_selectedDocumentIds.length} 条' : '资料库'),
        actions: _selectionMode
            ? [
                IconButton(
                  onPressed: visibleItems.isEmpty
                      ? null
                      : () => _selectAllVisible(visibleItems),
                  icon: const Icon(Icons.select_all),
                  tooltip: '全选当前列表',
                ),
              ]
            : [
                IconButton(
                  onPressed: visibleItems.isEmpty
                      ? null
                      : () => _selectAllVisible(visibleItems),
                  icon: const Icon(Icons.checklist_outlined),
                  tooltip: '批量管理',
                ),
                IconButton(
                  onPressed: _uploading ? null : _pickAndUpload,
                  icon: _uploading
                      ? const SizedBox.square(
                          dimension: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.upload_file_outlined),
                  tooltip: '上传资料',
                ),
                IconButton(
                  onPressed: () => context.push('/app/documents/new-note'),
                  icon: const Icon(Icons.add),
                  tooltip: '记一条',
                ),
              ],
      ),
      bottomNavigationBar: _selectionMode
          ? _BulkActionBar(
              selectedCount: _selectedDocumentIds.length,
              busy: _bulkBusy,
              onEditTags: () => _openBulkTagEditor(visibleItems),
              onDelete: _confirmBulkDelete,
              onClear: _clearSelection,
            )
          : null,
      body: documents.when(
        data: (documentPage) {
          final items = documentPage.items;
          if (items.isEmpty &&
              _selectedTag == null &&
              _selectedSourceType == null &&
              _keyword == null) {
            return Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                  child: _SourceTypeFilterBar(
                    selectedSourceType: _selectedSourceType,
                    onSelected: _selectSourceType,
                  ),
                ),
                _TagFilterBar(
                  tags: tags,
                  selectedTag: _selectedTag,
                  onSelected: _selectTag,
                  onBrowse: _browseTagFilter,
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                  child: _SearchField(
                    controller: _searchController,
                    onChanged: _onSearchChanged,
                    onClear: _clearSearch,
                  ),
                ),
                Expanded(
                  child: EmptyView(
                    title: '还没有资料',
                    action: Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      alignment: WrapAlignment.center,
                      children: [
                        FilledButton.icon(
                          onPressed: _uploading ? null : _pickAndUpload,
                          icon: const Icon(Icons.upload_file_outlined),
                          label: const Text('上传资料'),
                        ),
                        OutlinedButton.icon(
                          onPressed: () =>
                              context.push('/app/documents/new-note'),
                          icon: const Icon(Icons.edit_note_outlined),
                          label: const Text('记一条'),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            );
          }
          return RefreshIndicator(
            onRefresh: () =>
                ref.refresh(documentsPageProvider(_pageQuery).future),
            child: ListView.separated(
              padding: const EdgeInsets.all(16),
              itemBuilder: (context, index) {
                if (index == 0) {
                  return Column(
                    children: [
                      _SearchField(
                        controller: _searchController,
                        onChanged: _onSearchChanged,
                        onClear: _clearSearch,
                      ),
                      const SizedBox(height: 12),
                      _SourceTypeFilterBar(
                        selectedSourceType: _selectedSourceType,
                        onSelected: _selectSourceType,
                      ),
                      const SizedBox(height: 12),
                      _TagFilterBar(
                        tags: tags,
                        selectedTag: _selectedTag,
                        onSelected: _selectTag,
                        onBrowse: _browseTagFilter,
                      ),
                    ],
                  );
                }
                if (items.isEmpty) {
                  return Padding(
                    padding: const EdgeInsets.only(top: 80),
                    child: Center(child: Text(_emptyResultText())),
                  );
                }
                if (index == items.length + 1) {
                  return _PaginationBar(
                    page: documentPage.page,
                    totalPages: documentPage.totalPages,
                    total: documentPage.total,
                    onPrevious: documentPage.hasPrevious
                        ? () => setState(() {
                              _page -= 1;
                              _selectedDocumentIds.clear();
                            })
                        : null,
                    onNext: documentPage.hasNext
                        ? () => setState(() {
                              _page += 1;
                              _selectedDocumentIds.clear();
                            })
                        : null,
                  );
                }
                final document = items[index - 1];
                return DocumentCard(
                  document: document,
                  selectionMode: _selectionMode,
                  selected: _selectedDocumentIds.contains(document.id),
                  onTap: _selectionMode
                      ? () => _toggleDocumentSelection(document.id)
                      : null,
                  onLongPress: () => _toggleDocumentSelection(document.id),
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
            fallback: '暂时无法加载资料',
          ),
          onRetry: () => ref.invalidate(documentsPageProvider(_pageQuery)),
        ),
        loading: () => const LoadingView(),
      ),
    );
  }

  void _selectTag(String? tag) {
    setState(() {
      _selectedTag = tag;
      _page = 1;
      _selectedDocumentIds.clear();
    });
  }

  Future<void> _browseTagFilter() async {
    final selection = await showTagPickerDialog(
      context,
      selectedNames: {
        if (_selectedTag != null) _selectedTag!,
      },
      maxSelection: 1,
    );
    if (selection == null || !mounted) {
      return;
    }
    _selectTag(selection.isEmpty ? null : selection.first);
  }

  void _selectSourceType(String? sourceType) {
    setState(() {
      _selectedSourceType = sourceType;
      _page = 1;
      _selectedDocumentIds.clear();
    });
  }

  void _onSearchChanged(String value) {
    _searchDebounce?.cancel();
    _searchDebounce = Timer(const Duration(milliseconds: 350), () {
      final trimmed = value.trim();
      if (_keyword == (trimmed.isEmpty ? null : trimmed)) {
        return;
      }
      setState(() {
        _keyword = trimmed.isEmpty ? null : trimmed;
        _page = 1;
        _selectedDocumentIds.clear();
      });
    });
  }

  void _clearSearch() {
    _searchDebounce?.cancel();
    _searchController.clear();
    setState(() {
      _keyword = null;
      _page = 1;
      _selectedDocumentIds.clear();
    });
  }

  void _toggleDocumentSelection(String documentId) {
    setState(() {
      if (_selectedDocumentIds.contains(documentId)) {
        _selectedDocumentIds.remove(documentId);
      } else {
        _selectedDocumentIds.add(documentId);
      }
    });
  }

  void _selectAllVisible(List<KnowledgeDocument> documents) {
    setState(() {
      _selectedDocumentIds
        ..clear()
        ..addAll(documents.map((document) => document.id));
    });
  }

  void _clearSelection() {
    setState(() => _selectedDocumentIds.clear());
  }

  Future<void> _openBulkTagEditor(List<KnowledgeDocument> visibleItems) async {
    final selectedDocuments = visibleItems
        .where((document) => _selectedDocumentIds.contains(document.id))
        .toList();
    if (selectedDocuments.isEmpty) {
      return;
    }
    final result = await showModalBottomSheet<_BulkTagEditResult>(
      context: context,
      isScrollControlled: true,
      builder: (context) => _BulkTagEditSheet(
        documents: selectedDocuments,
        tags: ref.read(tagsProvider).valueOrNull ?? const [],
      ),
    );
    if (result == null) {
      return;
    }
    if (!mounted) {
      return;
    }
    if (result.mode == _BulkTagEditMode.append && result.tags.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请选择或输入要追加的标签')),
      );
      return;
    }

    setState(() => _bulkBusy = true);
    try {
      final api = ref.read(documentsApiProvider);
      for (final document in selectedDocuments) {
        final nextTags = result.mode == _BulkTagEditMode.append
            ? {...document.tags, ...result.tags}.toList()
            : result.tags;
        await api.updateDocument(document.id, tags: nextTags);
      }
      if (!mounted) {
        return;
      }
      _clearSelection();
      ref.invalidate(documentsProvider(_query));
      ref.invalidate(documentsProvider);
      ref.invalidate(documentsPageProvider);
      ref.invalidate(tagsProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('已更新 ${selectedDocuments.length} 条资料的标签')),
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
              fallback: '批量更新资料失败，请稍后重试',
            ),
          ),
        ),
      );
    } finally {
      if (mounted) {
        setState(() => _bulkBusy = false);
      }
    }
  }

  Future<void> _confirmBulkDelete() async {
    final count = _selectedDocumentIds.length;
    if (count == 0) {
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除选中资料'),
        content: Text('确定删除这 $count 条资料吗？删除后无法恢复。'),
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

    final ids = _selectedDocumentIds.toList();
    final visibleCount =
        ref.read(documentsPageProvider(_pageQuery)).valueOrNull?.items.length ??
            0;
    setState(() => _bulkBusy = true);
    try {
      final api = ref.read(documentsApiProvider);
      for (final id in ids) {
        await api.deleteDocument(id);
      }
      if (!mounted) {
        return;
      }
      _clearSelection();
      if (ids.length == visibleCount && _page > 1) {
        setState(() => _page -= 1);
      }
      ref.invalidate(documentsProvider(_query));
      ref.invalidate(documentsProvider);
      ref.invalidate(documentsPageProvider);
      ref.invalidate(tagsProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('已删除 ${ids.length} 条资料')),
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
              fallback: '批量删除资料失败，请稍后重试',
            ),
          ),
        ),
      );
    } finally {
      if (mounted) {
        setState(() => _bulkBusy = false);
      }
    }
  }

  String _emptyResultText() {
    if (_keyword != null && _selectedTag != null) {
      return '没有找到匹配这个关键词和标签的资料';
    }
    if (_keyword != null) {
      return '没有找到匹配这个关键词的资料';
    }
    return '这个标签下还没有资料';
  }

  Future<void> _pickAndUpload() async {
    setState(() => _uploading = true);
    try {
      final uploaded = await pickAndUploadDocument(
        context,
        ref,
        initialTag: _selectedTag,
      );
      if (!mounted) {
        return;
      }
      if (uploaded) {
        _searchDebounce?.cancel();
        _searchController.clear();
        setState(() {
          _keyword = null;
          _selectedTag = null;
          _selectedSourceType = null;
          _page = 1;
        });
      }
    } finally {
      if (mounted) {
        setState(() => _uploading = false);
      }
    }
  }
}

class _PaginationBar extends StatelessWidget {
  const _PaginationBar({
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

class _BulkActionBar extends StatelessWidget {
  const _BulkActionBar({
    required this.selectedCount,
    required this.busy,
    required this.onEditTags,
    required this.onDelete,
    required this.onClear,
  });

  final int selectedCount;
  final bool busy;
  final VoidCallback onEditTags;
  final VoidCallback onDelete;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: BottomAppBar(
        child: Row(
          children: [
            Expanded(
              child: Text(
                '已选 $selectedCount 条',
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ),
            if (busy)
              const Padding(
                padding: EdgeInsets.only(right: 12),
                child: SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            IconButton(
              onPressed: busy ? null : onEditTags,
              icon: const Icon(Icons.sell_outlined),
              tooltip: '批量改标签',
            ),
            IconButton(
              onPressed: busy ? null : onDelete,
              icon: const Icon(Icons.delete_outline),
              tooltip: '批量删除',
            ),
            IconButton(
              onPressed: busy ? null : onClear,
              icon: const Icon(Icons.close),
              tooltip: '取消选择',
            ),
          ],
        ),
      ),
    );
  }
}

class _SourceTypeFilterBar extends StatelessWidget {
  const _SourceTypeFilterBar({
    required this.selectedSourceType,
    required this.onSelected,
  });

  final String? selectedSourceType;
  final ValueChanged<String?> onSelected;

  static const _options = [
    (label: '全部类型', value: null),
    (label: '笔记', value: 'note'),
    (label: 'PDF', value: 'pdf'),
    (label: 'TXT', value: 'txt'),
    (label: 'Markdown', value: 'markdown'),
    (label: '图片', value: 'image'),
    (label: '音频', value: 'audio'),
    (label: 'AI 生成', value: 'ai_generated'),
  ];

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 44,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemBuilder: (context, index) {
          final option = _options[index];
          return FilterChip(
            label: Text(option.label),
            selected: selectedSourceType == option.value,
            onSelected: (_) => onSelected(option.value),
          );
        },
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemCount: _options.length,
      ),
    );
  }
}

enum _BulkTagEditMode { append, replace }

class _BulkTagEditResult {
  const _BulkTagEditResult({
    required this.mode,
    required this.tags,
  });

  final _BulkTagEditMode mode;
  final List<String> tags;
}

class _BulkTagEditSheet extends StatefulWidget {
  const _BulkTagEditSheet({
    required this.documents,
    required this.tags,
  });

  final List<KnowledgeDocument> documents;
  final List<KnowledgeTag> tags;

  @override
  State<_BulkTagEditSheet> createState() => _BulkTagEditSheetState();
}

class _BulkTagEditSheetState extends State<_BulkTagEditSheet> {
  final _extraTagsController = TextEditingController();
  final Set<String> _selectedTags = {};
  _BulkTagEditMode _mode = _BulkTagEditMode.append;

  @override
  void dispose() {
    _extraTagsController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.viewInsetsOf(context).bottom;

    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(16, 16, 16, bottom + 16),
        child: ListView(
          shrinkWrap: true,
          children: [
            Text('批量改标签', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 4),
            Text('将应用到 ${widget.documents.length} 条资料'),
            const SizedBox(height: 16),
            SegmentedButton<_BulkTagEditMode>(
              segments: const [
                ButtonSegment(
                  value: _BulkTagEditMode.append,
                  label: Text('追加'),
                ),
                ButtonSegment(
                  value: _BulkTagEditMode.replace,
                  label: Text('覆盖'),
                ),
              ],
              selected: {_mode},
              onSelectionChanged: (value) {
                setState(() => _mode = value.single);
              },
            ),
            const SizedBox(height: 12),
            if (_mode == _BulkTagEditMode.replace)
              const _WarningPanel(text: '覆盖会用下面选择的标签替换原有标签；留空确认则会清空标签。'),
            if (widget.tags.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text('选择标签', style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final tag in widget.tags)
                    FilterChip(
                      label: Text(tag.name),
                      selected: _selectedTags.contains(tag.name),
                      onSelected: (_) => _toggleTag(tag.name),
                    ),
                ],
              ),
            ],
            const SizedBox(height: 12),
            TextField(
              controller: _extraTagsController,
              decoration: const InputDecoration(labelText: '新标签，逗号分隔'),
            ),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: _confirm,
              icon: const Icon(Icons.done),
              label: Text(_mode == _BulkTagEditMode.append ? '追加标签' : '覆盖标签'),
            ),
          ],
        ),
      ),
    );
  }

  void _toggleTag(String tag) {
    setState(() {
      if (_selectedTags.contains(tag)) {
        _selectedTags.remove(tag);
      } else {
        _selectedTags.add(tag);
      }
    });
  }

  void _confirm() {
    Navigator.of(context).pop(
      _BulkTagEditResult(
        mode: _mode,
        tags: {
          ..._selectedTags,
          ..._parseTags(_extraTagsController.text),
        }.toList(),
      ),
    );
  }

  List<String> _parseTags(String value) {
    return value
        .replaceAll('，', ',')
        .split(',')
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toSet()
        .toList();
  }
}

class _WarningPanel extends StatelessWidget {
  const _WarningPanel({required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Text(text, style: TextStyle(color: colors.onErrorContainer)),
      ),
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
        hintText: '搜索标题或内容',
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

class _TagFilterBar extends StatelessWidget {
  const _TagFilterBar({
    required this.tags,
    required this.selectedTag,
    required this.onSelected,
    required this.onBrowse,
  });

  final AsyncValue<List<KnowledgeTag>> tags;
  final String? selectedTag;
  final ValueChanged<String?> onSelected;
  final VoidCallback onBrowse;

  @override
  Widget build(BuildContext context) {
    return tags.when(
      data: (items) {
        return SizedBox(
          height: 44,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemBuilder: (context, index) {
              if (index == 0) {
                return FilterChip(
                  label: const Text('全部'),
                  selected: selectedTag == null,
                  onSelected: (_) => onSelected(null),
                );
              }
              if (index == items.length + 1) {
                return IconButton(
                  onPressed: onBrowse,
                  icon: const Icon(Icons.manage_search),
                  tooltip: '查找标签',
                );
              }
              final tag = items[index - 1];
              return FilterChip(
                label: Text(tag.name),
                selected: selectedTag == tag.name,
                onSelected: (_) => onSelected(tag.name),
              );
            },
            separatorBuilder: (_, __) => const SizedBox(width: 8),
            itemCount: items.length + 2,
          ),
        );
      },
      error: (_, __) => const SizedBox.shrink(),
      loading: () => const SizedBox(
        height: 44,
        child: Align(
          alignment: Alignment.centerLeft,
          child: SizedBox.square(
            dimension: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ),
      ),
    );
  }
}
