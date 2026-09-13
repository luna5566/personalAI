import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/core/network/api_client.dart';
import 'package:personal_ai_mobile/core/network/cache_state.dart';
import 'package:personal_ai_mobile/features/auth/providers/auth_provider.dart';
import 'package:personal_ai_mobile/features/chat/providers/chat_provider.dart';
import 'package:personal_ai_mobile/features/documents/providers/documents_provider.dart';
import 'package:personal_ai_mobile/features/settings/providers/settings_provider.dart';
import 'package:personal_ai_mobile/features/tags/models/tag.dart';
import 'package:personal_ai_mobile/features/tags/providers/tags_provider.dart';

void main() {
  test('rebuilds every cache-backed API provider for a new generation', () {
    final dio = Dio();
    addTearDown(dio.close);
    final container = ProviderContainer(
      overrides: [dioProvider.overrideWithValue(dio)],
    );
    addTearDown(container.dispose);

    final documentsApi = container.read(documentsApiProvider);
    final tagsApi = container.read(tagsApiProvider);
    final chatApi = container.read(chatApiProvider);
    final settingsApi = container.read(settingsApiProvider);
    final authApi = container.read(authApiProvider);

    container.read(cacheRevalidationTrackerProvider.notifier).start();

    expect(container.read(documentsApiProvider), isNot(same(documentsApi)));
    expect(container.read(tagsApiProvider), isNot(same(tagsApi)));
    expect(container.read(chatApiProvider), isNot(same(chatApi)));
    expect(container.read(settingsApiProvider), isNot(same(settingsApi)));
    expect(container.read(authApiProvider), isNot(same(authApi)));
  });

  test('reloads active cache-backed data providers', () async {
    final adapter = TagsSequenceAdapter();
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    dio.httpClientAdapter = adapter;
    addTearDown(dio.close);
    final container = ProviderContainer(
      overrides: [dioProvider.overrideWithValue(dio)],
    );
    addTearDown(container.dispose);
    final subscription = container.listen<AsyncValue<List<KnowledgeTag>>>(
      tagsProvider,
      (_, _) {},
      fireImmediately: true,
    );
    addTearDown(subscription.close);

    await _waitForCalls(adapter, 1);
    expect(container.read(tagsProvider).requireValue.single.name, '缓存标签');

    container.read(cacheRevalidationTrackerProvider.notifier).start();
    await _waitForCalls(adapter, 2);

    expect(container.read(tagsProvider).requireValue.single.name, '实时标签');
  });
}

Future<void> _waitForCalls(TagsSequenceAdapter adapter, int count) async {
  for (var attempt = 0; attempt < 30; attempt += 1) {
    if (adapter.callCount >= count) {
      await Future<void>.delayed(Duration.zero);
      return;
    }
    await Future<void>.delayed(Duration.zero);
  }
  fail('Expected $count tag requests, received ${adapter.callCount}.');
}

class TagsSequenceAdapter implements HttpClientAdapter {
  int callCount = 0;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    expect(options.path, '/tags');
    expect(options.queryParameters['page'], 1);
    expect(options.queryParameters['page_size'], 100);
    callCount += 1;
    return ResponseBody.fromString(
      jsonEncode([
        {
          'id': 'tag-id',
          'name': callCount == 1 ? '缓存标签' : '实时标签',
          'color': null,
        },
      ]),
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
        'x-total-count': ['1'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}
