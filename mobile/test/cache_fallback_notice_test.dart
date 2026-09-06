import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/app.dart';
import 'package:personal_ai_mobile/core/network/cache_recovery.dart';
import 'package:personal_ai_mobile/core/network/cache_state.dart';

void main() {
  testWidgets('shows and replaces cache fallback notices', (tester) async {
    tester.view.physicalSize = const Size(360, 640);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    FlutterSecureStorage.setMockInitialValues({});
    final recoveryController = FakeCacheRecoveryController();
    final container = ProviderContainer(
      overrides: [
        cacheRecoveryControllerProvider.overrideWith(
          (ref) => recoveryController,
        ),
      ],
    );
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const PersonalAiApp(),
      ),
    );
    await tester.pumpAndSettle();

    final now = DateTime.now();
    final sameDayCachedAt = DateTime(
      now.year,
      now.month,
      now.day,
      now.hour,
      now.minute,
    );
    container.read(cacheFallbackNoticeProvider.notifier).state =
        CacheFallbackNotice(
      reason: CacheFallbackReason.offline,
      cachedAt: sameDayCachedAt.toUtc(),
    );
    await tester.pumpAndSettle();

    expect(find.text('正在显示离线缓存'), findsOneWidget);
    expect(find.text('重新连接'), findsOneWidget);
    expect(
      find.text('缓存更新于 ${_time(sameDayCachedAt)}'),
      findsOneWidget,
    );
    expect(find.byType(MaterialBanner), findsOneWidget);

    final olderCachedAt = sameDayCachedAt.subtract(const Duration(days: 2));
    container.read(cacheFallbackNoticeProvider.notifier).state =
        CacheFallbackNotice(
      reason: CacheFallbackReason.serviceUnavailable,
      cachedAt: olderCachedAt.toUtc(),
      retryAfter: '5',
    );
    await tester.pumpAndSettle();

    expect(find.text('服务暂不可用，正在显示缓存'), findsOneWidget);
    expect(find.text('正在显示离线缓存'), findsNothing);
    expect(
      find.text('缓存更新于 ${_dateTime(olderCachedAt)}'),
      findsOneWidget,
    );
    expect(find.byType(MaterialBanner), findsOneWidget);
    final bannerRect = tester.getRect(find.byType(MaterialBanner));
    expect(bannerRect.left, greaterThanOrEqualTo(0));
    expect(bannerRect.right, lessThanOrEqualTo(360));
    expect(bannerRect.top, greaterThanOrEqualTo(0));
    expect(bannerRect.bottom, lessThanOrEqualTo(640));

    final refreshedCachedAt = olderCachedAt.add(const Duration(hours: 1));
    container.read(cacheFallbackNoticeProvider.notifier).state =
        CacheFallbackNotice(
      reason: CacheFallbackReason.serviceUnavailable,
      cachedAt: refreshedCachedAt.toUtc(),
      retryAfter: '6',
    );
    await tester.pumpAndSettle();

    expect(find.text('服务暂不可用，正在显示缓存'), findsOneWidget);
    expect(find.byType(MaterialBanner), findsOneWidget);
    expect(
      find.text('缓存更新于 ${_dateTime(refreshedCachedAt)}'),
      findsOneWidget,
    );
    expect(find.text('缓存更新于 ${_dateTime(olderCachedAt)}'), findsNothing);

    await tester.tap(find.text('重新连接'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(recoveryController.retryCount, 1);
    expect(find.text('连接中'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byType(MaterialBanner),
        matching: find.byType(CircularProgressIndicator),
      ),
      findsOneWidget,
    );

    recoveryController.complete();
    await tester.pumpAndSettle();

    expect(find.text('重新连接'), findsOneWidget);
    expect(find.byType(MaterialBanner), findsOneWidget);

    container.read(cacheFallbackNoticeProvider.notifier).state = null;
    await tester.pumpAndSettle();

    expect(find.byType(MaterialBanner), findsNothing);
    expect(find.text('服务暂不可用，正在显示缓存'), findsNothing);
  });
}

String _time(DateTime value) {
  return '${_twoDigits(value.hour)}:${_twoDigits(value.minute)}';
}

String _dateTime(DateTime value) {
  return '${_twoDigits(value.month)}-${_twoDigits(value.day)} ${_time(value)}';
}

String _twoDigits(int value) => value.toString().padLeft(2, '0');

class FakeCacheRecoveryController extends CacheRecoveryController {
  FakeCacheRecoveryController() : super(Dio(), () {});

  int retryCount = 0;
  Completer<void>? _pending;

  @override
  Future<void> retry() {
    final pending = _pending;
    if (pending != null) {
      return pending.future;
    }
    retryCount += 1;
    state = true;
    final completer = Completer<void>();
    _pending = completer;
    return completer.future.whenComplete(() {
      state = false;
      _pending = null;
    });
  }

  void complete() {
    _pending?.complete();
  }
}
