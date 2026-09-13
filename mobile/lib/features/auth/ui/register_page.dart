import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../providers/auth_provider.dart';

class RegisterPage extends ConsumerStatefulWidget {
  const RegisterPage({super.key});

  @override
  ConsumerState<RegisterPage> createState() => _RegisterPageState();
}

class _RegisterPageState extends ConsumerState<RegisterPage> {
  final _nameController = TextEditingController();
  final _emailController = TextEditingController();
  final _inviteController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();
  String? _localError;

  @override
  void dispose() {
    _nameController.dispose();
    _emailController.dispose();
    _inviteController.dispose();
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final authConfig = ref.watch(authConfigProvider);
    return authConfig.when(
      loading: () => Scaffold(
        appBar: AppBar(title: const Text('注册')),
        body: const Center(child: CircularProgressIndicator()),
      ),
      error: (_, _) => Scaffold(
        appBar: AppBar(title: const Text('注册')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text('无法确认是否开放注册'),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: () => ref.invalidate(authConfigProvider),
                  icon: const Icon(Icons.refresh),
                  label: const Text('重试'),
                ),
                TextButton(
                  onPressed: () => context.go('/login'),
                  child: const Text('返回登录'),
                ),
              ],
            ),
          ),
        ),
      ),
      data: (config) => config.registrationEnabled
          ? _buildRegistrationForm(
              context,
              invitationRequired: config.invitationRequired,
            )
          : Scaffold(
              appBar: AppBar(title: const Text('注册')),
              body: Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Text('当前不开放新账号注册'),
                      const SizedBox(height: 16),
                      FilledButton.icon(
                        onPressed: () => context.go('/login'),
                        icon: const Icon(Icons.login),
                        label: const Text('返回登录'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
    );
  }

  Widget _buildRegistrationForm(
    BuildContext context, {
    required bool invitationRequired,
  }) {
    final auth = ref.watch(authControllerProvider);
    final error = _localError ?? auth.error;

    return Scaffold(
      appBar: AppBar(title: const Text('注册')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text('创建你的知识库账号', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: 24),
          TextField(
            controller: _nameController,
            decoration: const InputDecoration(labelText: '昵称，可选'),
            textInputAction: TextInputAction.next,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _emailController,
            decoration: const InputDecoration(labelText: '邮箱'),
            keyboardType: TextInputType.emailAddress,
            textInputAction: TextInputAction.next,
          ),
          if (invitationRequired) ...[
            const SizedBox(height: 12),
            TextField(
              controller: _inviteController,
              decoration: const InputDecoration(labelText: '邀请码'),
              textInputAction: TextInputAction.next,
              autocorrect: false,
              enableSuggestions: false,
            ),
          ],
          const SizedBox(height: 12),
          TextField(
            controller: _passwordController,
            decoration: const InputDecoration(labelText: '密码，至少 6 位'),
            obscureText: true,
            textInputAction: TextInputAction.next,
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _confirmController,
            decoration: const InputDecoration(labelText: '确认密码'),
            obscureText: true,
            onSubmitted: (_) => _submit(
              invitationRequired: invitationRequired,
            ),
          ),
          const SizedBox(height: 20),
          FilledButton(
            onPressed: auth.loading
                ? null
                : () => _submit(
                      invitationRequired: invitationRequired,
                    ),
            child: Text(auth.loading ? '注册中' : '注册并进入'),
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: auth.loading ? null : () => context.go('/login'),
            child: const Text('已有账号，去登录'),
          ),
          if (error != null) ...[
            const SizedBox(height: 12),
            Text(
              error,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
        ],
      ),
    );
  }

  Future<void> _submit({required bool invitationRequired}) async {
    final email = _emailController.text.trim();
    final inviteCode = _inviteController.text.trim();
    final password = _passwordController.text;
    final confirm = _confirmController.text;

    setState(() => _localError = null);
    if (email.isEmpty) {
      setState(() => _localError = '请输入邮箱');
      return;
    }
    if (invitationRequired && inviteCode.isEmpty) {
      setState(() => _localError = '请输入邀请码');
      return;
    }
    if (password.length < 6) {
      setState(() => _localError = '密码至少需要 6 位');
      return;
    }
    if (password != confirm) {
      setState(() => _localError = '两次输入的密码不一致');
      return;
    }

    await ref.read(authControllerProvider.notifier).register(
          email: email,
          password: password,
          name: _nameController.text,
          inviteCode: invitationRequired ? inviteCode : null,
        );
  }
}
