import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/user_error_message.dart';
import '../../../core/widgets/markdown_text.dart';
import '../../chat/providers/chat_provider.dart';
import '../../documents/models/document.dart';
import '../../documents/providers/documents_provider.dart';
import '../../documents/widgets/document_picker_dialog.dart';
import '../../tags/models/tag.dart';
import '../../tags/providers/tags_provider.dart';
import '../../tags/widgets/tag_picker_dialog.dart';
import '../providers/organize_provider.dart';

class OrganizePage extends ConsumerStatefulWidget {
  const OrganizePage({super.key});

  @override
  ConsumerState<OrganizePage> createState() => _OrganizePageState();
}

class _OrganizePageState extends ConsumerState<OrganizePage> {
  static const _maxSelectedDocuments = 20;

  String _mode = 'themes';
  String? _selectedTag;
  final Set<String> _selectedDocumentIds = {};
  final Map<String, String> _selectedDocumentTitles = {};
  bool _saveAsNote = false;

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(organizeControllerProvider);
    final tags = ref.watch(tagsProvider);
    final documents = ref.watch(selectableDocumentsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('整理')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'themes', label: Text('主题')),
              ButtonSegment(value: 'connections', label: Text('关联')),
              ButtonSegment(value: 'article_outline', label: Text('大纲')),
              ButtonSegment(value: 'study_plan', label: Text('计划')),
            ],
            selected: {_mode},
            onSelectionChanged: (value) => setState(() => _mode = value.first),
          ),
          const SizedBox(height: 12),
          _OrganizeScopeBar(
            tags: tags,
            selectedTag: _selectedTag,
            onSelected: _selectTag,
            onBrowse: _browseTag,
          ),
          const SizedBox(height: 12),
          _DocumentSelectionPanel(
            documents: documents,
            selectedDocumentIds: _selectedDocumentIds,
            onChanged: _toggleDocument,
            onBrowse: _browseDocuments,
          ),
          const SizedBox(height: 12),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('保存为新笔记'),
            value: _saveAsNote,
            onChanged: (value) => setState(() => _saveAsNote = value),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: state.isLoading
                ? null
                : () => ref
                    .read(organizeControllerProvider.notifier)
                    .organizeCollection(
                      mode: _mode,
                      tag: _selectedTag,
                      documentIds: _selectedDocumentIds.toList(),
                      saveAsNote: _saveAsNote,
                    ),
            icon: const Icon(Icons.auto_awesome),
            label: Text(_actionLabel),
          ),
          const SizedBox(height: 16),
          state.when(
            data: (result) => result == null
                ? const Text('选择一种整理方式。')
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (result.savedDocumentId != null)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 12),
                          child: _SavedNoteBanner(
                            documentId: result.savedDocumentId!,
                            onOpen: () {
                              ref.invalidate(documentsProvider);
                              ref.invalidate(documentsPageProvider);
                              ref.invalidate(selectableDocumentsProvider);
                              ref.invalidate(tagsProvider);
                              context.push(
                                '/app/documents/${result.savedDocumentId}',
                              );
                            },
                          ),
                        ),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          border: Border.all(
                            color: Theme.of(context).colorScheme.outlineVariant,
                          ),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: MarkdownText(data: result.result),
                      ),
                      const SizedBox(height: 12),
                      Align(
                        alignment: Alignment.centerRight,
                        child: OutlinedButton.icon(
                          onPressed: () => _continueWithSources(
                            result.sourceDocumentIds,
                          ),
                          icon: const Icon(Icons.chat_bubble_outline),
                          label: const Text('继续追问'),
                        ),
                      ),
                    ],
                  ),
            error: (error, _) => Text(
              userFacingErrorMessage(
                error,
                fallback: '整理失败，请稍后重试',
              ),
            ),
            loading: () => const Center(child: CircularProgressIndicator()),
          ),
        ],
      ),
    );
  }

  String get _actionLabel {
    if (_selectedDocumentIds.isNotEmpty) {
      return '整理已选资料';
    }
    return _selectedTag == null ? '整理最近 10 份资料' : '整理当前标签';
  }

  void _selectTag(String? tag) {
    setState(() {
      _selectedTag = tag;
      _selectedDocumentIds.clear();
      _selectedDocumentTitles.clear();
    });
  }

  void _toggleDocument(KnowledgeDocument document) {
    if (!_selectedDocumentIds.contains(document.id) &&
        _selectedDocumentIds.length >= _maxSelectedDocuments) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('一次最多选择 20 份资料')),
      );
      return;
    }
    setState(() {
      _selectedTag = null;
      if (_selectedDocumentIds.contains(document.id)) {
        _selectedDocumentIds.remove(document.id);
        _selectedDocumentTitles.remove(document.id);
      } else {
        _selectedDocumentIds.add(document.id);
        _selectedDocumentTitles[document.id] = document.title;
      }
    });
  }

  Future<void> _browseTag() async {
    final selection = await showTagPickerDialog(
      context,
      selectedNames: {
        ?_selectedTag,
      },
      maxSelection: 1,
    );
    if (selection == null || !mounted) {
      return;
    }
    _selectTag(selection.firstOrNull);
  }

  Future<void> _browseDocuments() async {
    final selection = await showDocumentPickerDialog(
      context,
      selectedIds: _selectedDocumentIds,
      selectedTitles: _selectedDocumentTitles,
      maxSelection: _maxSelectedDocuments,
    );
    if (selection == null || !mounted) {
      return;
    }
    setState(() {
      _selectedTag = null;
      _selectedDocumentIds
        ..clear()
        ..addAll(selection.ids);
      _selectedDocumentTitles
        ..clear()
        ..addAll(selection.titles);
    });
  }

  void _continueWithSources(List<String> sourceDocumentIds) {
    ref.read(chatControllerProvider.notifier).clear();
    context.go(
      Uri(
        path: '/app/chat',
        queryParameters: {
          if (sourceDocumentIds.isNotEmpty)
            'documentIds': sourceDocumentIds.join(','),
        },
      ).toString(),
    );
  }
}

