import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/user_error_message.dart';
import '../../../core/widgets/async_state_view.dart';
import '../../jobs/providers/jobs_provider.dart';
import '../models/runtime_settings.dart';
import '../providers/settings_provider.dart';

class ModelSettingsPage extends ConsumerWidget {
  const ModelSettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(runtimeSettingsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('模型设置')),
      body: settings.when(
        data: (value) => _ModelSettingsForm(settings: value),
        error: (error, _) => ErrorStateView(
          message: userFacingErrorMessage(
            error,
            fallback: '暂时无法加载模型设置',
          ),
          onRetry: () => ref.invalidate(runtimeSettingsProvider),
        ),
        loading: () => const LoadingView(),
      ),
    );
  }
}

class _ModelSettingsForm extends ConsumerStatefulWidget {
  const _ModelSettingsForm({required this.settings});

  final RuntimeSettings settings;

  @override
  ConsumerState<_ModelSettingsForm> createState() => _ModelSettingsFormState();
}

class _ModelSettingsFormState extends ConsumerState<_ModelSettingsForm> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _llmBaseUrlController;
  late final TextEditingController _llmModelController;
  late final TextEditingController _llmApiKeyController;
  late final TextEditingController _embeddingBaseUrlController;
  late final TextEditingController _embeddingModelController;
  late final TextEditingController _embeddingDimensionsController;
  late final TextEditingController _embeddingApiKeyController;
  late final TextEditingController _ocrBaseUrlController;
  late final TextEditingController _ocrModelController;
  late final TextEditingController _ocrApiKeyController;
  late final TextEditingController _speechBaseUrlController;
  late final TextEditingController _speechModelController;
  late final TextEditingController _speechApiKeyController;

  late String _llmProvider;
  late String _embeddingProvider;
  late String _ocrProvider;
  late String _speechProvider;
  bool _clearLlmApiKey = false;
  bool _clearEmbeddingApiKey = false;
  bool _clearOcrApiKey = false;
  bool _clearSpeechApiKey = false;
  bool _saving = false;
  bool _rebuilding = false;

  @override
  void initState() {
    super.initState();
    final settings = widget.settings;
    _llmProvider = _providerValue(
      settings.llmProvider,
      const ['local_extractive', 'openai_compatible'],
    );
    _embeddingProvider = _providerValue(
      settings.embeddingProvider,
      const ['local_hash', 'openai_compatible'],
    );
    _ocrProvider = _providerValue(
      settings.ocrProvider,
      const ['disabled', 'openai_compatible'],
    );
    _speechProvider = _providerValue(
      settings.speechToTextProvider,
      const ['disabled', 'openai_compatible'],
    );
    _llmBaseUrlController =
        TextEditingController(text: settings.llmBaseUrl ?? '');
    _llmModelController = TextEditingController(text: settings.llmModel ?? '');
    _llmApiKeyController = TextEditingController();
    _embeddingBaseUrlController =
        TextEditingController(text: settings.embeddingBaseUrl ?? '');
    _embeddingModelController =
        TextEditingController(text: settings.embeddingModel);
    _embeddingDimensionsController =
        TextEditingController(text: settings.embeddingDimensions.toString());
    _embeddingApiKeyController = TextEditingController();
    _ocrBaseUrlController =
        TextEditingController(text: settings.ocrBaseUrl ?? '');
    _ocrModelController = TextEditingController(text: settings.ocrModel);
    _ocrApiKeyController = TextEditingController();
    _speechBaseUrlController =
        TextEditingController(text: settings.speechToTextBaseUrl ?? '');
    _speechModelController =
        TextEditingController(text: settings.speechToTextModel);
    _speechApiKeyController = TextEditingController();
  }

  @override
  void dispose() {
    _llmBaseUrlController.dispose();
    _llmModelController.dispose();
    _llmApiKeyController.dispose();
    _embeddingBaseUrlController.dispose();
    _embeddingModelController.dispose();
    _embeddingDimensionsController.dispose();
    _embeddingApiKeyController.dispose();
    _ocrBaseUrlController.dispose();
    _ocrModelController.dispose();
    _ocrApiKeyController.dispose();
    _speechBaseUrlController.dispose();
    _speechModelController.dispose();
    _speechApiKeyController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Form(
      key: _formKey,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _SettingsSection(
            title: '运行环境',
            children: [
              _SettingsRow(label: '环境', value: widget.settings.appEnv),
              _SettingsRow(
                label: '存储',
                value: widget.settings.storageBackend,
              ),
              _SettingsRow(
                label: '图片 OCR',
                value: widget.settings.ocrProvider,
              ),
              _SettingsRow(
                label: '语音转文字',
                value: widget.settings.speechToTextProvider,
              ),
              const _SettingsRow(
                label: '密钥显示',
                value: 'API Key 只显示是否已配置，不回显内容',
              ),
            ],
          ),
          const SizedBox(height: 12),
          _SaveSettingsButton(saving: _saving, onPressed: _save),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _saving || _rebuilding ? null : _rebuildEmbeddings,
            icon: _rebuilding
                ? const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.refresh_outlined),
            label: const Text('重建全部资料索引'),
          ),
          const SizedBox(height: 12),
          _SettingsSection(
            title: '大模型',
            children: [
              DropdownButtonFormField<String>(
                initialValue: _providerValue(
                  _llmProvider,
                  const ['local_extractive', 'openai_compatible'],
                ),
                decoration: const InputDecoration(labelText: 'Provider'),
                items: const [
                  DropdownMenuItem(
                    value: 'local_extractive',
                    child: Text('local_extractive'),
                  ),
                  DropdownMenuItem(
                    value: 'openai_compatible',
                    child: Text('openai_compatible'),
                  ),
                ],
                onChanged: _saving
                    ? null
                    : (value) {
                        if (value != null) {
                          setState(() => _llmProvider = value);
                        }
                      },
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _llmModelController,
                decoration: const InputDecoration(labelText: '模型'),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _llmBaseUrlController,
                decoration: const InputDecoration(labelText: 'Base URL'),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _llmApiKeyController,
                enabled: !_clearLlmApiKey,
                obscureText: true,
                decoration: InputDecoration(
                  labelText: '新 API Key',
                  hintText: widget.settings.llmApiKeyConfigured
                      ? '留空表示保留当前密钥'
                      : '未配置',
                ),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('清空大模型 API Key'),
                value: _clearLlmApiKey,
                onChanged: _saving
                    ? null
                    : (value) {
                        setState(() {
                          _clearLlmApiKey = value;
                          if (value) {
                            _llmApiKeyController.clear();
                          }
                        });
                      },
              ),
            ],
          ),
          const SizedBox(height: 12),
          _SettingsSection(
            title: 'Embedding',
            children: [
              DropdownButtonFormField<String>(
                initialValue: _providerValue(
                  _embeddingProvider,
                  const ['local_hash', 'openai_compatible'],
                ),
                decoration: const InputDecoration(labelText: 'Provider'),
                items: const [
                  DropdownMenuItem(
                      value: 'local_hash', child: Text('local_hash')),
                  DropdownMenuItem(
                    value: 'openai_compatible',
                    child: Text('openai_compatible'),
                  ),
                ],
                onChanged: _saving
                    ? null
                    : (value) {
                        if (value != null) {
                          setState(() => _embeddingProvider = value);
                        }
                      },
              ),
              const SizedBox(height: 12),
              TextFormField(
                key: const ValueKey('embedding-model-field'),
                controller: _embeddingModelController,
                decoration: const InputDecoration(labelText: '模型'),
                validator: (value) =>
                    value == null || value.trim().isEmpty ? '请填写模型名' : null,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _embeddingDimensionsController,
                keyboardType: TextInputType.number,
                readOnly: true,
                decoration: const InputDecoration(
                  labelText: '维度',
                  helperText: '当前数据库固定为 1536 维',
                ),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _embeddingBaseUrlController,
                decoration: const InputDecoration(labelText: 'Base URL'),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: _embeddingApiKeyController,
                enabled: !_clearEmbeddingApiKey,
                obscureText: true,
                decoration: InputDecoration(
                  labelText: '新 API Key',
                  hintText: widget.settings.embeddingApiKeyConfigured
                      ? '留空表示保留当前密钥'
                      : '未配置',
                ),
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('清空 Embedding API Key'),
                value: _clearEmbeddingApiKey,
                onChanged: _saving
                    ? null
                    : (value) {
                        setState(() {
                          _clearEmbeddingApiKey = value;
                          if (value) {
                            _embeddingApiKeyController.clear();
                          }
                        });
                      },
              ),
            ],
          ),
          const SizedBox(height: 12),
          _SettingsSection(
            title: '图片 OCR',
            children: [
              _MediaProviderFields(
                provider: _ocrProvider,
                modelController: _ocrModelController,
                baseUrlController: _ocrBaseUrlController,
                apiKeyController: _ocrApiKeyController,
                apiKeyConfigured: widget.settings.ocrApiKeyConfigured,
                clearApiKey: _clearOcrApiKey,
                saving: _saving,
                onProviderChanged: (value) =>
                    setState(() => _ocrProvider = value),
                onClearApiKeyChanged: (value) {
                  setState(() {
                    _clearOcrApiKey = value;
                    if (value) {
                      _ocrApiKeyController.clear();
                    }
                  });
                },
              ),
            ],
          ),
          const SizedBox(height: 12),
          _SettingsSection(
            title: '语音转文字',
            children: [
              _MediaProviderFields(
                provider: _speechProvider,
                modelController: _speechModelController,
                baseUrlController: _speechBaseUrlController,
                apiKeyController: _speechApiKeyController,
                apiKeyConfigured: widget.settings.speechToTextApiKeyConfigured,
                clearApiKey: _clearSpeechApiKey,
                saving: _saving,
                onProviderChanged: (value) =>
                    setState(() => _speechProvider = value),
                onClearApiKeyChanged: (value) {
                  setState(() {
                    _clearSpeechApiKey = value;
                    if (value) {
                      _speechApiKeyController.clear();
                    }
                  });
                },
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            '保存后会写入后端 .env 并刷新当前运行配置。Embedding 配置变化时会自动重建所有用户的资料索引。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }

  String _providerValue(String value, List<String> supported) {
    return supported.contains(value) ? value : supported.first;
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }
    final dimensions = int.parse(_embeddingDimensionsController.text.trim());
    setState(() => _saving = true);
    try {
      final updateResult = await ref
          .read(settingsApiProvider)
          .updateRuntimeSettings(
            llmProvider: _llmProvider,
            llmBaseUrl: _blankToNull(_llmBaseUrlController.text),
            llmModel: _blankToNull(_llmModelController.text),
            llmApiKey: _blankToNull(_llmApiKeyController.text),
            clearLlmApiKey: _clearLlmApiKey,
            embeddingProvider: _embeddingProvider,
            embeddingBaseUrl: _blankToNull(_embeddingBaseUrlController.text),
            embeddingModel: _embeddingModelController.text.trim(),
            embeddingDimensions: dimensions,
            embeddingApiKey: _blankToNull(_embeddingApiKeyController.text),
            clearEmbeddingApiKey: _clearEmbeddingApiKey,
            ocrProvider: _ocrProvider,
            ocrBaseUrl: _blankToNull(_ocrBaseUrlController.text),
            ocrModel: _ocrModelController.text.trim(),
            ocrApiKey: _blankToNull(_ocrApiKeyController.text),
            clearOcrApiKey: _clearOcrApiKey,
            speechToTextProvider: _speechProvider,
            speechToTextBaseUrl: _blankToNull(_speechBaseUrlController.text),
            speechToTextModel: _speechModelController.text.trim(),
            speechToTextApiKey: _blankToNull(_speechApiKeyController.text),
            clearSpeechToTextApiKey: _clearSpeechApiKey,
          );
      if (!mounted) {
        return;
      }
      _llmApiKeyController.clear();
      _embeddingApiKeyController.clear();
      _ocrApiKeyController.clear();
      _speechApiKeyController.clear();
      setState(() {
        _clearLlmApiKey = false;
        _clearEmbeddingApiKey = false;
        _clearOcrApiKey = false;
        _clearSpeechApiKey = false;
      });
      if (updateResult.rebuildJobId != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Embedding 配置已保存，正在重建全部资料索引')),
        );
        context.push('/app/jobs/${updateResult.rebuildJobId}');
        ref.invalidate(runtimeSettingsProvider);
      } else {
        ref.invalidate(runtimeSettingsProvider);
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('模型配置已保存')),
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
              fallback: '保存模型设置失败，请稍后重试',
            ),
          ),
        ),
      );
    } finally {
      if (mounted) {
        setState(() => _saving = false);
      }
    }
  }

  String? _blankToNull(String value) {
    final trimmed = value.trim();
    return trimmed.isEmpty ? null : trimmed;
  }

  Future<void> _rebuildEmbeddings() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('重建全部资料索引'),
        content: const Text(
          '将按当前 Embedding 配置重新生成所有用户的资料向量。资料较多时会花一些时间。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('开始重建'),
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

    setState(() => _rebuilding = true);
    try {
      final job = await ref.read(jobsApiProvider).rebuildAllEmbeddings();
      if (!mounted) {
        return;
      }
      context.push('/app/jobs/${job.id}');
    } catch (error) {
      if (!mounted) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            userFacingErrorMessage(
              error,
              fallback: '启动索引重建失败，请稍后重试',
            ),
          ),
        ),
      );
    } finally {
      if (mounted) {
        setState(() => _rebuilding = false);
      }
    }
  }
}

