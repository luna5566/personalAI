class User {
  const User({
    required this.id,
    required this.email,
    this.name,
    this.isAdmin = false,
  });

  final String id;
  final String email;
  final String? name;
  final bool isAdmin;

  factory User.fromJson(Map<String, dynamic> json) {
    return User(
      id: json['id'] as String,
      email: json['email'] as String,
      name: json['name'] as String?,
      isAdmin: json['is_admin'] as bool? ?? false,
    );
  }
}
