import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/cache_state.dart';
import '../data/settings_api.dart';
import '../models/media_capabilities.dart';
import '../models/runtime_settings.dart';

final settingsApiProvider = Provider<SettingsApi>((ref) {
  ref.watch(cacheRevalidationProvider);
  return SettingsApi(ref.watch(dioProvider));
});

final runtimeSettingsProvider =
    FutureProvider.autoDispose<RuntimeSettings>((ref) {
  return ref.watch(settingsApiProvider).runtimeSettings();
});

/// Public media capability flags used before file uploads.
/// Falls back to disabled so the picker only offers text formats when unknown.
final mediaCapabilitiesProvider =
    FutureProvider.autoDispose<MediaCapabilities>((ref) async {
  try {
    return await ref.watch(settingsApiProvider).mediaCapabilities();
  } catch (_) {
    return MediaCapabilities.fallback;
  }
});
