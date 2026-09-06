import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/network/cache_recovery.dart';
import 'core/network/cache_state.dart';
import 'core/router/app_router.dart';
import 'core/theme/app_theme.dart';

final _scaffoldMessengerKey = GlobalKey<ScaffoldMessengerState>();

typedef _CacheFallbackBannerState = ({
  CacheFallbackNotice? notice,
  bool recovering,
});

final _cacheFallbackBannerStateProvider =
    Provider<_CacheFallbackBannerState>((ref) {
  return (
    notice: ref.watch(cacheFallbackNoticeProvider),
    recovering: ref.watch(cacheRecoveryControllerProvider),
  );
});

class PersonalAiApp extends ConsumerWidget {
  const PersonalAiApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(appRouterProvider);
    ref.listen<_CacheFallbackBannerState>(_cacheFallbackBannerStateProvider,
        (_, bannerState) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final messenger = _scaffoldMessengerKey.currentState;
        if (messenger == null) {
          return;
        }
        messenger.removeCurrentMaterialBanner();
        final notice = bannerState.notice;
        if (notice != null) {
          messenger.showMaterialBanner(
            _cacheFallbackBanner(
              notice,
              recovering: bannerState.recovering,
              onRetry: ref.read(cacheRecoveryControllerProvider.notifier).retry,
            ),
          );
        }
      });
    });

    return MaterialApp.router(
      scaffoldMessengerKey: _scaffoldMessengerKey,
      title: '个人 AI 知识助手',
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      routerConfig: router,
    );
  }
}

MaterialBanner _cacheFallbackBanner(
  CacheFallbackNotice notice, {
  required bool recovering,
  required Future<void> Function() onRetry,
}) {
  final (icon, message) = switch (notice.reason) {
    CacheFallbackReason.offline => (
        Icons.wifi_off_outlined,
        '正在显示离线缓存',
      ),
    CacheFallbackReason.serviceUnavailable => (
        Icons.cloud_off_outlined,
        '服务暂不可用，正在显示缓存',
      ),
  };
  return MaterialBanner(
    leading: Icon(icon),
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
    leadingPadding: const EdgeInsets.only(right: 12),
    forceActionsBelow: true,
    minActionBarHeight: 44,
    content: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(message, style: const TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 2),
        Text(
          '缓存更新于 ${_formatCacheTime(notice.cachedAt)}',
          style: const TextStyle(fontSize: 12),
        ),
      ],
    ),
    actions: [
      SizedBox(
        width: 112,
        height: 40,
        child: TextButton.icon(
          onPressed: recovering ? null : onRetry,
          icon: SizedBox.square(
            dimension: 18,
            child: recovering
                ? const CircularProgressIndicator(strokeWidth: 2)
                : const Icon(Icons.refresh, size: 18),
          ),
          label: Text(recovering ? '连接中' : '重新连接'),
        ),
      ),
    ],
  );
}

String _formatCacheTime(DateTime cachedAt) {
  final localCachedAt = cachedAt.toLocal();
  final now = DateTime.now();
  final time = '${_twoDigits(localCachedAt.hour)}:'
      '${_twoDigits(localCachedAt.minute)}';
  final isToday = localCachedAt.year == now.year &&
      localCachedAt.month == now.month &&
      localCachedAt.day == now.day;
  if (isToday) {
    return time;
  }
  return '${_twoDigits(localCachedAt.month)}-'
      '${_twoDigits(localCachedAt.day)} $time';
}

String _twoDigits(int value) => value.toString().padLeft(2, '0');
