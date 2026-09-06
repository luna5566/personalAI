import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../models/document.dart';

class DocumentCard extends StatelessWidget {
  const DocumentCard({
    required this.document,
    this.selectionMode = false,
    this.selected = false,
    this.onTap,
    this.onLongPress,
    super.key,
  });

  final KnowledgeDocument document;
  final bool selectionMode;
  final bool selected;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        onTap: onTap ?? () => context.push('/app/documents/${document.id}'),
        onLongPress: onLongPress,
        borderRadius: BorderRadius.circular(8),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  if (selectionMode) ...[
                    Checkbox(value: selected, onChanged: (_) => onTap?.call()),
                    const SizedBox(width: 4),
                  ],
                  Expanded(
                      child: Text(document.title,
                          style: Theme.of(context).textTheme.titleMedium)),
                  _StatusBadge(document: document),
                ],
              ),
              const SizedBox(height: 4),
              Text(
                _metadataLabel(document),
                style: Theme.of(context).textTheme.labelMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
              if (document.summary != null && document.summary!.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(document.summary!,
                    maxLines: 2, overflow: TextOverflow.ellipsis),
              ],
              if (document.tags.isNotEmpty) ...[
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final tag in document.tags) Chip(label: Text(tag)),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  String _metadataLabel(KnowledgeDocument document) {
    final createdAt = document.createdAt;
    if (createdAt == null) {
      return document.sourceTypeLabel;
    }
    final month = createdAt.month.toString().padLeft(2, '0');
    final day = createdAt.day.toString().padLeft(2, '0');
    return '${document.sourceTypeLabel} · ${createdAt.year}-$month-$day';
  }
}

class _StatusBadge extends StatelessWidget {
  const _StatusBadge({required this.document});

  final KnowledgeDocument document;

  @override
  Widget build(BuildContext context) {
    return Chip(
      label: Text(document.statusLabel),
      visualDensity: VisualDensity.compact,
    );
  }
}