class _MediaProviderFields extends StatelessWidget {
  const _MediaProviderFields({
    required this.provider,
    required this.modelController,
    required this.baseUrlController,
    required this.apiKeyController,
    required this.apiKeyConfigured,
    required this.clearApiKey,
    required this.saving,
    required this.onProviderChanged,
    required this.onClearApiKeyChanged,
  });

  final String provider;
  final TextEditingController modelController;
  final TextEditingController baseUrlController;
  final TextEditingController apiKeyController;
  final bool apiKeyConfigured;
  final bool clearApiKey;
  final bool saving;
  final ValueChanged<String> onProviderChanged;
  final ValueChanged<bool> onClearApiKeyChanged;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        DropdownButtonFormField<String>(
          initialValue: provider,
          decoration: const InputDecoration(labelText: 'Provider'),
          items: const [
            DropdownMenuItem(value: 'disabled', child: Text('disabled')),
            DropdownMenuItem(
              value: 'openai_compatible',
              child: Text('openai_compatible'),
            ),
          ],
          onChanged: saving
              ? null
              : (value) {
                  if (value != null) {
                    onProviderChanged(value);
                  }
                },
        ),
        const SizedBox(height: 12),
        TextFormField(
          controller: modelController,
          decoration: const InputDecoration(labelText: '模型'),
          validator: (value) => provider == 'openai_compatible' &&
                  (value == null || value.trim().isEmpty)
              ? '请填写模型名'
              : null,
        ),
        const SizedBox(height: 12),
        TextFormField(
          controller: baseUrlController,
          decoration: const InputDecoration(labelText: 'Base URL'),
        ),
        const SizedBox(height: 12),
        TextFormField(
          controller: apiKeyController,
          enabled: !clearApiKey,
          obscureText: true,
          decoration: InputDecoration(
            labelText: '新 API Key',
            hintText: apiKeyConfigured ? '留空表示保留当前密钥' : '未配置',
          ),
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: const Text('清空 API Key'),
          value: clearApiKey,
          onChanged: saving ? null : onClearApiKeyChanged,
        ),
      ],
    );
  }
}

class _SaveSettingsButton extends StatelessWidget {
  const _SaveSettingsButton({
    required this.saving,
    required this.onPressed,
  });

  final bool saving;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return FilledButton.icon(
      key: const ValueKey('save-model-settings'),
      onPressed: saving ? null : onPressed,
      icon: saving
          ? const SizedBox.square(
              dimension: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            )
          : const Icon(Icons.save_outlined),
      label: const Text('保存配置'),
    );
  }
}

class _SettingsSection extends StatelessWidget {
  const _SettingsSection({
    required this.title,
    required this.children,
  });

  final String title;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 8),
            ...children,
          ],
        ),
      ),
    );
  }
}

class _SettingsRow extends StatelessWidget {
  const _SettingsRow({
    required this.label,
    required this.value,
  });

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 96,
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
            ),
          ),
          Expanded(child: Text(value)),
        ],
      ),
    );
  }
}
