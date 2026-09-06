import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:personal_ai_mobile/features/jobs/data/jobs_api.dart';
import 'package:personal_ai_mobile/features/jobs/models/job.dart';
import 'package:personal_ai_mobile/features/jobs/providers/jobs_provider.dart';
import 'package:personal_ai_mobile/features/settings/data/settings_api.dart';
import 'package:personal_ai_mobile/features/settings/models/runtime_settings.dart';
import 'package:personal_ai_mobile/features/settings/providers/settings_provider.dart';
import 'package:personal_ai_mobile/features/settings/ui/model_settings_page.dart';

void main() {
  setUp(() {
    FakeSettingsApi.reset();
    FakeJobsApi.reset();
  });

  testWidgets('renders runtime model settings', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          runtimeSettingsProvider.overrideWith(
            (ref) async => const RuntimeSettings(
              appEnv: 'local',
              llmProvider: 'local_extractive',
              llmModel: null,
              llmBaseUrl: null,
              llmBaseUrlConfigured: false,
              llmApiKeyConfigured: false,
              embeddingProvider: 'local_hash',
              embeddingBaseUrl: null,
              embeddingModel: 'local_hash:1536',
              embeddingDimensions: 1536,
              embeddingBaseUrlConfigured: false,
              embeddingApiKeyConfigured: false,
              storageBackend: 'local',
              ocrProvider: 'disabled',
              speechToTextProvider: 'disabled',
            ),
          ),
        ],
        child: const MaterialApp(home: ModelSettingsPage()),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('模型设置'), findsOneWidget);
    expect(find.text('local_extractive'), findsOneWidget);
    expect(find.byKey(const ValueKey('save-model-settings')), findsOneWidget);
  });

  testWidgets('submits edited runtime model settings', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          runtimeSettingsProvider.overrideWith(
            (ref) async => const RuntimeSettings(
              appEnv: 'local',
              llmProvider: 'local_extractive',
              llmModel: null,
              llmBaseUrl: null,
              llmBaseUrlConfigured: false,
              llmApiKeyConfigured: false,
              embeddingProvider: 'local_hash',
              embeddingBaseUrl: null,
              embeddingModel: 'text-embedding-3-small',
              embeddingDimensions: 1536,
              embeddingBaseUrlConfigured: false,
              embeddingApiKeyConfigured: false,
              storageBackend: 'local',
              ocrProvider: 'disabled',
              speechToTextProvider: 'disabled',
            ),
          ),
          settingsApiProvider.overrideWithValue(FakeSettingsApi()),
          jobsApiProvider.overrideWithValue(FakeJobsApi()),
        ],
        child: const MaterialApp(home: ModelSettingsPage()),
      ),
    );

    await tester.pumpAndSettle();
    await tester.enterText(
        find.widgetWithText(TextFormField, '模型').first, 'gpt-4.1-mini');
    await tester.enterText(
        find.widgetWithText(TextFormField, '新 API Key').first, 'sk-test');
    final saveButton = find.byKey(const ValueKey('save-model-settings'));
    await tester.ensureVisible(saveButton);
    await tester.pumpAndSettle();
    await tester.tap(saveButton);
    await tester.pumpAndSettle();

    expect(FakeSettingsApi.lastLlmProvider, 'local_extractive');
    expect(FakeSettingsApi.lastLlmModel, 'gpt-4.1-mini');
    expect(FakeSettingsApi.lastLlmApiKey, 'sk-test');
    expect(FakeJobsApi.rebuildAllStarted, isFalse);
    expect(find.text('模型配置已保存'), findsOneWidget);
  });

  testWidgets('opens rebuild job returned by settings update', (tester) async {
    FakeSettingsApi.nextRebuildJobId = 'global-rebuild-job-id';
    final router = GoRouter(
      initialLocation: '/settings',
      routes: [
        GoRoute(
          path: '/settings',
          builder: (context, state) => const ModelSettingsPage(),
        ),
        GoRoute(
          path: '/app/jobs/:id',
          builder: (context, state) => Scaffold(
            body: Text('job:${state.pathParameters['id']}'),
          ),
        ),
      ],
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          runtimeSettingsProvider.overrideWith(
            (ref) async => const RuntimeSettings(
              appEnv: 'local',
              llmProvider: 'local_extractive',
              llmModel: null,
              llmBaseUrl: null,
              llmBaseUrlConfigured: false,
              llmApiKeyConfigured: false,
              embeddingProvider: 'local_hash',
              embeddingBaseUrl: null,
              embeddingModel: 'local_hash:1536',
              embeddingDimensions: 1536,
              embeddingBaseUrlConfigured: false,
              embeddingApiKeyConfigured: false,
              storageBackend: 'local',
              ocrProvider: 'disabled',
              speechToTextProvider: 'disabled',
            ),
          ),
          settingsApiProvider.overrideWithValue(FakeSettingsApi()),
          jobsApiProvider.overrideWithValue(FakeJobsApi()),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pumpAndSettle();
    final embeddingModel = find.byKey(
      const ValueKey('embedding-model-field'),
    );
    await tester.scrollUntilVisible(
      embeddingModel,
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.enterText(
      embeddingModel,
      'text-embedding-3-small',
    );
    final saveButton = find.byKey(const ValueKey('save-model-settings'));
    await tester.scrollUntilVisible(
      saveButton,
      -300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(saveButton);
    await tester.pumpAndSettle();

    expect(FakeJobsApi.rebuildAllStarted, isFalse);
    expect(find.text('job:global-rebuild-job-id'), findsOneWidget);
  });

  testWidgets('starts embedding rebuild job', (tester) async {
    final router = GoRouter(
      initialLocation: '/settings',
      routes: [
        GoRoute(
          path: '/settings',
          builder: (context, state) => const ModelSettingsPage(),
        ),
        GoRoute(
          path: '/app/jobs/:id',
          builder: (context, state) => Scaffold(
            body: Text('job:${state.pathParameters['id']}'),
          ),
        ),
      ],
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          runtimeSettingsProvider.overrideWith(
            (ref) async => const RuntimeSettings(
              appEnv: 'local',
              llmProvider: 'local_extractive',
              llmModel: null,
              llmBaseUrl: null,
              llmBaseUrlConfigured: false,
              llmApiKeyConfigured: false,
              embeddingProvider: 'local_hash',
              embeddingBaseUrl: null,
              embeddingModel: 'text-embedding-3-small',
              embeddingDimensions: 1536,
              embeddingBaseUrlConfigured: false,
              embeddingApiKeyConfigured: false,
              storageBackend: 'local',
              ocrProvider: 'disabled',
              speechToTextProvider: 'disabled',
            ),
          ),
          jobsApiProvider.overrideWithValue(FakeJobsApi()),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );

    await tester.pumpAndSettle();
    await tester.tap(find.text('重建全部资料索引'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('开始重建'));
    await tester.pumpAndSettle();

    expect(FakeJobsApi.rebuildAllStarted, isTrue);
    expect(find.text('job:rebuild-job-id'), findsOneWidget);
  });
}

class FakeSettingsApi extends SettingsApi {
  FakeSettingsApi() : super(Dio());

  static String? lastLlmProvider;
  static String? lastLlmModel;
  static String? lastLlmApiKey;
  static String? nextRebuildJobId;

  static void reset() {
    lastLlmProvider = null;
    lastLlmModel = null;
    lastLlmApiKey = null;
    nextRebuildJobId = null;
  }

  @override
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
    lastLlmProvider = llmProvider;
    lastLlmModel = llmModel;
    lastLlmApiKey = llmApiKey;
    return RuntimeSettingsUpdateResult(
      rebuildJobId: nextRebuildJobId,
      settings: RuntimeSettings(
        appEnv: 'local',
        llmProvider: llmProvider,
        llmModel: llmModel,
        llmBaseUrl: llmBaseUrl,
        llmBaseUrlConfigured: llmBaseUrl != null,
        llmApiKeyConfigured: llmApiKey != null,
        embeddingProvider: embeddingProvider,
        embeddingBaseUrl: embeddingBaseUrl,
        embeddingModel: embeddingModel,
        embeddingDimensions: embeddingDimensions,
        embeddingBaseUrlConfigured: embeddingBaseUrl != null,
        embeddingApiKeyConfigured: embeddingApiKey != null,
        storageBackend: 'local',
        ocrProvider: ocrProvider,
        ocrBaseUrl: ocrBaseUrl,
        ocrModel: ocrModel,
        ocrBaseUrlConfigured: ocrBaseUrl != null,
        ocrApiKeyConfigured: ocrApiKey != null,
        speechToTextProvider: speechToTextProvider,
        speechToTextBaseUrl: speechToTextBaseUrl,
        speechToTextModel: speechToTextModel,
        speechToTextBaseUrlConfigured: speechToTextBaseUrl != null,
        speechToTextApiKeyConfigured: speechToTextApiKey != null,
      ),
    );
  }
}

class FakeJobsApi extends JobsApi {
  FakeJobsApi() : super(Dio());

  static bool rebuildAllStarted = false;

  static void reset() {
    rebuildAllStarted = false;
  }

  @override
  Future<IndexJob> rebuildAllEmbeddings() async {
    rebuildAllStarted = true;
    return const IndexJob(
      id: 'rebuild-job-id',
      jobType: 'rebuild_all_embeddings',
      status: 'pending',
      progress: 0,
    );
  }
}
