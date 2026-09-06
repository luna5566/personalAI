import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/app.dart';
import 'package:personal_ai_mobile/features/auth/models/auth_config.dart';
import 'package:personal_ai_mobile/features/auth/models/user.dart';
import 'package:personal_ai_mobile/features/auth/providers/auth_provider.dart';

void main() {
  testWidgets('preserves a deep link while authentication is loading',
      (tester) async {
    tester.binding.platformDispatcher.defaultRouteNameTestValue = '/app/me';
    addTearDown(
      tester.binding.platformDispatcher.clearDefaultRouteNameTestValue,
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(
            DelayedAuthenticatedController.new,
          ),
        ],
        child: const PersonalAiApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('deep-link@example.com'), findsOneWidget);
  });

  testWidgets('retries a startup auth error and preserves the deep link',
      (tester) async {
    tester.binding.platformDispatcher.defaultRouteNameTestValue = '/app/me';
    addTearDown(
      tester.binding.platformDispatcher.clearDefaultRouteNameTestValue,
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(
            RecoverableAuthenticatedController.new,
          ),
        ],
        child: const PersonalAiApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('无法恢复登录状态'), findsOneWidget);
    await tester.tap(find.text('重试'));
    await tester.pumpAndSettle();

    expect(find.text('recovered@example.com'), findsOneWidget);
  });

  testWidgets('keeps login fields mounted while an interactive login fails',
      (tester) async {
    tester.binding.platformDispatcher.defaultRouteNameTestValue = '/login';
    addTearDown(
      tester.binding.platformDispatcher.clearDefaultRouteNameTestValue,
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(
            InteractiveFailingLoginController.new,
          ),
          authConfigProvider.overrideWith(
            (ref) async => const AuthConfig(registrationEnabled: true),
          ),
        ],
        child: const PersonalAiApp(),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.widgetWithText(TextField, '邮箱'),
      'user@example.com',
    );
    await tester.enterText(
      find.widgetWithText(TextField, '密码'),
      'wrong-password',
    );
    await tester.tap(find.widgetWithText(FilledButton, '登录'));
    await tester.pumpAndSettle();

    final emailField = tester.widget<TextField>(
      find.widgetWithText(TextField, '邮箱'),
    );
    final passwordField = tester.widget<TextField>(
      find.widgetWithText(TextField, '密码'),
    );
    expect(find.text('邮箱或密码错误'), findsOneWidget);
    expect(emailField.controller?.text, 'user@example.com');
    expect(passwordField.controller?.text, 'wrong-password');
    expect(passwordField.focusNode?.hasFocus, isTrue);
    expect(passwordField.controller?.selection.baseOffset, 0);
    expect(
      passwordField.controller?.selection.extentOffset,
      'wrong-password'.length,
    );
  });

  testWidgets(
      'keeps registration fields mounted while an interactive registration fails',
      (tester) async {
    tester.binding.platformDispatcher.defaultRouteNameTestValue = '/register';
    addTearDown(
      tester.binding.platformDispatcher.clearDefaultRouteNameTestValue,
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith(
            InteractiveFailingRegistrationController.new,
          ),
          authConfigProvider.overrideWith(
            (ref) async => const AuthConfig(registrationEnabled: true),
          ),
        ],
        child: const PersonalAiApp(),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(
      find.widgetWithText(TextField, '昵称，可选'),
      '测试用户',
    );
    await tester.enterText(
      find.widgetWithText(TextField, '邮箱'),
      'existing@example.com',
    );
    await tester.enterText(
      find.widgetWithText(TextField, '密码，至少 6 位'),
      'secure-password',
    );
    await tester.enterText(
      find.widgetWithText(TextField, '确认密码'),
      'secure-password',
    );
    await tester.tap(find.widgetWithText(FilledButton, '注册并进入'));
    await tester.pumpAndSettle();

    expect(find.text('邮箱已注册'), findsOneWidget);
    expect(
      tester
          .widget<TextField>(find.widgetWithText(TextField, '昵称，可选'))
          .controller
          ?.text,
      '测试用户',
    );
    expect(
      tester
          .widget<TextField>(find.widgetWithText(TextField, '邮箱'))
          .controller
          ?.text,
      'existing@example.com',
    );
    expect(
      tester
          .widget<TextField>(find.widgetWithText(TextField, '密码，至少 6 位'))
          .controller
          ?.text,
      'secure-password',
    );
    expect(
      tester
          .widget<TextField>(find.widgetWithText(TextField, '确认密码'))
          .controller
          ?.text,
      'secure-password',
    );
  });
}

class DelayedAuthenticatedController extends AuthController {
  DelayedAuthenticatedController(super.ref);

  @override
  Future<void> loadCurrentUser() async {
    await Future<void>.delayed(Duration.zero);
    state = const AuthState(
      user: User(id: 'user-id', email: 'deep-link@example.com'),
    );
  }
}

class RecoverableAuthenticatedController extends AuthController {
  RecoverableAuthenticatedController(super.ref);

  int loadCount = 0;

  @override
  Future<void> loadCurrentUser() async {
    loadCount += 1;
    state = const AuthState(loading: true, initializing: true);
    await Future<void>.delayed(Duration.zero);
    if (loadCount == 1) {
      state = const AuthState(
        error: '后端暂时不可用',
        startupFailed: true,
      );
      return;
    }
    state = const AuthState(
      user: User(id: 'user-id', email: 'recovered@example.com'),
    );
  }
}

class InteractiveFailingLoginController extends AuthController {
  InteractiveFailingLoginController(super.ref);

  @override
  Future<void> loadCurrentUser() async {
    state = const AuthState();
  }

  @override
  Future<void> login(String email, String password) async {
    state = const AuthState(loading: true);
    await Future<void>.delayed(Duration.zero);
    state = const AuthState(error: '邮箱或密码错误');
  }
}

class InteractiveFailingRegistrationController extends AuthController {
  InteractiveFailingRegistrationController(super.ref);

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
    state = const AuthState(loading: true);
    await Future<void>.delayed(Duration.zero);
    state = const AuthState(error: '邮箱已注册');
  }
}
