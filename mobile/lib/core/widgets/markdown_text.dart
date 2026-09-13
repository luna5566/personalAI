import 'package:flutter/material.dart';
import 'package:markdown_widget/markdown_widget.dart';

/// 以 Markdown 渲染 AI 生成内容（问答回答、整理结果）。
///
/// 使用 MarkdownBlock（纯 Column，无滚动容器），用于嵌入消息气泡或
/// 页面级滚动视图；长按可选择文本。
class MarkdownText extends StatelessWidget {
  const MarkdownText({super.key, required this.data});

  final String data;

  @override
  Widget build(BuildContext context) {
    if (data.trim().isEmpty) {
      return const SizedBox.shrink();
    }
    final theme = Theme.of(context);
    final baseStyle =
        theme.textTheme.bodyMedium ?? const TextStyle(fontSize: 14);
    final fontSize = baseStyle.fontSize ?? 14;
    final isDark = theme.brightness == Brightness.dark;
    final config = MarkdownConfig(configs: [
      PConfig(textStyle: baseStyle.copyWith(height: 1.6)),
      H1Config(
        style:
            baseStyle.copyWith(fontSize: 20, fontWeight: FontWeight.w700),
      ),
      H2Config(
        style:
            baseStyle.copyWith(fontSize: 18, fontWeight: FontWeight.w700),
      ),
      H3Config(
        style:
            baseStyle.copyWith(fontSize: 16, fontWeight: FontWeight.w600),
      ),
      CodeConfig(
        style: baseStyle.copyWith(
          backgroundColor:
              isDark ? const Color(0xFF2A2A33) : const Color(0xFFF3F4F6),
          fontFamily: 'monospace',
          fontSize: fontSize - 1,
        ),
      ),
      PreConfig(
        textStyle: baseStyle.copyWith(
          color: const Color(0xFFE6E6E6),
          fontFamily: 'monospace',
          fontSize: fontSize - 1,
          height: 1.5,
        ),
        decoration: BoxDecoration(
          color: const Color(0xFF282C34),
          borderRadius: BorderRadius.circular(8),
        ),
      ),
    ]);
    return MarkdownBlock(data: data, config: config);
  }
}
