import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/auth/models/auth_config.dart';
import 'package:personal_ai_mobile/features/auth/models/user.dart';
import 'package:personal_ai_mobile/features/auth/providers/auth_provider.dart';
import 'package:personal_ai_mobile/features/auth/ui/register_page.dart';

void main() {
  setUp(() {
    FakeAuthController.lastName = null;
    FakeAuthController.lastEmail = null;
    FakeAuthController.lastPassword = null;
    FakeAuthController.lastInviteCode = null;
  });

  testWidgets('validates password confirmation', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeAuthController.new),
          authConfigProvider.overrideWith(
            (ref) async => const AuthConfig(registrationEnabled: true),
          ),
        ],
        child: const MaterialApp(home: RegisterPage()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
        find.widgetWithText(TextField, '邮箱'), 'new@example.com');
    await tester.enterText(
        find.widgetWithText(TextField, '密码，至少 6 位'), '123456');
    await tester.enterText(find.widgetWithText(TextField, '确认密码'), '654321');
    await tester.tap(find.text('注册并进入'));
    await tester.pump();

    expect(find.text('两次输入的密码不一致'), findsOneWidget);
    expect(FakeAuthController.lastEmail, isNull);
  });

  testWidgets('submits registration values', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeAuthController.new),
          authConfigProvider.overrideWith(
            (ref) async => const AuthConfig(registrationEnabled: true),
          ),
        ],
        child: const MaterialApp(home: RegisterPage()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.widgetWithText(TextField, '昵称，可选'), '小明');
    await tester.enterText(
        find.widgetWithText(TextField, '邮箱'), 'new@example.com');
    await tester.enterText(
        find.widgetWithText(TextField, '密码，至少 6 位'), '123456');
    await tester.enterText(find.widgetWithText(TextField, '确认密码'), '123456');
    await tester.tap(find.text('注册并进入'));
    await tester.pump();

    expect(FakeAuthController.lastName, '小明');
    expect(FakeAuthController.lastEmail, 'new@example.com');
    expect(FakeAuthController.lastPassword, '123456');
  });

  testWidgets('blocks the registration form when registration is disabled',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeAuthController.new),
          authConfigProvider.overrideWith(
            (ref) async => const AuthConfig(registrationEnabled: false),
          ),
        ],
        child: const MaterialApp(home: RegisterPage()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('当前不开放新账号注册'), findsOneWidget);
    expect(find.text('注册并进入'), findsNothing);
    expect(find.text('返回登录'), findsOneWidget);
  });

  testWidgets('requires and submits an invitation code when configured',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeAuthController.new),
          authConfigProvider.overrideWith(
            (ref) async => const AuthConfig(
              registrationEnabled: true,
              invitationRequired: true,
            ),
          ),
        ],
        child: const MaterialApp(home: RegisterPage()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.widgetWithText(TextField, '邮箱'),
      'invitee@example.com',
    );
    await tester.enterText(
      find.widgetWithText(TextField, '密码，至少 6 位'),
      'secure-password',
    );
    await tester.enterText(
      find.widgetWithText(TextField, '确认密码'),
      'secure-password',
    );
    await tester.tap(find.text('注册并进入'));
    await tester.pump();

    expect(find.text('请输入邀请码'), findsOneWidget);
    expect(FakeAuthController.lastEmail, isNull);

    await tester.enterText(
      find.widgetWithText(TextField, '邀请码'),
      'one-time-code',
    );
    await tester.tap(find.text('注册并进入'));
    await tester.pump();

    expect(FakeAuthController.lastEmail, 'invitee@example.com');
    expect(FakeAuthController.lastInviteCode, 'one-time-code');
  });

  testWidgets('shows retry state when registration policy cannot load',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeAuthController.new),
          authConfigProvider.overrideWith(
            (ref) async => throw StateError('offline'),
          ),
        ],
        child: const MaterialApp(home: RegisterPage()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('无法确认是否开放注册'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);
    expect(find.text('返回登录'), findsOneWidget);
  });
}

class FakeAuthController extends AuthController {

  static String? lastName;
  static String? lastEmail;
  static String? lastPassword;
  static String? lastInviteCode;

  @override
  Future<void> loadCurrentUser() async {
    state = const AuthState();
  }

  @override
  Future<void> register({
    required String email,
    required String password,
    String? name,
    String? inviteCode,
  }) async {
    lastName = name;
    lastEmail = email;
    lastPassword = password;
    lastInviteCode = inviteCode;
    state = const AuthState(
      user: User(id: 'user-id', email: 'new@example.com', name: '小明'),
    );
  }
}
