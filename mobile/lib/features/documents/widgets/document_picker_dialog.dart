import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/user_error_message.dart';
import '../providers/documents_provider.dart';

class DocumentSelectionResult {
  const DocumentSelectionResult({
    required this.ids,
    required this.titles,
  });

  final Set<String> ids;
  final Map<String, String> titles;
}

Future<DocumentSelectionResult?> showDocumentPickerDialog(
  BuildContext context, {
  required Set<String> selectedIds,
  Map<String, String> selectedTitles = const {},
  required int maxSelection,
}) {
  return showDialog<DocumentSelectionResult>(
    context: context,
    builder: (_) => DocumentPickerDialog(
      selectedIds: selectedIds,
      selectedTitles: selectedTitles,
      maxSelection: maxSelection,
    ),
  );
}

class DocumentPickerDialog extends ConsumerStatefulWidget {
  const DocumentPickerDialog({
    required this.selectedIds,
    required this.selectedTitles,
    required this.maxSelection,
    super.key,
  });

  final Set<String> selectedIds;
  final Map<String, String> selectedTitles;
  final int maxSelection;

  @override
  ConsumerState<DocumentPickerDialog> createState() =>
      _DocumentPickerDialogState();
}

class _DocumentPickerDialogState extends ConsumerState<DocumentPickerDialog> {
  late final Set<String> _selected = {...widget.selectedIds};
  late final Map<String, String> _titles = {...widget.selectedTitles};
  Timer? _debounce;
  String? _keyword;
  String? _selectionError;
  int _page = 1;

  @override
  void dispose() {
    _debounce?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final query = (keyword: _keyword, page: _page);
    final page = ref.watch(selectableDocumentsPageProvider(query));
    final size = MediaQuery.sizeOf(context);

    return AlertDialog(
      title: const Text('选择资料'),
      content: SizedBox(
        width: math.min(size.width * 0.85, 560),
        height: math.min(size.height * 0.65, 500),
        child: Column(
          children: [
            TextField(
              decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                hintText: '搜索资料',
              ),
              onChanged: _search,
            ),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerLeft,
              child: Text('已选 ${_selected.length}/${widget.maxSelection}'),
            ),
            if (_selectionError != null)
              Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  _selectionError!,
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.error,
                  ),
                ),
              ),
            const SizedBox(height: 8),
            Expanded(
              child: page.when(
                data: (value) => value.items.isEmpty
                    ? const Center(child: Text('没有匹配的资料'))
                    : ListView.builder(
                        itemCount: value.items.length,
                        itemBuilder: (context, index) {
                          final document = value.items[index];
                          return CheckboxListTile(
                            value: _selected.contains(document.id),
                            title: Text(document.title),
                            subtitle: Text(document.sourceType),
                            contentPadding: EdgeInsets.zero,
                            onChanged: (selected) => _toggle(
                              document.id,
                              document.title,
                              selected ?? false,
                            ),
                          );
                        },
                      ),
                error: (error, _) => Center(
                  child: Text(
                    userFacingErrorMessage(
                      error,
                      fallback: '暂时无法加载资料',
                    ),
                  ),
                ),
                loading: () => const Center(
                  child: CircularProgressIndicator(),
                ),
              ),
            ),
            page.maybeWhen(
              data: (value) => Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  IconButton(
                    onPressed: value.hasPrevious ? _previousPage : null,
                    icon: const Icon(Icons.chevron_left),
                    tooltip: '上一页',
                  ),
                  SizedBox(
                    width: 88,
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
              orElse: () => const SizedBox(height: 48),
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
          onPressed: () => Navigator.of(context).pop(
            DocumentSelectionResult(
              ids: _selected,
              titles: {
                for (final id in _selected)
                  if (_titles[id] != null) id: _titles[id]!,
              },
            ),
          ),
          child: const Text('确定'),
        ),
      ],
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

  void _toggle(String id, String title, bool selected) {
    setState(() {
      _selectionError = null;
      if (!selected) {
        _selected.remove(id);
        _titles.remove(id);
        return;
      }
      if (_selected.contains(id)) {
        return;
      }
      if (_selected.length >= widget.maxSelection) {
        _selectionError = '最多选择 ${widget.maxSelection} 份资料';
        return;
      }
      _selected.add(id);
      _titles[id] = title;
    });
  }

  void _previousPage() => setState(() => _page -= 1);

  void _nextPage() => setState(() => _page += 1);
}
