import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/widgets/markdown_text.dart';
import '../../documents/models/document.dart';
import '../../documents/providers/documents_provider.dart';
import '../../documents/widgets/document_picker_dialog.dart';
import '../../tags/models/tag.dart';
import '../../tags/providers/tags_provider.dart';
import '../../tags/widgets/tag_picker_dialog.dart';
import '../models/chat.dart';
import '../providers/chat_provider.dart';
import '../services/speech_input_service.dart';

class ChatPage extends ConsumerStatefulWidget {
  const ChatPage({
    this.initialDocumentId,
    this.initialDocumentIds = const [],
    super.key,
  });

  final String? initialDocumentId;
  final List<String> initialDocumentIds;

  @override
  ConsumerState<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends ConsumerState<ChatPage> {
  final _controller = TextEditingController();
  final _scrollController = ScrollController();
  final Set<String> _selectedTags = {};
  final Set<String> _selectedDocumentIds = {};
  final Map<String, String> _selectedDocumentTitles = {};
  final Set<String> _selectedSourceTypes = {};
  int? _selectedRecentDays;
  int _inputRevision = 0;
  bool _listening = false;
  late final SpeechInputService _speechInput;

  @override
  void initState() {
    super.initState();
    _speechInput = ref.read(speechInputServiceProvider);
    final activeChat = ref.read(chatControllerProvider);
    _selectedTags.addAll(activeChat.scopeTags);
    _selectedDocumentIds.addAll(activeChat.scopeDocumentIds);
    _selectedSourceTypes.addAll(activeChat.scopeSourceTypes);
    _selectedRecentDays = activeChat.scopeRecentDays;
    _selectedDocumentIds.addAll(widget.initialDocumentIds);
    if (widget.initialDocumentId != null) {
      _selectedDocumentIds.add(widget.initialDocumentId!);
    }
  }

  @override
  void dispose() {
    _speechInput.stop();
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final chat = ref.watch(chatControllerProvider);
    final tags = ref.watch(tagsProvider);
    final documents = ref.watch(selectableDocumentsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('提问'),
        actions: [
          IconButton(
            onPressed: () => context.push('/app/chat/history'),
            icon: const Icon(Icons.history),
            tooltip: '会话历史',
          ),
          IconButton(
            onPressed: chat.messages.isEmpty
                ? null
                : () => ref.read(chatControllerProvider.notifier).clear(),
            icon: const Icon(Icons.delete_outline),
            tooltip: '清空对话',
          ),
        ],
      ),
      body: Column(
        children: [
          _ChatScopeBar(
            tags: tags,
            documents: documents,
            selectedTags: _selectedTags,
            selectedDocumentIds: _selectedDocumentIds,
            selectedDocumentTitles: _selectedDocumentTitles,
            selectedSourceTypes: _selectedSourceTypes,
            selectedRecentDays: _selectedRecentDays,
            onTagChanged: _toggleTag,
            onDocumentChanged: _toggleDocument,
            onSourceTypeChanged: _toggleSourceType,
            onRecentDaysChanged: _setRecentDays,
            onBrowseTags: _browseTags,
            onBrowseDocuments: _browseDocuments,
          ),
          if (chat.resumedFromHistory) const _ConversationResumeBanner(),
          if (chat.olderMessagesHidden)
            _OlderMessagesHiddenBanner(
              onOpenHistory: () {
                final conversationId = chat.conversationId;
                context.push(
                  conversationId == null
                      ? '/app/chat/history'
                      : '/app/chat/history/$conversationId',
                );
              },
            ),
          Expanded(
            child: chat.isEmpty && !chat.loading
                ? const _EmptyChatView()
                : ListView.separated(
                    controller: _scrollController,
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
                    itemBuilder: (context, index) {
                      if (index == chat.messages.length) {
                        return const _TypingIndicator();
                      }
                      final isLast = index == chat.messages.length - 1;
                      return _MessageBubble(
                        message: chat.messages[index],
                        onSuggestedQuestion: _askSuggestedQuestion,
                        showRegenerate:
                            isLast &&
                            !chat.loading &&
                            chat.messages[index].role ==
                                ChatMessageRole.assistant,
                        onRegenerate: () => ref
                            .read(chatControllerProvider.notifier)
                            .regenerate(),
                      );
                    },
                    separatorBuilder: (_, _) => const SizedBox(height: 12),
                    itemCount: chat.messages.length + (chat.loading ? 1 : 0),
                  ),
          ),
          if (chat.error != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      chat.error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  TextButton.icon(
                    onPressed: chat.loading ? null : _retryLastQuestion,
                    icon: const Icon(Icons.refresh),
                    label: const Text('重试'),
                  ),
                ],
              ),
            ),
          SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(
                    child: TextField(
                      key: ValueKey(_inputRevision),
                      controller: _controller,
                      minLines: 1,
                      maxLines: 4,
                      textInputAction: TextInputAction.send,
                      decoration: const InputDecoration(hintText: '问我的资料'),
                      onSubmitted: (_) => _submitQuestion(),
                    ),
                  ),
                  const SizedBox(width: 8),
                  IconButton(
                    onPressed: chat.loading ? null : _toggleListening,
                    icon: Icon(_listening ? Icons.mic : Icons.mic_none),
                    color: _listening
                        ? Theme.of(context).colorScheme.error
                        : null,
                    tooltip: _listening ? '停止语音输入' : '语音输入',
                  ),
                  IconButton.filled(
                    onPressed: chat.loading
                        ? () => ref
                              .read(chatControllerProvider.notifier)
                              .stopStreaming()
                        : _submitQuestion,
                    icon: Icon(chat.loading ? Icons.stop : Icons.send),
                    tooltip: chat.loading ? '停止生成' : '发送',
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _submitQuestion() async {
    final question = _controller.text.trim();
    if (question.isEmpty) {
      return;
    }
    if (_listening) {
      await _speechInput.stop();
      if (mounted) {
        setState(() => _listening = false);
      }
    }
    _clearInput();
    await ref
        .read(chatControllerProvider.notifier)
        .ask(
          question,
          tags: _selectedTags.toList(),
          documentIds: _selectedDocumentIds.toList(),
          sourceTypes: _selectedSourceTypes.toList(),
          recentDays: _selectedRecentDays,
        );
    _scrollToBottom();
  }

  Future<void> _toggleListening() async {
    final speech = _speechInput;
    if (_listening) {
      await speech.stop();
      if (mounted) {
        setState(() => _listening = false);
      }
      return;
    }

    final available = await speech.start(
      onText: (text) {
        if (!mounted) {
          return;
        }
        _controller.value = TextEditingValue(
          text: text,
          selection: TextSelection.collapsed(offset: text.length),
        );
        setState(() {});
      },
      onStopped: () {
        if (mounted) {
          setState(() => _listening = false);
        }
      },
      onError: (_) {
        if (!mounted) {
          return;
        }
        setState(() => _listening = false);
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('语音识别失败，请检查麦克风权限后重试')));
      },
    );
    if (!mounted) {
      return;
    }
    if (!available) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('当前设备不支持语音识别或未授予麦克风权限')));
      return;
    }
    setState(() => _listening = true);
  }

  Future<void> _askSuggestedQuestion(String question) async {
    if (question.trim().isEmpty) {
      return;
    }
    _clearInput();
    await ref
        .read(chatControllerProvider.notifier)
        .ask(
          question,
          tags: _selectedTags.toList(),
          documentIds: _selectedDocumentIds.toList(),
          sourceTypes: _selectedSourceTypes.toList(),
          recentDays: _selectedRecentDays,
        );
    _scrollToBottom();
  }

  Future<void> _retryLastQuestion() async {
    await ref
        .read(chatControllerProvider.notifier)
        .retryLast(
          tags: _selectedTags.toList(),
          documentIds: _selectedDocumentIds.toList(),
          sourceTypes: _selectedSourceTypes.toList(),
          recentDays: _selectedRecentDays,
        );
    _scrollToBottom();
  }

  void _clearInput() {
    _controller.value = TextEditingValue.empty;
    setState(() => _inputRevision += 1);
    FocusScope.of(context).unfocus();
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

  void _toggleDocument(KnowledgeDocument document) {
    setState(() {
      if (_selectedDocumentIds.contains(document.id)) {
        _selectedDocumentIds.remove(document.id);
        _selectedDocumentTitles.remove(document.id);
      } else {
        _selectedDocumentIds.add(document.id);
        _selectedDocumentTitles[document.id] = document.title;
      }
    });
  }

  Future<void> _browseDocuments() async {
    final selection = await showDocumentPickerDialog(
      context,
      selectedIds: _selectedDocumentIds,
      selectedTitles: _selectedDocumentTitles,
      maxSelection: 100,
    );
    if (selection == null || !mounted) {
      return;
    }
    setState(() {
      _selectedDocumentIds
        ..clear()
        ..addAll(selection.ids);
      _selectedDocumentTitles
        ..clear()
        ..addAll(selection.titles);
    });
  }

  Future<void> _browseTags() async {
    final selection = await showTagPickerDialog(
      context,
      selectedNames: _selectedTags,
      maxSelection: 20,
    );
    if (selection == null || !mounted) {
      return;
    }
    setState(() {
      _selectedTags
        ..clear()
        ..addAll(selection);
    });
  }

  void _toggleSourceType(String sourceType) {
    setState(() {
      if (_selectedSourceTypes.contains(sourceType)) {
        _selectedSourceTypes.remove(sourceType);
      } else {
        _selectedSourceTypes.add(sourceType);
      }
    });
  }

  void _setRecentDays(int? days) {
    setState(() => _selectedRecentDays = days);
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) {
        return;
      }
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 220),
        curve: Curves.easeOut,
      );
    });
  }
}

