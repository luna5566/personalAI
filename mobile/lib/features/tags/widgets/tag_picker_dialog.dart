import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/user_error_message.dart';
import '../providers/tags_provider.dart';

Future<Set<String>?> showTagPickerDialog(
  BuildContext context, {
  required Set<String> selectedNames,
  required int maxSelection,
}) {
  return showDialog<Set<String>>(
    context: context,
    builder: (_) => TagPickerDialog(
      selectedNames: selectedNames,
      maxSelection: maxSelection,
    ),
  );
}

class TagPickerDialog extends ConsumerStatefulWidget {
  const TagPickerDialog({
    required this.selectedNames,
    required this.maxSelection,
    super.key,
  });

  final Set<String> selectedNames;
  final int maxSelection;

  @override
  ConsumerState<TagPickerDialog> createState() => _TagPickerDialogState();
}

class _TagPickerDialogState extends ConsumerState<TagPickerDialog> {
  late final Set<String> _selected = {...widget.selectedNames};
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
    final page = ref.watch(tagsPageProvider(query));
    final size = MediaQuery.sizeOf(context);

    return AlertDialog(
      title: const Text('选择标签'),
      content: SizedBox(
        width: math.min(size.width * 0.85, 520),
        height: math.min(size.height * 0.65, 480),
        child: Column(
          children: [
            TextField(
              decoration: const InputDecoration(
                prefixIcon: Icon(Icons.search),
                hintText: '搜索标签',
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
                    ? const Center(child: Text('没有匹配的标签'))
                    : ListView.builder(
                        itemCount: value.items.length,
                        itemBuilder: (context, index) {
                          final tag = value.items[index];
                          return CheckboxListTile(
                            value: _selected.contains(tag.name),
                            title: Text(tag.name),
                            contentPadding: EdgeInsets.zero,
                            onChanged: (selected) =>
                                _toggle(tag.name, selected ?? false),
                          );
                        },
                      ),
                error: (error, _) => Center(
                  child: Text(
                    userFacingErrorMessage(
                      error,
                      fallback: '暂时无法加载标签',
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
          onPressed: () => Navigator.of(context).pop(_selected),
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

  void _toggle(String name, bool selected) {
    setState(() {
      _selectionError = null;
      if (!selected) {
        _selected.remove(name);
        return;
      }
      if (_selected.contains(name)) {
        return;
      }
      if (widget.maxSelection == 1) {
        _selected
          ..clear()
          ..add(name);
        return;
      }
      if (_selected.length >= widget.maxSelection) {
        _selectionError = '最多选择 ${widget.maxSelection} 个标签';
        return;
      }
      _selected.add(name);
    });
  }

  void _previousPage() => setState(() => _page -= 1);

  void _nextPage() => setState(() => _page += 1);
}
