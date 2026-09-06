import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'package:personal_ai_mobile/app.dart';
import 'package:personal_ai_mobile/features/auth/models/auth_config.dart';
import 'package:personal_ai_mobile/features/auth/providers/auth_provider.dart';

void main() {
  testWidgets('renders login entry', (tester) async {
    FlutterSecureStorage.setMockInitialValues({});
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authConfigProvider.overrideWith(
            (ref) async => const AuthConfig(registrationEnabled: true),
          ),
        ],
        child: const PersonalAiApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('登录'), findsWidgets);
  });
}