class _ConversationResumeBanner extends StatelessWidget {
  const _ConversationResumeBanner();

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: colorScheme.secondaryContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        '正在继续历史会话',
        style: TextStyle(color: colorScheme.onSecondaryContainer),
      ),
    );
  }
}

class _OlderMessagesHiddenBanner extends StatelessWidget {
  const _OlderMessagesHiddenBanner({required this.onOpenHistory});

  final VoidCallback onOpenHistory;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Container(
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      padding: const EdgeInsets.fromLTRB(12, 6, 6, 6),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: [
          Icon(
            Icons.info_outline,
            size: 18,
            color: colorScheme.onSurfaceVariant,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '较早消息未显示',
              style: TextStyle(color: colorScheme.onSurfaceVariant),
            ),
          ),
          IconButton(
            onPressed: onOpenHistory,
            icon: const Icon(Icons.history),
            tooltip: '查看会话历史',
          ),
        ],
      ),
    );
  }
}

class _ChatScopeBar extends StatelessWidget {
  const _ChatScopeBar({
    required this.tags,
    required this.documents,
    required this.selectedTags,
    required this.selectedDocumentIds,
    required this.selectedDocumentTitles,
    required this.selectedSourceTypes,
    required this.selectedRecentDays,
    required this.onTagChanged,
    required this.onDocumentChanged,
    required this.onSourceTypeChanged,
    required this.onRecentDaysChanged,
    required this.onBrowseTags,
    required this.onBrowseDocuments,
  });

