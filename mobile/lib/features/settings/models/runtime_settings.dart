class RuntimeSettings {
  const RuntimeSettings({
    required this.appEnv,
    required this.llmProvider,
    this.llmBaseUrl,
    required this.llmBaseUrlConfigured,
    required this.llmApiKeyConfigured,
    required this.embeddingProvider,
    this.embeddingBaseUrl,
    required this.embeddingModel,
    required this.embeddingDimensions,
    required this.embeddingBaseUrlConfigured,
    required this.embeddingApiKeyConfigured,
    required this.storageBackend,
    required this.ocrProvider,
    required this.speechToTextProvider,
    this.ocrBaseUrl,
    this.ocrModel = 'gpt-4o-mini',
    this.ocrBaseUrlConfigured = false,
    this.ocrApiKeyConfigured = false,
    this.speechToTextBaseUrl,
    this.speechToTextModel = 'whisper-1',
    this.speechToTextBaseUrlConfigured = false,
    this.speechToTextApiKeyConfigured = false,
    this.llmModel,
  });

  final String appEnv;
  final String llmProvider;
  final String? llmModel;
  final String? llmBaseUrl;
  final bool llmBaseUrlConfigured;
  final bool llmApiKeyConfigured;
  final String embeddingProvider;
  final String? embeddingBaseUrl;
  final String embeddingModel;
  final int embeddingDimensions;
  final bool embeddingBaseUrlConfigured;
  final bool embeddingApiKeyConfigured;
  final String storageBackend;
  final String ocrProvider;
  final String? ocrBaseUrl;
  final String ocrModel;
  final bool ocrBaseUrlConfigured;
  final bool ocrApiKeyConfigured;
  final String speechToTextProvider;
  final String? speechToTextBaseUrl;
  final String speechToTextModel;
  final bool speechToTextBaseUrlConfigured;
  final bool speechToTextApiKeyConfigured;

  factory RuntimeSettings.fromJson(Map<String, dynamic> json) {
    return RuntimeSettings(
      appEnv: json['app_env'] as String,
      llmProvider: json['llm_provider'] as String,
      llmModel: json['llm_model'] as String?,
      llmBaseUrl: json['llm_base_url'] as String?,
      llmBaseUrlConfigured: json['llm_base_url_configured'] as bool,
      llmApiKeyConfigured: json['llm_api_key_configured'] as bool,
      embeddingProvider: json['embedding_provider'] as String,
      embeddingBaseUrl: json['embedding_base_url'] as String?,
      embeddingModel: json['embedding_model'] as String,
      embeddingDimensions: json['embedding_dimensions'] as int,
      embeddingBaseUrlConfigured: json['embedding_base_url_configured'] as bool,
      embeddingApiKeyConfigured: json['embedding_api_key_configured'] as bool,
      storageBackend: json['storage_backend'] as String? ?? 'local',
      ocrProvider: json['ocr_provider'] as String? ?? 'disabled',
      ocrBaseUrl: json['ocr_base_url'] as String?,
      ocrModel: json['ocr_model'] as String? ?? 'gpt-4o-mini',
      ocrBaseUrlConfigured: json['ocr_base_url_configured'] as bool? ?? false,
      ocrApiKeyConfigured: json['ocr_api_key_configured'] as bool? ?? false,
      speechToTextProvider:
          json['speech_to_text_provider'] as String? ?? 'disabled',
      speechToTextBaseUrl: json['speech_to_text_base_url'] as String?,
      speechToTextModel: json['speech_to_text_model'] as String? ?? 'whisper-1',
      speechToTextBaseUrlConfigured:
          json['speech_to_text_base_url_configured'] as bool? ?? false,
      speechToTextApiKeyConfigured:
          json['speech_to_text_api_key_configured'] as bool? ?? false,
    );
  }
}
