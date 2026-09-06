import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/auth_provider.dart';

class AuthStartupErrorPage extends ConsumerWidget {
  const AuthStartupErrorPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.cloud_off_outlined,
                    size: 48,
                    color: Theme.of(context).colorScheme.error,
                  ),
                  const SizedBox(height: 16),
                  Text(
                    '无法恢复登录状态',
                    style: Theme.of(context).textTheme.titleLarge,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    auth.error ?? '请检查网络或后端服务后重试。',
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 24),
                  FilledButton.icon(
                    onPressed: auth.loading
                        ? null
                        : () => ref
                            .read(authControllerProvider.notifier)
                            .loadCurrentUser(),
                    icon: const Icon(Icons.refresh),
                    label: const Text('重试'),
                  ),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: auth.loading
                        ? null
                        : () =>
                            ref.read(authControllerProvider.notifier).logout(),
                    child: const Text('重新登录'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
