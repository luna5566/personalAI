import 'package:dio/dio.dart';

import '../models/registration_invite.dart';

class RegistrationInvitesApi {
  const RegistrationInvitesApi(this._dio);

  final Dio _dio;

  Future<RegistrationInvitePage> list({
    int page = 1,
    int pageSize = 20,
    String? status,
  }) async {
    final response = await _dio.get<Map<String, dynamic>>(
      '/auth/registration-invites',
      queryParameters: {
        'page': page,
        'page_size': pageSize,
        if (status != null && status.isNotEmpty) 'status': status,
      },
    );
    return RegistrationInvitePage.fromJson(response.data!);
  }

  Future<CreatedRegistrationInvite> create({required int validHours}) async {
    final response = await _dio.post<Map<String, dynamic>>(
      '/auth/registration-invites',
      data: {'valid_hours': validHours},
    );
    return CreatedRegistrationInvite.fromJson(response.data!);
  }

  Future<void> revoke(String id) async {
    await _dio.delete<void>('/auth/registration-invites/$id');
  }
}
