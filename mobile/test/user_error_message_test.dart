import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/core/network/user_error_message.dart';

void main() {
  test('uses a stable API message from a JSON response', () {
    final options = RequestOptions(path: '/documents');
    final error = DioException(
      requestOptions: options,
      response: Response<Map<String, dynamic>>(
        requestOptions: options,
        statusCode: 409,
        data: {'message': '  资料仍在处理中  '},
      ),
    );

    expect(userFacingErrorMessage(error), '资料仍在处理中');
  });

  test('uses detail when a response has no message field', () {
    final options = RequestOptions(path: '/auth/register');
    final error = DioException(
      requestOptions: options,
      response: Response<Map<String, dynamic>>(
        requestOptions: options,
        statusCode: 403,
        data: {'detail': '当前不开放新账号注册'},
      ),
    );

    expect(userFacingErrorMessage(error), '当前不开放新账号注册');
  });

  test('hides transport and unknown exception details', () {
    final transportError = DioException(
      requestOptions: RequestOptions(path: '/documents'),
      type: DioExceptionType.connectionError,
      message: 'XMLHttpRequest onError callback was called',
    );

    expect(
      userFacingErrorMessage(
        transportError,
        fallback: '暂时无法加载资料',
      ),
      '暂时无法加载资料',
    );
    expect(
      userFacingErrorMessage(
        StateError('database credentials leaked'),
        fallback: '保存失败，请稍后重试',
      ),
      '保存失败，请稍后重试',
    );
  });

  test('ignores blank and non-string API error fields', () {
    final options = RequestOptions(path: '/documents');
    final error = DioException(
      requestOptions: options,
      response: Response<Map<String, dynamic>>(
        requestOptions: options,
        statusCode: 422,
        data: {
          'message': '   ',
          'detail': [
            {
              'loc': ['body', 'title']
            },
          ],
        },
      ),
    );

    expect(
      userFacingErrorMessage(error, fallback: '请求内容无效'),
      '请求内容无效',
    );
  });
}
