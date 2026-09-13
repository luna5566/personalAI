import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../providers/auth_provider.dart';

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _passwordFocusNode = FocusNode();

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _passwordFocusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authControllerProvider);
    final authConfig = ref.watch(authConfigProvider);
    ref.listen<AuthState>(authControllerProvider, (previous, next) {
      final loginFailed = previous?.loading == true &&
          !next.loading &&
          next.user == null &&
          next.error != null;
      if (!loginFailed) {
        return;
      }
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) {
          return;
        }
        _passwordFocusNode.requestFocus();
        _passwordController.selection = TextSelection(
          baseOffset: 0,
          extentOffset: _passwordController.text.length,
        );
      });
    });

    return Scaffold(
      appBar: AppBar(title: const Text('登录')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('个人 AI 知识助手', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 24),
          TextField(
            controller: _emailController,
            decoration: const InputDecoration(labelText: '邮箱'),
            keyboardType: TextInputType.emailAddress,
            textInputAction: TextInputAction.next,
            autofillHints: const [AutofillHints.username, AutofillHints.email],
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _passwordController,
            focusNode: _passwordFocusNode,
            decoration: const InputDecoration(labelText: '密码'),
            obscureText: true,
            textInputAction: TextInputAction.done,
            autofillHints: const [AutofillHints.password],
            onSubmitted: auth.loading ? null : (_) => _login(),
          ),
          const SizedBox(height: 20),
          FilledButton(
            onPressed: auth.loading ? null : _login,
            child: Text(auth.loading ? '登录中' : '登录'),
          ),
          const SizedBox(height: 8),
          if (authConfig.value?.registrationEnabled == true)
            TextButton(
              onPressed: auth.loading ? null : () => context.push('/register'),
              child: const Text('创建新账号'),
            ),
          if (auth.error != null) ...[
            const SizedBox(height: 12),
            Text(auth.error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error)),
          ],
        ],
      ),
    );
  }

  void _login() {
    ref.read(authControllerProvider.notifier).login(
          _emailController.text.trim(),
          _passwordController.text,
        );
  }
}
