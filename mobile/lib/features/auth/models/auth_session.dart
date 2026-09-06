class AuthSessionInfo {
  const AuthSessionInfo({
    required this.id,
    required this.createdAt,
    required this.expiresAt,
    required this.isCurrent,
    this.clientName,
  });

  final String id;
  final String? clientName;
  final DateTime createdAt;
  final DateTime expiresAt;
  final bool isCurrent;

  DateTime get createdAtLocal => createdAt.toLocal();
  DateTime get expiresAtLocal => expiresAt.toLocal();

  factory AuthSessionInfo.fromJson(Map<String, dynamic> json) {
    return AuthSessionInfo(
      id: json['id'] as String,
      clientName: json['client_name'] as String?,
      createdAt: DateTime.parse(json['created_at'] as String),
      expiresAt: DateTime.parse(json['expires_at'] as String),
      isCurrent: json['is_current'] as bool,
    );
  }
}
