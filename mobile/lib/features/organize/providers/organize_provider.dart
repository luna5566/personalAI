import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/organize_api.dart';

final organizeApiProvider =
    Provider<OrganizeApi>((ref) => OrganizeApi(ref.watch(dioProvider)));

final organizeControllerProvider =
    NotifierProvider<OrganizeController, AsyncValue<OrganizeResult?>>(
  OrganizeController.new,
);

class OrganizeController extends Notifier<AsyncValue<OrganizeResult?>> {
  @override
  AsyncValue<OrganizeResult?> build() => const AsyncData(null);

  Future<void> organizeCollection({
    required String mode,
    String? tag,
    List<String> documentIds = const [],
    required bool saveAsNote,
  }) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(
      () => ref.read(organizeApiProvider).organizeCollection(
            mode: mode,
            tag: tag,
            documentIds: documentIds,
            saveAsNote: saveAsNote,
          ),
    );
  }
}