  final AsyncValue<List<KnowledgeTag>> tags;
  final AsyncValue<List<KnowledgeDocument>> documents;
  final Set<String> selectedTags;
  final Set<String> selectedDocumentIds;
  final Map<String, String> selectedDocumentTitles;
  final Set<String> selectedSourceTypes;
  final int? selectedRecentDays;
  final ValueChanged<String> onTagChanged;
  final ValueChanged<KnowledgeDocument> onDocumentChanged;
  final ValueChanged<String> onSourceTypeChanged;
  final ValueChanged<int?> onRecentDaysChanged;
  final VoidCallback onBrowseTags;
  final VoidCallback onBrowseDocuments;

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 2),
          child: Align(
            alignment: Alignment.centerLeft,
            child: Text(
              _scopeLabel(),
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelLarge,
            ),
          ),
        ),
        _RecentDaysScopeRow(
          selectedRecentDays: selectedRecentDays,
          onChanged: onRecentDaysChanged,
        ),
        _SourceTypeScopeRow(
          selectedSourceTypes: selectedSourceTypes,
          onChanged: onSourceTypeChanged,
        ),
        _DocumentScopeRow(
          documents: documents,
          selectedDocumentIds: selectedDocumentIds,
          onChanged: onDocumentChanged,
          onBrowse: onBrowseDocuments,
        ),
        _TagScopeRow(
          tags: tags,
          selectedTags: selectedTags,
          onChanged: onTagChanged,
          onBrowse: onBrowseTags,
        ),
      ],
    );
  }

  String _scopeLabel() {
    final parts = <String>[];
    if (selectedRecentDays != null) {
      parts.add('最近 $selectedRecentDays 天');
    }
    if (selectedTags.isNotEmpty) {
      parts.add(
        selectedTags.length <= 2
            ? selectedTags.join('、')
            : '${selectedTags.length} 个标签',
      );
    }
    if (selectedDocumentIds.isNotEmpty) {
      final catalogTitles = {
        for (final document in documents.value ?? const <KnowledgeDocument>[])
          document.id: document.title,
      };
      final titles = selectedDocumentIds
          .map((id) => selectedDocumentTitles[id] ?? catalogTitles[id])
          .whereType<String>()
          .toList();
      parts.add(
        titles.length == selectedDocumentIds.length && titles.length <= 2
            ? titles.join('、')
            : '${selectedDocumentIds.length} 份资料',
      );
    }
    if (selectedSourceTypes.isNotEmpty) {
      final labels = selectedSourceTypes.map(_sourceTypeLabel).toList();
      parts.add(labels.length <= 2 ? labels.join('、') : '${labels.length} 种类型');
    }
    return parts.isEmpty ? '当前范围：全部资料' : '当前范围：${parts.join(' · ')}';
  }

  String _sourceTypeLabel(String value) {
    return switch (value) {
      'note' => '笔记',
      'pdf' => 'PDF',
      'txt' => 'TXT',
      'markdown' => 'Markdown',
      'image' => '图片',
      'audio' => '音频',
      'ai_generated' => 'AI 生成',
      _ => value,
    };
  }
}

