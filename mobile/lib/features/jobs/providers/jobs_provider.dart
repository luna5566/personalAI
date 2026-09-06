import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/api_client.dart';
import '../data/jobs_api.dart';
import '../models/job.dart';

final jobsApiProvider =
    Provider<JobsApi>((ref) => JobsApi(ref.watch(dioProvider)));

final jobProvider =
    FutureProvider.autoDispose.family<IndexJob, String>((ref, id) {
  return ref.watch(jobsApiProvider).getJob(id);
});

typedef JobsPageQuery = ({int page, String? status});

final jobsPageProvider =
    FutureProvider.autoDispose.family<JobPage, JobsPageQuery>((ref, query) {
  return ref.watch(jobsApiProvider).listJobs(
        page: query.page,
        status: query.status,
      );
});
