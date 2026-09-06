class RegistrationInviteInfo {
  const RegistrationInviteInfo({
    required this.id,
    required this.status,
    required this.createdAt,
    required this.expiresAt,
    this.usedAt,
    this.revokedAt,
  });

  final String id;
  final String status;
  final DateTime createdAt;
  final DateTime expiresAt;
  final DateTime? usedAt;
  final DateTime? revokedAt;

  bool get canRevoke => status == 'active';

  factory RegistrationInviteInfo.fromJson(Map<String, dynamic> json) {
    return RegistrationInviteInfo(
      id: json['id'] as String,
      status: json['status'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
      expiresAt: DateTime.parse(json['expires_at'] as String),
      usedAt: _optionalDateTime(json['used_at']),
      revokedAt: _optionalDateTime(json['revoked_at']),
    );
  }

  static DateTime? _optionalDateTime(dynamic value) {
    return value is String ? DateTime.parse(value) : null;
  }
}

class RegistrationInvitePage {
  const RegistrationInvitePage({
    required this.items,
    required this.total,
    required this.page,
    required this.pageSize,
  });

  final List<RegistrationInviteInfo> items;
  final int total;
  final int page;
  final int pageSize;

  int get totalPages => total == 0 ? 1 : (total + pageSize - 1) ~/ pageSize;
  bool get hasPrevious => page > 1;
  bool get hasNext => page < totalPages;

  factory RegistrationInvitePage.fromJson(Map<String, dynamic> json) {
    return RegistrationInvitePage(
      items: (json['items'] as List<dynamic>)
          .map(
            (item) => RegistrationInviteInfo.fromJson(
              item as Map<String, dynamic>,
            ),
          )
          .toList(),
      total: json['total'] as int,
      page: json['page'] as int,
      pageSize: json['page_size'] as int,
    );
  }
}

class CreatedRegistrationInvite {
  const CreatedRegistrationInvite({
    required this.code,
    required this.invite,
  });

  final String code;
  final RegistrationInviteInfo invite;

  factory CreatedRegistrationInvite.fromJson(Map<String, dynamic> json) {
    return CreatedRegistrationInvite(
      code: json['code'] as String,
      invite: RegistrationInviteInfo.fromJson(json),
    );
  }
}
