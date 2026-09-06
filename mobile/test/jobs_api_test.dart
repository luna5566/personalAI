import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/jobs/data/jobs_api.dart';

void main() {
  test('loads a filtered job page with timestamps', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = JobsAdapter();
    dio.httpClientAdapter = adapter;

    final page = await JobsApi(dio).listJobs(
      page: 2,
      pageSize: 10,
      status: 'failed',
      jobType: 'index_document',
    );

    expect(adapter.requestedPage, 2);
    expect(adapter.requestedPageSize, 10);
    expect(adapter.requestedStatus, 'failed');
    expect(adapter.requestedJobType, 'index_document');
    expect(page.total, 11);
    expect(page.hasPrevious, isTrue);
    expect(page.hasNext, isFalse);
    expect(page.items.single.errorMessage, 'provider unavailable');
    expect(page.items.single.retryOfJobId, 'original-job-id');
    expect(page.items.single.updatedAt, DateTime.utc(2026, 7, 17, 10, 5));
  });

  test('cancels and retries a job through dedicated endpoints', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://localhost/api'));
    final adapter = JobsAdapter();
    dio.httpClientAdapter = adapter;
    final api = JobsApi(dio);

    final cancelled = await api.cancelJob('job-id');
    final retry = await api.retryJob('job-id');

    expect(cancelled.status, 'cancel_requested');
    expect(retry.id, 'retry-job-id');
    expect(retry.retryOfJobId, 'job-id');
    expect(retry.status, 'pending');
    expect(adapter.operations, ['cancel', 'retry']);
  });
}

class JobsAdapter implements HttpClientAdapter {
  int? requestedPage;
  int? requestedPageSize;
  String? requestedStatus;
  String? requestedJobType;
  final List<String> operations = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    if (options.path == '/jobs/job-id/cancel') {
      operations.add('cancel');
      return _jobResponse(id: 'job-id', status: 'cancel_requested');
    }
    if (options.path == '/jobs/job-id/retry') {
      operations.add('retry');
      return _jobResponse(id: 'retry-job-id', status: 'pending');
    }
    expect(options.path, '/jobs');
    requestedPage = options.queryParameters['page'] as int;
    requestedPageSize = options.queryParameters['page_size'] as int;
    requestedStatus = options.queryParameters['status'] as String;
    requestedJobType = options.queryParameters['job_type'] as String;
    return ResponseBody.fromString(
      jsonEncode({
        'items': [
          {
            'id': 'job-id',
            'job_type': 'index_document',
            'status': 'failed',
            'progress': 100,
            'message': '处理失败',
            'error_message': 'provider unavailable',
            'retry_of_job_id': 'original-job-id',
            'created_at': '2026-07-17T10:00:00Z',
            'updated_at': '2026-07-17T10:05:00Z',
          },
        ],
        'total': 11,
        'page': 2,
        'page_size': 10,
      }),
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  ResponseBody _jobResponse({required String id, required String status}) {
    return ResponseBody.fromString(
      jsonEncode({
        'id': id,
        'job_type': 'index_document',
        'status': status,
        'progress': status == 'pending' ? 0 : 55,
        'retry_of_job_id': id == 'retry-job-id' ? 'job-id' : null,
      }),
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}
