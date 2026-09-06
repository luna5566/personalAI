import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/auth/data/auth_api.dart';
import 'package:personal_ai_mobile/features/auth/models/auth_session.dart';
import 'package:personal_ai_mobile/features/auth/models/user.dart';
import 'package:personal_ai_mobile/features/auth/providers/auth_provider.dart';
import 'package:personal_ai_mobile/features/documents/models/document.dart';
import 'package:personal_ai_mobile/features/documents/providers/documents_provider.dart';
import 'package:personal_ai_mobile/features/me/ui/me_page.dart';

void main() {
  testWidgets('shows complete document statistics', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeAuthController.new),
          documentStatsProvider.overrideWith(
            (ref) async => const DocumentStats(
              total: 42,
              indexed: 30,
              processing: 8,
              failed: 4,
              cancelled: 2,
              storageBytes: 12 * 1024 * 1024,
            ),
          ),
        ],
        child: const MaterialApp(home: MePage()),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.text('资料 42'), findsOneWidget);
    expect(find.text('已索引 30'), findsOneWidget);
    expect(find.text('处理中 8'), findsOneWidget);
    expect(find.text('失败 4'), findsOneWidget);
    expect(find.text('已取消 2'), findsOneWidget);
    expect(find.text('文件空间 12 MB'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('清除本机数据'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('清除本机数据'), findsOneWidget);
    expect(find.text('任务历史'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('退出所有设备'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('修改密码'), findsOneWidget);
    expect(find.text('登录设备'), findsOneWidget);
    expect(find.text('退出所有设备'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('删除账号'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('删除账号'), findsOneWidget);
  });

  testWidgets('hides statistics errors and retries the request',
      (tester) async {
    var attempts = 0;
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeAuthController.new),
          documentStatsProvider.overrideWith((ref) async {
            attempts += 1;
            if (attempts == 1) {
              throw StateError('internal transport details');
            }
            return _emptyStats;
          }),
        ],
        child: const MaterialApp(home: MePage()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('暂时无法加载资料统计'), findsOneWidget);
    expect(find.textContaining('internal transport details'), findsNothing);
    expect(find.byTooltip('重新加载资料统计'), findsOneWidget);

    await tester.tap(find.byTooltip('重新加载资料统计'));
    await tester.pumpAndSettle();

    expect(attempts, 2);
    expect(find.text('暂时无法加载资料统计'), findsNothing);
    expect(find.text('资料 0'), findsOneWidget);
  });

  testWidgets('shows current session and revokes another session',
      (tester) async {
    final authApi = FakeSessionsApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeAuthController.new),
          authApiProvider.overrideWithValue(authApi),
          documentStatsProvider.overrideWith(
            (ref) async => _emptyStats,
          ),
        ],
        child: const MaterialApp(home: MePage()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('登录设备'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('登录设备'));
    await tester.pumpAndSettle();

    expect(find.text('Personal AI Web'), findsOneWidget);
    expect(find.text('Personal AI Android'), findsOneWidget);
    expect(find.text('当前设备'), findsOneWidget);
    expect(find.byTooltip('退出此设备'), findsOneWidget);

    await tester.tap(find.byTooltip('退出此设备'));
    await tester.pumpAndSettle();

    expect(authApi.revokedSessionIds, ['other-session']);
    expect(authApi.sessionListCalls, greaterThanOrEqualTo(2));
    expect(find.text('Personal AI Android'), findsNothing);
    expect(find.text('Personal AI Web'), findsOneWidget);
    expect(find.byTooltip('退出此设备'), findsNothing);
  });

  testWidgets('shows authentication session loading and error states',
      (tester) async {
    final authApi = ControlledSessionsApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeAuthController.new),
          authApiProvider.overrideWithValue(authApi),
          documentStatsProvider.overrideWith(
            (ref) async => _emptyStats,
          ),
        ],
        child: const MaterialApp(home: MePage()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('登录设备'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('登录设备'));
    await tester.pump();

    final dialog = find.byType(AlertDialog);
    expect(
      find.descendant(
        of: dialog,
        matching: find.byType(CircularProgressIndicator),
      ),
      findsOneWidget,
    );

    authApi.completeWithError();
    await tester.pumpAndSettle();

    expect(find.text('暂时无法加载登录设备'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);
  });

  testWidgets('validates password confirmation before changing password',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeAuthController.new),
          documentStatsProvider.overrideWith(
            (ref) async => const DocumentStats(
              total: 0,
              indexed: 0,
              processing: 0,
              failed: 0,
              cancelled: 0,
              storageBytes: 0,
            ),
          ),
        ],
        child: const MaterialApp(home: MePage()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('修改密码'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('修改密码'));
    await tester.pumpAndSettle();

    await tester.enterText(
      find.widgetWithText(TextField, '当前密码'),
      'current-password',
    );
    await tester.enterText(
      find.widgetWithText(TextField, '新密码，至少 6 位'),
      'new-password',
    );
    await tester.enterText(
      find.widgetWithText(TextField, '确认新密码'),
      'different-password',
    );
    await tester.tap(find.text('确认修改'));
    await tester.pump();

    expect(find.text('两次输入的新密码不一致'), findsOneWidget);
    expect(FakeAuthController.changePasswordCalls, 0);
  });

  testWidgets('shows registration invite management only to admins',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(AdminAuthController.new),
          documentStatsProvider.overrideWith((ref) async => _emptyStats),
        ],
        child: const MaterialApp(home: MePage()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('注册邀请码'),
      300,
      scrollable: find.byType(Scrollable).first,
    );

    expect(find.text('注册邀请码'), findsOneWidget);
    expect(find.text('创建和管理一次性邀请码'), findsOneWidget);
    await tester.scrollUntilVisible(
      find.text('退出登录'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('删除账号'), findsNothing);
  });

  testWidgets('requires password and confirmation before deleting account',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeAuthController.new),
          documentStatsProvider.overrideWith((ref) async => _emptyStats),
        ],
        child: const MaterialApp(home: MePage()),
      ),
    );
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('删除账号'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('删除账号'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('永久删除'));
    await tester.pump();
    expect(find.text('请输入当前密码'), findsOneWidget);
    expect(FakeAuthController.deleteAccountCalls, 0);

    await tester.enterText(
      find.widgetWithText(TextField, '当前密码'),
      'current-password',
    );
    await tester.tap(find.text('永久删除'));
    await tester.pump();
    expect(find.text('请确认永久删除账号和全部数据'), findsOneWidget);
    expect(FakeAuthController.deleteAccountCalls, 0);

    await tester.tap(find.byType(Checkbox));
    await tester.pump();
    await tester.tap(find.text('永久删除'));
    await tester.pumpAndSettle();

    expect(FakeAuthController.deleteAccountCalls, 1);
    expect(FakeAuthController.deletedPassword, 'current-password');
    expect(find.text('服务器拒绝删除'), findsOneWidget);
  });
}

