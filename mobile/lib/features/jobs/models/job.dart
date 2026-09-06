class IndexJob {
  const IndexJob({
    required this.id,
    required this.jobType,
    required this.status,
    required this.progress,
    this.documentId,
    this.retryOfJobId,
    this.message,
    this.errorMessage,
    this.createdAt,
    this.updatedAt,
  });

  final String id;
  final String jobType;
  final String status;
  final int progress;
  final String? documentId;
  final String? retryOfJobId;
  final String? message;
  final String? errorMessage;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  bool get isFinished =>
      status == 'success' || status == 'failed' || status == 'cancelled';

  bool get canCancel => status == 'pending' || status == 'running';

  bool get canRetry => status == 'failed' || status == 'cancelled';

  factory IndexJob.fromJson(Map<String, dynamic> json) {
    return IndexJob(
      id: json['id'] as String,
      jobType: json['job_type'] as String,
      status: json['status'] as String,
      progress: json['progress'] as int? ?? 0,
      documentId: json['document_id'] as String?,
      retryOfJobId: json['retry_of_job_id'] as String?,
      message: json['message'] as String?,
      errorMessage: json['error_message'] as String?,
      createdAt: json['created_at'] == null
          ? null
          : DateTime.parse(json['created_at'] as String),
      updatedAt: json['updated_at'] == null
          ? null
          : DateTime.parse(json['updated_at'] as String),
    );
  }
}
