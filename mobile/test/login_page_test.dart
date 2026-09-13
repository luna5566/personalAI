import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/auth/models/auth_config.dart';
import 'package:personal_ai_mobile/features/auth/providers/auth_provider.dart';
import 'package:personal_ai_mobile/features/auth/ui/login_page.dart';

void main() {
  setUp(() {
    FakeLoginController.lastEmail = null;
    FakeLoginController.lastPassword = null;
  });

  testWidgets('keeps shipped credentials empty and trims login email',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeLoginController.new),
          authConfigProvider.overrideWith(
            (ref) async => const AuthConfig(registrationEnabled: true),
          ),
        ],
        child: const MaterialApp(home: LoginPage()),
      ),
    );
    await tester.pumpAndSettle();

    final emailField = tester.widget<TextField>(
      find.widgetWithText(TextField, '邮箱'),
    );
    final passwordField = tester.widget<TextField>(
      find.widgetWithText(TextField, '密码'),
    );
    expect(emailField.controller?.text, isEmpty);
    expect(passwordField.controller?.text, isEmpty);
    expect(find.text('创建新账号'), findsOneWidget);

    await tester.enterText(
      find.widgetWithText(TextField, '邮箱'),
      '  user@example.com  ',
    );
    await tester.enterText(
      find.widgetWithText(TextField, '密码'),
      'secret-password',
    );
    await tester.tap(find.widgetWithText(FilledButton, '登录'));
    await tester.pump();

    expect(FakeLoginController.lastEmail, 'user@example.com');
    expect(FakeLoginController.lastPassword, 'secret-password');
  });

  testWidgets('hides registration entry when registration is disabled',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeLoginController.new),
          authConfigProvider.overrideWith(
            (ref) async => const AuthConfig(registrationEnabled: false),
          ),
        ],
        child: const MaterialApp(home: LoginPage()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('登录'), findsWidgets);
    expect(find.text('创建新账号'), findsNothing);
  });

  testWidgets('keeps login usable when registration policy cannot load',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(FakeLoginController.new),
          authConfigProvider.overrideWith(
            (ref) async => throw StateError('offline'),
          ),
        ],
        child: const MaterialApp(home: LoginPage()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.widgetWithText(FilledButton, '登录'), findsOneWidget);
    expect(find.text('创建新账号'), findsNothing);
  });
}

class FakeLoginController extends AuthController {

  static String? lastEmail;
  static String? lastPassword;

  @override
  Future<void> loadCurrentUser() async {
    state = const AuthState();
  }

  @override
  Future<void> login(String email, String password) async {
    lastEmail = email;
    lastPassword = password;
  }
}