class _RecentDaysScopeRow extends StatelessWidget {
  const _RecentDaysScopeRow({
    required this.selectedRecentDays,
    required this.onChanged,
  });

  final int? selectedRecentDays;
  final ValueChanged<int?> onChanged;

  static const _options = [
    (label: '全部时间', value: null),
    (label: '最近 7 天', value: 7),
    (label: '最近 30 天', value: 30),
  ];

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 52,
      child: ListView.separated(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        scrollDirection: Axis.horizontal,
        itemBuilder: (context, index) {
          final option = _options[index];
          return FilterChip(
            label: Text(option.label),
            selected: selectedRecentDays == option.value,
            onSelected: (_) => onChanged(option.value),
          );
        },
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemCount: _options.length,
      ),
    );
  }
}

class _SourceTypeScopeRow extends StatelessWidget {
  const _SourceTypeScopeRow({
    required this.selectedSourceTypes,
    required this.onChanged,
  });

  final Set<String> selectedSourceTypes;
  final ValueChanged<String> onChanged;

  static const _options = [
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
      height: 52,
      child: ListView.separated(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        scrollDirection: Axis.horizontal,
        itemBuilder: (context, index) {
          final option = _options[index];
          return FilterChip(
            label: Text(option.label),
            selected: selectedSourceTypes.contains(option.value),
            onSelected: (_) => onChanged(option.value),
          );
        },
        separatorBuilder: (_, _) => const SizedBox(width: 8),
        itemCount: _options.length,
      ),
    );
  }
}

