import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/organize_api.dart';

final organizeApiProvider =
    Provider<OrganizeApi>((ref) => OrganizeApi(ref.watch(dioProvider)));

final organizeControllerProvider =
    StateNotifierProvider<OrganizeController, AsyncValue<OrganizeResult?>>(
  (ref) => OrganizeController(ref),
);

class OrganizeController extends StateNotifier<AsyncValue<OrganizeResult?>> {
  OrganizeController(this._ref) : super(const AsyncData(null));

  final Ref _ref;

  Future<void> organizeCollection({
    required String mode,
    String? tag,
    List<String> documentIds = const [],
    required bool saveAsNote,
  }) async {
    state = const AsyncLoading();
    state = await AsyncValue.guard(
      () => _ref.read(organizeApiProvider).organizeCollection(
            mode: mode,
            tag: tag,
            documentIds: documentIds,
            saveAsNote: saveAsNote,
          ),
    );
  }
}
