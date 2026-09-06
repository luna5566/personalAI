import 'package:dio/dio.dart';

import '../models/media_capabilities.dart';
import '../models/runtime_settings.dart';

class RuntimeSettingsUpdateResult {
  const RuntimeSettingsUpdateResult({
    required this.settings,
    this.rebuildJobId,
  });

  final RuntimeSettings settings;
  final String? rebuildJobId;
}

class SettingsApi {
  const SettingsApi(this._dio);

  final Dio _dio;

  Future<MediaCapabilities> mediaCapabilities() async {
    final response =
        await _dio.get<Map<String, dynamic>>('/health/capabilities');
    return MediaCapabilities.fromJson(response.data ?? const {});
  }

  Future<RuntimeSettings> runtimeSettings() async {
    final response = await _dio.get<Map<String, dynamic>>('/settings/runtime');
    return RuntimeSettings.fromJson(response.data!);
  }

  Future<RuntimeSettingsUpdateResult> updateRuntimeSettings({
    required String llmProvider,
    String? llmBaseUrl,
    String? llmModel,
    String? llmApiKey,
    bool clearLlmApiKey = false,
    required String embeddingProvider,
    String? embeddingBaseUrl,
    required String embeddingModel,
    required int embeddingDimensions,
    String? embeddingApiKey,
    bool clearEmbeddingApiKey = false,
    required String ocrProvider,
    String? ocrBaseUrl,
    required String ocrModel,
    String? ocrApiKey,
    bool clearOcrApiKey = false,
    required String speechToTextProvider,
    String? speechToTextBaseUrl,
    required String speechToTextModel,
    String? speechToTextApiKey,
    bool clearSpeechToTextApiKey = false,
  }) async {
    final response = await _dio.patch<Map<String, dynamic>>(
      '/settings/runtime',
      data: {
        'llm_provider': llmProvider,
        'llm_base_url': llmBaseUrl,
        'llm_model': llmModel,
        if (llmApiKey != null && llmApiKey.trim().isNotEmpty)
          'llm_api_key': llmApiKey.trim(),
        'clear_llm_api_key': clearLlmApiKey,
        'embedding_provider': embeddingProvider,
        'embedding_base_url': embeddingBaseUrl,
        'embedding_model': embeddingModel,
        'embedding_dimensions': embeddingDimensions,
        if (embeddingApiKey != null && embeddingApiKey.trim().isNotEmpty)
          'embedding_api_key': embeddingApiKey.trim(),
        'clear_embedding_api_key': clearEmbeddingApiKey,
        'ocr_provider': ocrProvider,
        'ocr_base_url': ocrBaseUrl,
        'ocr_model': ocrModel,
        if (ocrApiKey != null && ocrApiKey.trim().isNotEmpty)
          'ocr_api_key': ocrApiKey.trim(),
        'clear_ocr_api_key': clearOcrApiKey,
        'speech_to_text_provider': speechToTextProvider,
        'speech_to_text_base_url': speechToTextBaseUrl,
        'speech_to_text_model': speechToTextModel,
        if (speechToTextApiKey != null && speechToTextApiKey.trim().isNotEmpty)
          'speech_to_text_api_key': speechToTextApiKey.trim(),
        'clear_speech_to_text_api_key': clearSpeechToTextApiKey,
      },
    );
    return RuntimeSettingsUpdateResult(
      settings: RuntimeSettings.fromJson(response.data!),
      rebuildJobId: response.headers.value('x-embedding-rebuild-job-id'),
    );
  }
}