class _OrganizeScopeBar extends StatelessWidget {
  const _OrganizeScopeBar({
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
                  label: const Text('最近 10 份'),
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
            separatorBuilder: (_, _) => const SizedBox(width: 8),
            itemCount: items.length + 2,
          ),
        );
      },
      error: (_, _) => const SizedBox.shrink(),
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

class _DocumentSelectionPanel extends StatelessWidget {
  const _DocumentSelectionPanel({
    required this.documents,
    required this.selectedDocumentIds,
    required this.onChanged,
    required this.onBrowse,
  });

  final AsyncValue<List<KnowledgeDocument>> documents;
  final Set<String> selectedDocumentIds;
  final ValueChanged<KnowledgeDocument> onChanged;
  final VoidCallback onBrowse;

  @override
  Widget build(BuildContext context) {
    return documents.when(
      data: (items) {
        final indexedItems =
            items.where((document) => document.isIndexed).toList();
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '手动选择资料（已选 ${selectedDocumentIds.length}/20）',
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: OutlinedButton.icon(
                onPressed: onBrowse,
                icon: const Icon(Icons.manage_search),
                label: const Text('查找资料'),
              ),
            ),
            if (indexedItems.isNotEmpty) const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final document in indexedItems)
                  FilterChip(
                    avatar: const Icon(Icons.description_outlined, size: 18),
                    label: Text(document.title),
                    selected: selectedDocumentIds.contains(document.id),
                    onSelected: (_) => onChanged(document),
                  ),
              ],
            ),
          ],
        );
      },
      error: (_, _) => const SizedBox.shrink(),
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

class _SavedNoteBanner extends StatelessWidget {
  const _SavedNoteBanner({
    required this.documentId,
    required this.onOpen,
  });

  final String documentId;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: colorScheme.primaryContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(Icons.note_alt_outlined, color: colorScheme.onPrimaryContainer),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              '已保存为新笔记',
              style: TextStyle(color: colorScheme.onPrimaryContainer),
            ),
          ),
          TextButton(
            onPressed: onOpen,
            child: const Text('打开'),
          ),
        ],
      ),
    );
  }
}
