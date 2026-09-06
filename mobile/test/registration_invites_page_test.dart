import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_mobile/features/auth/data/registration_invites_api.dart';
import 'package:personal_ai_mobile/features/auth/models/registration_invite.dart';
import 'package:personal_ai_mobile/features/auth/providers/registration_invites_provider.dart';
import 'package:personal_ai_mobile/features/auth/ui/registration_invites_page.dart';

void main() {
  testWidgets('shows statuses and revokes only an active invite',
      (tester) async {
    final api = FakeRegistrationInvitesApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          registrationInvitesApiProvider.overrideWithValue(api),
        ],
        child: const MaterialApp(home: RegistrationInvitesPage()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('可使用'), findsOneWidget);
    expect(find.text('已使用'), findsOneWidget);
    expect(find.byTooltip('使邀请码失效'), findsOneWidget);

    await tester.tap(find.byTooltip('使邀请码失效'));
    await tester.pumpAndSettle();
    expect(find.text('确认失效'), findsOneWidget);
    await tester.tap(find.text('确认失效'));
    await tester.pumpAndSettle();

    expect(api.revokedIds, ['active-invite-id']);
    expect(api.listCalls, greaterThanOrEqualTo(2));
    expect(find.text('已失效'), findsOneWidget);
    expect(find.byTooltip('使邀请码失效'), findsNothing);
  });

  testWidgets('creates an invite and shows its raw code once', (tester) async {
    final api = FakeRegistrationInvitesApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          registrationInvitesApiProvider.overrideWithValue(api),
        ],
        child: const MaterialApp(home: RegistrationInvitesPage()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('创建邀请码'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextField, '有效小时数'),
      '24',
    );
    await tester.tap(find.widgetWithText(FilledButton, '创建'));
    await tester.pumpAndSettle();

    expect(api.createdValidHours, [24]);
    expect(find.text('原码仅显示一次'), findsOneWidget);
    expect(find.text('raw-code-shown-once'), findsOneWidget);
    expect(find.byTooltip('复制邀请码'), findsOneWidget);
  });

  testWidgets('rejects an invite duration outside the supported range',
      (tester) async {
    final api = FakeRegistrationInvitesApi();
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          registrationInvitesApiProvider.overrideWithValue(api),
        ],
        child: const MaterialApp(home: RegistrationInvitesPage()),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('创建邀请码'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.widgetWithText(TextField, '有效小时数'),
      '0',
    );
    await tester.tap(find.widgetWithText(FilledButton, '创建'));
    await tester.pump();

    expect(find.text('请输入 1 到 8760 之间的小时数'), findsOneWidget);
    expect(api.createdValidHours, isEmpty);
    expect(find.text('创建邀请码'), findsOneWidget);
  });

  testWidgets('shows retry state when invite listing fails', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          registrationInvitesApiProvider.overrideWithValue(
            FailingRegistrationInvitesApi(),
          ),
        ],
        child: const MaterialApp(home: RegistrationInvitesPage()),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('暂时无法加载邀请码'), findsOneWidget);
    expect(find.text('重试'), findsOneWidget);
  });
}

class FakeRegistrationInvitesApi extends RegistrationInvitesApi {
  FakeRegistrationInvitesApi() : super(Dio());

  int listCalls = 0;
  final List<String> revokedIds = [];
  final List<int> createdValidHours = [];
  final List<RegistrationInviteInfo> _items = [
    RegistrationInviteInfo(
      id: 'active-invite-id',
      status: 'active',
      createdAt: DateTime.utc(2026, 7, 17, 10),
      expiresAt: DateTime.utc(2026, 7, 24, 10),
    ),
    RegistrationInviteInfo(
      id: 'used-invite-id',
      status: 'used',
      createdAt: DateTime.utc(2026, 7, 16, 10),
      expiresAt: DateTime.utc(2026, 7, 23, 10),
      usedAt: DateTime.utc(2026, 7, 17, 9),
    ),
  ];

  @override
  Future<RegistrationInvitePage> list({
    int page = 1,
    int pageSize = 20,
    String? status,
  }) async {
    listCalls += 1;
    final items = status == null
        ? _items
        : _items.where((invite) => invite.status == status).toList();
    return RegistrationInvitePage(
      items: List.unmodifiable(items),
      total: items.length,
      page: page,
      pageSize: pageSize,
    );
  }

  @override
  Future<CreatedRegistrationInvite> create({required int validHours}) async {
    createdValidHours.add(validHours);
    final invite = RegistrationInviteInfo(
      id: 'created-invite-id',
      status: 'active',
      createdAt: DateTime.utc(2026, 7, 17, 12),
      expiresAt: DateTime.utc(2026, 7, 18, 12),
    );
    _items.insert(0, invite);
    return CreatedRegistrationInvite(
      code: 'raw-code-shown-once',
      invite: invite,
    );
  }

  @override
  Future<void> revoke(String id) async {
    revokedIds.add(id);
    final index = _items.indexWhere((invite) => invite.id == id);
    final current = _items[index];
    _items[index] = RegistrationInviteInfo(
      id: current.id,
      status: 'revoked',
      createdAt: current.createdAt,
      expiresAt: current.expiresAt,
      revokedAt: DateTime.utc(2026, 7, 17, 13),
    );
  }
}

class FailingRegistrationInvitesApi extends RegistrationInvitesApi {
  FailingRegistrationInvitesApi() : super(Dio());

  @override
  Future<RegistrationInvitePage> list({
    int page = 1,
    int pageSize = 20,
    String? status,
  }) {
    throw StateError('offline');
  }
}
