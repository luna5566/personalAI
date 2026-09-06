import 'package:dio/dio.dart';

const defaultUserErrorMessage = '操作失败，请稍后重试';

String userFacingErrorMessage(
  Object error, {
  String fallback = defaultUserErrorMessage,
}) {
  if (error is DioException) {
    final responseMessage = _responseMessage(error.response?.data);
    if (responseMessage != null) {
      return responseMessage;
    }
  }
  return fallback;
}

String? _responseMessage(Object? data) {
  if (data is! Map) {
    return null;
  }
  for (final key in const ['message', 'detail']) {
    final value = data[key];
    if (value is String && value.trim().isNotEmpty) {
      return value.trim();
    }
  }
  return null;
}
