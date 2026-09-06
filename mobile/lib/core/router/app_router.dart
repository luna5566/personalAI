import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/auth/providers/auth_provider.dart';
import '../../features/auth/ui/auth_startup_error_page.dart';
import '../../features/auth/ui/login_page.dart';
import '../../features/auth/ui/register_page.dart';
import '../../features/auth/ui/registration_invites_page.dart';
import '../../features/chat/ui/chat_page.dart';
import '../../features/chat/ui/conversation_detail_page.dart';
import '../../features/chat/ui/conversation_history_page.dart';
import '../../features/documents/ui/document_detail_page.dart';
import '../../features/documents/ui/documents_page.dart';
import '../../features/documents/ui/new_note_page.dart';
import '../../features/home/ui/home_page.dart';
import '../../features/jobs/ui/job_status_page.dart';
import '../../features/jobs/ui/job_history_page.dart';
import '../../features/me/ui/me_page.dart';
import '../../features/organize/ui/organize_page.dart';
import '../../features/settings/ui/model_settings_page.dart';
import '../../features/tags/ui/tag_management_page.dart';
import 'main_shell.dart';

final _rootNavigatorKey = GlobalKey<NavigatorState>();
final _shellNavigatorKey = GlobalKey<NavigatorState>();

final appRouterProvider = Provider<GoRouter>((ref) {
  final router = GoRouter(
    navigatorKey: _rootNavigatorKey,
    initialLocation: '/loading',
    overridePlatformDefaultLocation: false,
    redirect: (context, state) {
      final authState = ref.read(authControllerProvider);
      final loggedIn = authState.user != null;
      final initializing = authState.initializing;
      final inLoading = state.matchedLocation == '/loading';
      final inStartupError = state.matchedLocation == '/startup-error';
      final inAuthFlow = state.matchedLocation == '/login' ||
          state.matchedLocation == '/register';
      final redirectTarget = _validatedRedirectTarget(
        state.uri.queryParameters['redirect'],
      );
      if (initializing) {
        return inLoading
            ? null
            : _locationWithRedirect(
                '/loading',
                redirectTarget ?? state.uri.toString(),
              );
      }
      if (authState.startupFailed && !loggedIn) {
        return inStartupError
            ? null
            : _locationWithRedirect(
                '/startup-error',
                redirectTarget ?? state.uri.toString(),
              );
      }
      if (inStartupError) {
        return loggedIn ? redirectTarget ?? '/app/home' : '/login';
      }
      if (inLoading) {
        if (loggedIn) {
          return redirectTarget ?? '/app/home';
        }
        return _locationWithRedirect('/login', redirectTarget);
      }
      if (!loggedIn && !inAuthFlow) {
        return _locationWithRedirect('/login', state.uri.toString());
      }
      if (loggedIn && inAuthFlow) {
        return redirectTarget ?? '/app/home';
      }
      return null;
    },
    routes: [
      GoRoute(
        path: '/loading',
        builder: (context, state) => const Scaffold(
          body: Center(child: CircularProgressIndicator()),
        ),
      ),
      GoRoute(
        path: '/login',
        builder: (context, state) => const LoginPage(),
      ),
      GoRoute(
        path: '/startup-error',
        builder: (context, state) => const AuthStartupErrorPage(),
      ),
      GoRoute(
        path: '/register',
        builder: (context, state) => const RegisterPage(),
      ),
      ShellRoute(
        navigatorKey: _shellNavigatorKey,
        builder: (context, state, child) => MainShell(child: child),
        routes: [
          GoRoute(
              path: '/app/home', builder: (context, state) => const HomePage()),
          GoRoute(
              path: '/app/documents',
              builder: (context, state) => const DocumentsPage()),
          GoRoute(
            path: '/app/chat',
            builder: (context, state) => ChatPage(
              initialDocumentId: state.uri.queryParameters['documentId'],
              initialDocumentIds: _documentIdsFromQuery(state.uri),
            ),
          ),
          GoRoute(
              path: '/app/organize',
              builder: (context, state) => const OrganizePage()),
          GoRoute(path: '/app/me', builder: (context, state) => const MePage()),
        ],
      ),
      GoRoute(
        parentNavigatorKey: _rootNavigatorKey,
        path: '/app/documents/new-note',
        builder: (context, state) => const NewNotePage(),
      ),
      GoRoute(
        parentNavigatorKey: _rootNavigatorKey,
        path: '/app/documents/:id',
        builder: (context, state) => DocumentDetailPage(
          documentId: state.pathParameters['id']!,
          highlightText: state.uri.queryParameters['highlight'],
          highlightStart: int.tryParse(
            state.uri.queryParameters['highlightStart'] ?? '',
          ),
          highlightEnd: int.tryParse(
            state.uri.queryParameters['highlightEnd'] ?? '',
          ),
        ),
      ),
      GoRoute(
        parentNavigatorKey: _rootNavigatorKey,
        path: '/app/jobs',
        builder: (context, state) => const JobHistoryPage(),
      ),
      GoRoute(
        parentNavigatorKey: _rootNavigatorKey,
        path: '/app/jobs/:id',
        builder: (context, state) => JobStatusPage(
          jobId: state.pathParameters['id']!,
          documentId: state.uri.queryParameters['documentId'],
        ),
      ),
      GoRoute(
        parentNavigatorKey: _rootNavigatorKey,
        path: '/app/chat/history',
        builder: (context, state) => const ConversationHistoryPage(),
      ),
      GoRoute(
        parentNavigatorKey: _rootNavigatorKey,
        path: '/app/chat/history/:id',
        builder: (context, state) =>
            ConversationDetailPage(conversationId: state.pathParameters['id']!),
      ),
      GoRoute(
        parentNavigatorKey: _rootNavigatorKey,
        path: '/app/tags',
        builder: (context, state) => const TagManagementPage(),
      ),
      GoRoute(
        parentNavigatorKey: _rootNavigatorKey,
        path: '/app/settings/model',
        builder: (context, state) => const ModelSettingsPage(),
      ),
      GoRoute(
        parentNavigatorKey: _rootNavigatorKey,
        path: '/app/settings/invites',
        builder: (context, state) => const RegistrationInvitesPage(),
      ),
    ],
  );
  ref.listen<AuthState>(authControllerProvider, (_, __) => router.refresh());
  ref.onDispose(router.dispose);
  return router;
});

String _locationWithRedirect(String path, String? redirectTarget) {
  final target = _validatedRedirectTarget(redirectTarget);
  if (target == null) {
    return path;
  }
  return Uri(
    path: path,
    queryParameters: {'redirect': target},
  ).toString();
}

String? _validatedRedirectTarget(String? value) {
  if (value == null || value.isEmpty) {
    return null;
  }
  final uri = Uri.tryParse(value);
  if (uri == null || uri.hasScheme || uri.hasAuthority) {
    return null;
  }
  return uri.path.startsWith('/app/') ? uri.toString() : null;
}

List<String> _documentIdsFromQuery(Uri uri) {
  final value = uri.queryParameters['documentIds'];
  if (value == null || value.isEmpty) {
    return const [];
  }
  return value
      .split(',')
      .map((item) => item.trim())
      .where((item) => item.isNotEmpty)
      .toSet()
      .toList();
}
