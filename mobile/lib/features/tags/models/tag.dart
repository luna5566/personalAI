class KnowledgeTag {
  const KnowledgeTag({
    required this.id,
    required this.name,
    this.color,
  });

  final String id;
  final String name;
  final String? color;

  factory KnowledgeTag.fromJson(Map<String, dynamic> json) {
    return KnowledgeTag(
      id: json['id'] as String,
      name: json['name'] as String,
      color: json['color'] as String?,
    );
  }
}