class _DocumentScopeRow extends StatelessWidget {
  const _DocumentScopeRow({
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
        final indexedItems = items
            .where((document) => document.isIndexed)
            .toList();
        return SizedBox(
          height: 52,
          child: ListView.separated(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
            scrollDirection: Axis.horizontal,
            itemBuilder: (context, index) {
              if (index == indexedItems.length) {
                return IconButton(
                  onPressed: onBrowse,
                  icon: const Icon(Icons.manage_search),
                  tooltip: '查找资料',
                );
              }
              final document = indexedItems[index];
              return FilterChip(
                avatar: const Icon(Icons.description_outlined, size: 18),
                label: Text(document.title),
                selected: selectedDocumentIds.contains(document.id),
                onSelected: (_) => onChanged(document),
              );
            },
            separatorBuilder: (_, _) => const SizedBox(width: 8),
            itemCount: indexedItems.length + 1,
          ),
        );
      },
      error: (_, _) => const SizedBox.shrink(),
      loading: () => const _ScopeLoadingRow(),
    );
  }
}

class _TagScopeRow extends StatelessWidget {
  const _TagScopeRow({
    required this.tags,
    required this.selectedTags,
    required this.onChanged,
    required this.onBrowse,
  });

  final AsyncValue<List<KnowledgeTag>> tags;
  final Set<String> selectedTags;
  final ValueChanged<String> onChanged;
  final VoidCallback onBrowse;

  @override
  Widget build(BuildContext context) {
    return tags.when(
      data: (items) {
        return SizedBox(
          height: 52,
          child: ListView.separated(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
            scrollDirection: Axis.horizontal,
            itemBuilder: (context, index) {
              if (index == items.length) {
                return IconButton(
                  onPressed: onBrowse,
                  icon: const Icon(Icons.manage_search),
                  tooltip: '查找标签',
                );
              }
              final tag = items[index];
              return FilterChip(
                label: Text(tag.name),
                selected: selectedTags.contains(tag.name),
                onSelected: (_) => onChanged(tag.name),
              );
            },
            separatorBuilder: (_, _) => const SizedBox(width: 8),
            itemCount: items.length + 1,
          ),
        );
      },
      error: (_, _) => const SizedBox.shrink(),
      loading: () => const _ScopeLoadingRow(),
    );
  }
}

class _ScopeLoadingRow extends StatelessWidget {
  const _ScopeLoadingRow();

  @override
  Widget build(BuildContext context) {
    return const SizedBox(
      height: 52,
      child: Align(
        alignment: Alignment.center,
        child: SizedBox.square(
          dimension: 18,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      ),
    );
  }
}

class _EmptyChatView extends StatelessWidget {
  const _EmptyChatView();

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: const [
        Text('向你的资料提一个问题。'),
        SizedBox(height: 8),
        Text('例如：最近的笔记里有哪些主题？这份资料可以怎么整理？'),
      ],
    );
  }
}

