import 'package:dio/dio.dart';

import '../models/job.dart';

class JobsApi {
  const JobsApi(this._dio);

  final Dio _dio;

  Future<JobPage> listJobs({
    int page = 1,
    int pageSize = 20,
    String? status,
    String? jobType,
  }) async {
    final response = await _dio.get<Map<String, dynamic>>(
      '/jobs',
      queryParameters: {
        'page': page,
        'page_size': pageSize,
        if (status != null && status.isNotEmpty) 'status': status,
        if (jobType != null && jobType.isNotEmpty) 'job_type': jobType,
      },
    );
    return JobPage.fromJson(response.data!);
  }

  Future<IndexJob> getJob(String id) async {
    final response = await _dio.get<Map<String, dynamic>>('/jobs/$id');
    return IndexJob.fromJson(response.data!);
  }

  Future<IndexJob> cancelJob(String id) async {
    final response = await _dio.post<Map<String, dynamic>>('/jobs/$id/cancel');
    return IndexJob.fromJson(response.data!);
  }

  Future<IndexJob> retryJob(String id) async {
    final response = await _dio.post<Map<String, dynamic>>('/jobs/$id/retry');
    return IndexJob.fromJson(response.data!);
  }

  Future<IndexJob> rebuildEmbeddings() async {
    final response =
        await _dio.post<Map<String, dynamic>>('/jobs/rebuild-embeddings');
    return IndexJob.fromJson(response.data!);
  }

  Future<IndexJob> rebuildAllEmbeddings() async {
    final response =
        await _dio.post<Map<String, dynamic>>('/jobs/rebuild-all-embeddings');
    return IndexJob.fromJson(response.data!);
  }
}

class JobPage {
  const JobPage({
    required this.items,
    required this.total,
    required this.page,
    required this.pageSize,
  });

  final List<IndexJob> items;
  final int total;
  final int page;
  final int pageSize;

  int get totalPages => total == 0 ? 1 : (total + pageSize - 1) ~/ pageSize;
  bool get hasPrevious => page > 1;
  bool get hasNext => page < totalPages;

  factory JobPage.fromJson(Map<String, dynamic> json) {
    final items = json['items'] as List<dynamic>;
    return JobPage(
      items: items
          .map((item) => IndexJob.fromJson(item as Map<String, dynamic>))
          .toList(),
      total: json['total'] as int,
      page: json['page'] as int,
      pageSize: json['page_size'] as int,
    );
  }
}
