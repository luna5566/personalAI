import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/user_error_message.dart';
import '../../settings/models/media_capabilities.dart';
import '../../settings/providers/settings_provider.dart';
import '../../tags/models/tag.dart';
import '../../tags/providers/tags_provider.dart';
import '../providers/documents_provider.dart';

const _textUploadExtensions = [
  'txt',
  'md',
  'markdown',
  'pdf',
];

const _imageUploadExtensions = [
  'png',
  'jpg',
  'jpeg',
  'webp',
  'bmp',
  'gif',
  'tif',
  'tiff',
];

const _audioUploadExtensions = [
  'mp3',
  'wav',
  'm4a',
  'aac',
  'ogg',
  'opus',
  'flac',
];

List<String> allowedUploadExtensions(MediaCapabilities capabilities) {
  return [
    ..._textUploadExtensions,
    if (capabilities.ocrEnabled) ..._imageUploadExtensions,
    if (capabilities.speechToTextEnabled) ..._audioUploadExtensions,
  ];
}

bool isImageUploadFilename(String filename) {
  final parts = filename.toLowerCase().split('.');
  if (parts.length < 2) {
    return false;
  }
  return _imageUploadExtensions.contains(parts.last);
}

bool isAudioUploadFilename(String filename) {
  final parts = filename.toLowerCase().split('.');
  if (parts.length < 2) {
    return false;
  }
  return _audioUploadExtensions.contains(parts.last);
}

Future<bool> pickAndUploadDocument(
  BuildContext context,
  WidgetRef ref, {
  String? initialTag,
}) async {
  final capabilities = await ref.refresh(mediaCapabilitiesProvider.future);
  if (!context.mounted) {
    return false;
  }
  final result = await FilePicker.platform.pickFiles(
    type: FileType.custom,
    allowedExtensions: allowedUploadExtensions(capabilities),
    withData: true,
  );
  final file = result?.files.single;
  final path = file?.path;
  final bytes = file?.bytes;
  if (file == null) {
    return false;
  }
  if (!context.mounted) {
    return false;
  }
  if (path == null && bytes == null) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('无法读取所选文件')),
    );
    return false;
  }
  if (isImageUploadFilename(file.name) && !capabilities.ocrEnabled) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('图片 OCR 尚未启用，请改为上传 TXT、Markdown 或 PDF'),
      ),
    );
    return false;
  }
  if (isAudioUploadFilename(file.name) && !capabilities.speechToTextEnabled) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('语音转文字尚未启用，请改为上传 TXT、Markdown 或 PDF'),
      ),
    );
    return false;
  }

  final options = await showModalBottomSheet<UploadOptions>(
    context: context,
    isScrollControlled: true,
    builder: (context) => UploadOptionsSheet(
      filename: file.name,
      tags: ref.read(tagsProvider).valueOrNull ?? const [],
      initialTag: initialTag,
    ),
  );
  if (options == null) {
    return false;
  }

  try {
    final upload = await ref.read(documentsApiProvider).uploadDocument(
          filePath: path,
          fileBytes: bytes,
          filename: file.name,
          title: options.title,
          tags: options.tags,
        );
    ref.invalidate(documentsProvider);
    ref.invalidate(documentsPageProvider);
    ref.invalidate(tagsProvider);
    if (!context.mounted) {
      return true;
    }
    context.push('/app/jobs/${upload.jobId}?documentId=${upload.documentId}');
    return true;
  } catch (error) {
    if (!context.mounted) {
      return false;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          userFacingErrorMessage(
            error,
            fallback: '上传资料失败，请稍后重试',
          ),
        ),
      ),
    );
    return false;
  }
}

class UploadOptions {
  const UploadOptions({
    required this.title,
    required this.tags,
  });

  final String title;
  final List<String> tags;
}

class UploadOptionsSheet extends StatefulWidget {
  const UploadOptionsSheet({
    required this.filename,
    required this.tags,
    this.initialTag,
    super.key,
  });

  final String filename;
  final List<KnowledgeTag> tags;
  final String? initialTag;

  @override
  State<UploadOptionsSheet> createState() => _UploadOptionsSheetState();
}

class _UploadOptionsSheetState extends State<UploadOptionsSheet> {
  late final TextEditingController _titleController;
  late final TextEditingController _extraTagsController;
  late final Set<String> _selectedTags;

  @override
  void initState() {
    super.initState();
    _titleController = TextEditingController(
      text: _filenameWithoutExtension(widget.filename),
    );
    _extraTagsController = TextEditingController();
    _selectedTags = {
      if (widget.initialTag != null && widget.initialTag!.isNotEmpty)
        widget.initialTag!,
    };
  }

  @override
  void dispose() {
    _titleController.dispose();
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
            Text('上传设置', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 4),
            Text(widget.filename, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: 16),
            TextField(
              controller: _titleController,
              decoration: const InputDecoration(labelText: '资料标题'),
            ),
            const SizedBox(height: 12),
            if (widget.tags.isNotEmpty) ...[
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
              const SizedBox(height: 12),
            ],
            TextField(
              controller: _extraTagsController,
              decoration: const InputDecoration(labelText: '新标签，逗号分隔'),
            ),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: _confirm,
              icon: const Icon(Icons.upload_file_outlined),
              label: const Text('开始上传'),
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
    final title = _titleController.text.trim();
    Navigator.of(context).pop(
      UploadOptions(
        title:
            title.isEmpty ? _filenameWithoutExtension(widget.filename) : title,
        tags: [
          ..._selectedTags,
          ..._parseTags(_extraTagsController.text),
        ],
      ),
    );
  }

  String _filenameWithoutExtension(String filename) {
    final normalized = filename.split(RegExp(r'[\\/]')).last;
    final dotIndex = normalized.lastIndexOf('.');
    if (dotIndex <= 0) {
      return normalized;
    }
    return normalized.substring(0, dotIndex);
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