const _emptyStats = DocumentStats(
  total: 0,
  indexed: 0,
  processing: 0,
  failed: 0,
  cancelled: 0,
  storageBytes: 0,
);

class FakeAuthController extends AuthController {
  FakeAuthController(super.ref);

  static int changePasswordCalls = 0;
  static int deleteAccountCalls = 0;
  static String? deletedPassword;

  @override
  Future<void> loadCurrentUser() async {
    changePasswordCalls = 0;
    deleteAccountCalls = 0;
    deletedPassword = null;
    state = const AuthState(
      user: User(
        id: 'user-id',
        email: 'user@example.com',
        name: '测试用户',
      ),
    );
  }

  @override
  Future<String?> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    changePasswordCalls += 1;
    return null;
  }

  @override
  Future<String?> deleteAccount({required String currentPassword}) async {
    deleteAccountCalls += 1;
    deletedPassword = currentPassword;
    return '服务器拒绝删除';
  }
}

class AdminAuthController extends FakeAuthController {
  AdminAuthController(super.ref);

  @override
  Future<void> loadCurrentUser() async {
    state = const AuthState(
      user: User(
        id: 'admin-id',
        email: 'admin@example.com',
        name: '管理员',
        isAdmin: true,
      ),
    );
  }
}

class FakeSessionsApi extends AuthApi {
  FakeSessionsApi() : super(Dio());

  int sessionListCalls = 0;
  final List<String> revokedSessionIds = [];
  final List<AuthSessionInfo> _sessions = [
    AuthSessionInfo(
      id: 'current-session',
      clientName: 'Personal AI Web',
      createdAt: DateTime.utc(2026, 7, 17, 12),
      expiresAt: DateTime.utc(2026, 7, 24, 12),
      isCurrent: true,
    ),
    AuthSessionInfo(
      id: 'other-session',
      clientName: 'Personal AI Android',
      createdAt: DateTime.utc(2026, 7, 17, 11),
      expiresAt: DateTime.utc(2026, 7, 24, 11),
      isCurrent: false,
    ),
  ];

  @override
  Future<List<AuthSessionInfo>> sessions() async {
    sessionListCalls += 1;
    return List.unmodifiable(_sessions);
  }

  @override
  Future<void> revokeSession(String id) async {
    revokedSessionIds.add(id);
    _sessions.removeWhere((session) => session.id == id);
  }
}

class ControlledSessionsApi extends AuthApi {
  ControlledSessionsApi() : super(Dio());

  final Completer<List<AuthSessionInfo>> _completer = Completer();

  @override
  Future<List<AuthSessionInfo>> sessions() => _completer.future;

  void completeWithError() {
    _completer.completeError(StateError('offline'));
  }
}
