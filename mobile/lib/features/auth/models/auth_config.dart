class AuthConfig {
  const AuthConfig({
    required this.registrationEnabled,
    this.invitationRequired = false,
  });

  final bool registrationEnabled;
  final bool invitationRequired;

  factory AuthConfig.fromJson(Map<String, dynamic> json) {
    return AuthConfig(
      registrationEnabled: json['registration_enabled'] as bool,
      invitationRequired: json['invitation_required'] as bool,
    );
  }
}
