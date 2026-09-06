import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/user_error_message.dart';
import '../../tags/providers/tags_provider.dart';
import '../providers/documents_provider.dart';

class NewNotePage extends ConsumerStatefulWidget {
  const NewNotePage({super.key});

  @override
  ConsumerState<NewNotePage> createState() => _NewNotePageState();
}

class _NewNotePageState extends ConsumerState<NewNotePage> {
  final _titleController = TextEditingController();
  final _contentController = TextEditingController();
  final _tagsController = TextEditingController();
  bool _saving = false;

  @override
  void dispose() {
    _titleController.dispose();
    _contentController.dispose();
    _tagsController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('记一条')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          TextField(
              controller: _titleController,
              decoration: const InputDecoration(labelText: '标题')),
          const SizedBox(height: 12),
          TextField(
              controller: _tagsController,
              decoration: const InputDecoration(labelText: '标签，逗号分隔')),
          const SizedBox(height: 12),
          TextField(
            controller: _contentController,
            minLines: 8,
            maxLines: 16,
            decoration: const InputDecoration(labelText: '内容'),
          ),
          const SizedBox(height: 20),
          FilledButton(
            onPressed: _saving ? null : _save,
            child: Text(_saving ? '保存中' : '保存'),
          ),
        ],
      ),
    );
  }

  Future<void> _save() async {
    final content = _contentController.text.trim();
    if (content.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请输入笔记内容')),
      );
      return;
    }
    setState(() => _saving = true);
    final tags = _tagsController.text
        .replaceAll('，', ',')
        .split(',')
        .map((item) => item.trim())
        .where((item) => item.isNotEmpty)
        .toList();
    try {
      await ref.read(documentsApiProvider).createNote(
            title: _titleController.text,
            content: content,
            tags: tags,
          );
      ref.invalidate(documentsProvider);
      ref.invalidate(documentsPageProvider);
      ref.invalidate(selectableDocumentsProvider);
      ref.invalidate(documentStatsProvider);
      ref.invalidate(tagsProvider);
      if (mounted) {
        context.pop();
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              userFacingErrorMessage(
                error,
                fallback: '保存笔记失败，请稍后重试',
              ),
            ),
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _saving = false);
      }
    }
  }
}
