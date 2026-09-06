import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/registration_invites_api.dart';
import '../models/registration_invite.dart';

final registrationInvitesApiProvider = Provider<RegistrationInvitesApi>((ref) {
  return RegistrationInvitesApi(ref.watch(dioProvider));
});

typedef RegistrationInviteQuery = ({int page, String? status});

final registrationInvitesPageProvider = FutureProvider.autoDispose
    .family<RegistrationInvitePage, RegistrationInviteQuery>((ref, query) {
  return ref.watch(registrationInvitesApiProvider).list(
        page: query.page,
        status: query.status,
      );
});