class _TypingIndicator extends StatelessWidget {
  const _TypingIndicator();

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(8),
        ),
        child: const Padding(
          padding: EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: SizedBox.square(
            dimension: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ),
      ),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({
    required this.message,
    required this.onSuggestedQuestion,
    this.showRegenerate = false,
    this.onRegenerate,
  });

  final ChatMessage message;
  final ValueChanged<String> onSuggestedQuestion;
  final bool showRegenerate;
  final VoidCallback? onRegenerate;

  @override
  Widget build(BuildContext context) {
    final isUser = message.role == ChatMessageRole.user;
    final colorScheme = Theme.of(context).colorScheme;

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            DecoratedBox(
              decoration: BoxDecoration(
                color: isUser ? colorScheme.primary : Colors.white,
                borderRadius: BorderRadius.circular(8),
                border: isUser
                    ? null
                    : Border.all(color: colorScheme.outlineVariant),
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
                      if (message.interrupted) ...[
                        const SizedBox(height: 8),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(
                              Icons.info_outline,
                              size: 16,
                              color: Theme.of(
                                context,
                              ).textTheme.labelMedium?.color,
                            ),
                            const SizedBox(width: 6),
                            Expanded(
                              child: Text(
                                '已停止生成，内容可能不完整',
                                style: Theme.of(context).textTheme.labelMedium,
                              ),
                            ),
                          ],
                        ),
                      ],
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
                          _CitationTile(citation: citation),
                      ],
                      if (message.suggestedQuestions.isNotEmpty) ...[
                        const SizedBox(height: 12),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            for (final question in message.suggestedQuestions)
                              ActionChip(
                                label: Text(question),
                                onPressed: () => onSuggestedQuestion(question),
                              ),
                          ],
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),
            if (showRegenerate)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: TextButton.icon(
                  onPressed: onRegenerate,
                  icon: const Icon(Icons.refresh, size: 18),
                  label: const Text('重新生成'),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _CitationTile extends ConsumerStatefulWidget {
  const _CitationTile({required this.citation});

  final Citation citation;

  @override
  ConsumerState<_CitationTile> createState() => _CitationTileState();
}

class _CitationTileState extends ConsumerState<_CitationTile> {
  bool _expanded = false;
  Future<KnowledgeDocument>? _contextFuture;

  static const _contextPadding = 500;
  static const _contextLimit = 2200;

  void _toggleContext() {
    setState(() {
      _expanded = !_expanded;
      if (_expanded && _contextFuture == null) {
        final start = widget.citation.startOffset ?? 0;
        final windowStart = start > _contextPadding
            ? start - _contextPadding
            : 0;
        _contextFuture = ref
            .read(documentsApiProvider)
            .getDocument(
              widget.citation.documentId,
              contentOffset: windowStart,
              contentLimit: _contextLimit,
            );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final citation = widget.citation;
    final canExpand =
        citation.startOffset != null && citation.endOffset != null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InkWell(
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
              border: Border.all(
                color: Theme.of(context).colorScheme.outlineVariant,
              ),
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
                      if (canExpand) ...[
                        const SizedBox(height: 4),
                        Align(
                          alignment: Alignment.centerRight,
                          child: GestureDetector(
                            onTap: _toggleContext,
                            child: Text(
                              _expanded ? '收起前后文' : '查看前后文',
                              style: Theme.of(context).textTheme.labelSmall
                                  ?.copyWith(
                                    color: Theme.of(
                                      context,
                                    ).colorScheme.primary,
                                  ),
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                const Icon(Icons.chevron_right, size: 18),
              ],
            ),
          ),
        ),
        if (_expanded) _buildContext(),
      ],
    );
  }

  Widget _buildContext() {
    return FutureBuilder<KnowledgeDocument>(
      future: _contextFuture,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Padding(
            padding: EdgeInsets.only(top: 8),
            child: SizedBox.square(
              dimension: 16,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
          );
        }
        if (snapshot.hasError || !snapshot.hasData) {
          return Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              '暂时无法加载前后文',
              style: Theme.of(context).textTheme.labelSmall,
            ),
          );
        }
        final document = snapshot.data!;
        final content = document.content ?? '';
        final start =
            ((widget.citation.startOffset ?? 0) - document.contentOffset)
                .clamp(0, content.length)
                .toInt();
        final end = ((widget.citation.endOffset ?? 0) - document.contentOffset)
            .clamp(start, content.length)
            .toInt();
        return Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.surfaceContainerHighest,
              borderRadius: BorderRadius.circular(6),
            ),
            child: SelectableText.rich(
              TextSpan(
                children: [
                  if (start > 0) TextSpan(text: content.substring(0, start)),
                  TextSpan(
                    text: content.substring(start, end),
                    style: TextStyle(
                      backgroundColor: Theme.of(
                        context,
                      ).colorScheme.primaryContainer,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  if (end < content.length)
                    TextSpan(text: content.substring(end)),
                ],
              ),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
        );
      },
    );
  }
}
