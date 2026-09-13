import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../auth/models/auth_session.dart';
import '../../auth/providers/auth_provider.dart';
import '../../documents/models/document.dart';
import '../../documents/providers/documents_provider.dart';

class MePage extends ConsumerWidget {
  const MePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);
    final user = auth.user;
    final documentStats = ref.watch(documentStatsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('我的')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ListTile(
            leading: const CircleAvatar(child: Icon(Icons.person_outline)),
            title: Text(user?.name ?? '本地用户'),
            subtitle: Text(user?.email ?? ''),
          ),
          const SizedBox(height: 12),
          _StorageSummaryTile(
            stats: documentStats,
            onRetry: () => ref.invalidate(documentStatsProvider),
          ),
          const SizedBox(height: 12),
          ListTile(
            leading: const Icon(Icons.label_outline),
            title: const Text('标签管理'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.push('/app/tags'),
          ),
          ListTile(
            leading: const Icon(Icons.history_outlined),
            title: const Text('任务历史'),
            subtitle: const Text('查看上传、索引和重建进度'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => context.push('/app/jobs'),
          ),
          if (user?.isAdmin == true) ...[
            ListTile(
              leading: const Icon(Icons.vpn_key_outlined),
              title: const Text('注册邀请码'),
              subtitle: const Text('创建和管理一次性邀请码'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push('/app/settings/invites'),
            ),
            ListTile(
              leading: const Icon(Icons.tune_outlined),
              title: const Text('模型设置'),
              subtitle: const Text('Provider、模型、Base URL、API Key'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push('/app/settings/model'),
            ),
          ],
          ListTile(
            leading: const Icon(Icons.privacy_tip_outlined),
            title: const Text('隐私设置'),
            subtitle: const Text('查看资料存储、离线缓存和模型传输说明'),
            onTap: () => _showPrivacyDialog(context),
          ),
          ListTile(
            leading: const Icon(Icons.password_outlined),
            title: const Text('修改密码'),
            subtitle: const Text('更新密码并退出其它设备'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => _showChangePasswordDialog(context, ref),
          ),
          ListTile(
            leading: const Icon(Icons.devices_outlined),
            title: const Text('登录设备'),
            subtitle: const Text('查看并退出其它设备'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => _showAuthSessionsDialog(context),
          ),
          ListTile(
            leading: const Icon(Icons.logout_outlined),
            title: const Text('退出所有设备'),
            subtitle: const Text('撤销当前账号的全部登录会话'),
            onTap: () => _confirmLogoutAll(context, ref),
          ),
          ListTile(
            leading: const Icon(Icons.cleaning_services_outlined),
            title: const Text('清除本机数据'),
            subtitle: const Text('清除登录凭据和加密离线缓存，需要重新登录'),
            onTap: () => _confirmClearLocalCache(context, ref),
          ),
          if (user?.isAdmin != true)
            ListTile(
              leading: Icon(
                Icons.delete_forever_outlined,
                color: Theme.of(context).colorScheme.error,
              ),
              title: Text(
                '删除账号',
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
              subtitle: const Text('永久删除账号及全部资料、问答和设置'),
              onTap: auth.loading
                  ? null
                  : () => _showDeleteAccountDialog(context, ref),
            ),
          const SizedBox(height: 12),
          OutlinedButton.icon(
            onPressed: () => ref.read(authControllerProvider.notifier).logout(),
            icon: const Icon(Icons.logout),
            label: const Text('退出登录'),
          ),
        ],
      ),
    );
  }

  void _showPrivacyDialog(BuildContext context) {
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('隐私设置'),
        content: const Text(
          '资料由后端配置保存到本地或 S3 兼容对象存储。App 会在系统安全存储中保存登录凭据和加密离线缓存。'
          '启用外部模型 Provider 时，相关资料内容会发送到你配置的服务。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('知道了'),
          ),
        ],
      ),
    );
  }

  Future<void> _confirmClearLocalCache(
      BuildContext context, WidgetRef ref) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('清除本机数据'),
        content: const Text('这会清除登录凭据和离线缓存并返回登录页，后端资料不会被删除。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('清空'),
          ),
        ],
      ),
    );
    if (confirmed != true) {
      return;
    }
    await ref.read(authControllerProvider.notifier).logout();
  }

  Future<void> _showChangePasswordDialog(
    BuildContext context,
    WidgetRef ref,
  ) async {
    final changed = await showDialog<bool>(
      context: context,
      builder: (context) => _ChangePasswordDialog(
        onSubmit: ({required currentPassword, required newPassword}) {
          return ref.read(authControllerProvider.notifier).changePassword(
                currentPassword: currentPassword,
                newPassword: newPassword,
              );
        },
      ),
    );
    if (changed == true && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('密码已修改，其它设备已退出登录')),
      );
    }
  }

  Future<void> _showAuthSessionsDialog(BuildContext context) async {
    await showDialog<void>(
      context: context,
      builder: (context) => const _AuthSessionsDialog(),
    );
  }

  Future<void> _confirmLogoutAll(
    BuildContext context,
    WidgetRef ref,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('退出所有设备'),
        content: const Text('所有设备上的登录状态都会失效，包括当前设备。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('全部退出'),
          ),
        ],
      ),
    );
    if (confirmed != true) {
      return;
    }
    final error = await ref.read(authControllerProvider.notifier).logoutAll();
    if (error != null && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error)),
      );
    }
  }

  Future<void> _showDeleteAccountDialog(
    BuildContext context,
    WidgetRef ref,
  ) async {
    await showDialog<bool>(
      context: context,
      builder: (context) => _DeleteAccountDialog(
        onSubmit: ({required currentPassword}) {
          return ref.read(authControllerProvider.notifier).deleteAccount(
                currentPassword: currentPassword,
              );
        },
      ),
    );
  }
}

class _DeleteAccountDialog extends StatefulWidget {
  const _DeleteAccountDialog({required this.onSubmit});

  final Future<String?> Function({required String currentPassword}) onSubmit;

  @override
  State<_DeleteAccountDialog> createState() => _DeleteAccountDialogState();
}

class _DeleteAccountDialogState extends State<_DeleteAccountDialog> {
  final _passwordController = TextEditingController();
  final _passwordFocusNode = FocusNode();
  bool _confirmed = false;
  bool _submitting = false;
  String? _error;

  @override
  void dispose() {
    _passwordController.dispose();
    _passwordFocusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return AlertDialog(
      title: const Text('删除账号'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '账号、资料、问答记录、标签和登录设备都会永久删除。此操作无法撤销。',
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _passwordController,
                focusNode: _passwordFocusNode,
                enabled: !_submitting,
                obscureText: true,
                autofillHints: const [AutofillHints.password],
                decoration: const InputDecoration(
                  labelText: '当前密码',
                  border: OutlineInputBorder(),
                ),
                onSubmitted: (_) => _submit(),
              ),
              const SizedBox(height: 8),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _confirmed,
                onChanged: _submitting
                    ? null
                    : (value) {
                        setState(() => _confirmed = value ?? false);
                      },
                title: const Text('我确认永久删除账号和全部数据'),
                controlAffinity: ListTileControlAffinity.leading,
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    _error!,
                    style: TextStyle(color: colorScheme.error),
                  ),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed:
              _submitting ? null : () => Navigator.of(context).pop(false),
          child: const Text('取消'),
        ),
        FilledButton(
          style: FilledButton.styleFrom(
            backgroundColor: colorScheme.error,
            foregroundColor: colorScheme.onError,
          ),
          onPressed: _submitting ? null : _submit,
          child: _submitting
              ? const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('永久删除'),
        ),
      ],
    );
  }

  Future<void> _submit() async {
    final password = _passwordController.text;
    if (password.isEmpty) {
      setState(() => _error = '请输入当前密码');
      _passwordFocusNode.requestFocus();
      return;
    }
    if (!_confirmed) {
      setState(() => _error = '请确认永久删除账号和全部数据');
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });
    final error = await widget.onSubmit(currentPassword: password);
    if (!mounted) {
      return;
    }
    if (error == null) {
      Navigator.of(context).pop(true);
      return;
    }
    setState(() {
      _submitting = false;
      _error = error;
    });
  }
}

class _AuthSessionsDialog extends ConsumerStatefulWidget {
  const _AuthSessionsDialog();

  @override
  ConsumerState<_AuthSessionsDialog> createState() =>
      _AuthSessionsDialogState();
}

class _AuthSessionsDialogState extends ConsumerState<_AuthSessionsDialog> {
  String? _revokingSessionId;
  String? _revokeError;

  @override
  Widget build(BuildContext context) {
    final sessions = ref.watch(authSessionsProvider);
    return AlertDialog(
      title: const Text('登录设备'),
      content: SizedBox(
        width: 520,
        child: sessions.when(
          loading: () => const SizedBox(
            height: 160,
            child: Center(child: CircularProgressIndicator()),
          ),
          error: (_, _) => SizedBox(
            height: 160,
            child: Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text('暂时无法加载登录设备'),
                  const SizedBox(height: 12),
                  FilledButton.icon(
                    onPressed: () => ref.invalidate(authSessionsProvider),
                    icon: const Icon(Icons.refresh),
                    label: const Text('重试'),
                  ),
                ],
              ),
            ),
          ),
          data: (items) => _buildSessionList(items),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('关闭'),
        ),
      ],
    );
  }

  Widget _buildSessionList(List<AuthSessionInfo> sessions) {
    if (sessions.isEmpty) {
      return const SizedBox(
        height: 120,
        child: Center(child: Text('没有有效登录设备')),
      );
    }
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ConstrainedBox(
          constraints: const BoxConstraints(maxHeight: 420),
          child: ListView.separated(
            shrinkWrap: true,
            itemCount: sessions.length,
            separatorBuilder: (_, _) => const Divider(height: 1),
            itemBuilder: (context, index) {
              final session = sessions[index];
              final isRevoking = _revokingSessionId == session.id;
              return ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.devices_other_outlined),
                title: Text(
                  session.clientName ?? '未知设备',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
                subtitle: Text(
                  '登录于 ${_formatLocal(session.createdAtLocal)}\n'
                  '有效期至 ${_formatLocal(session.expiresAtLocal)}',
                ),
                isThreeLine: true,
                trailing: session.isCurrent
                    ? const Chip(label: Text('当前设备'))
                    : SizedBox.square(
                        dimension: 48,
                        child: isRevoking
                            ? const Center(
                                child: SizedBox.square(
                                  dimension: 20,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                ),
                              )
                            : IconButton(
                                tooltip: '退出此设备',
                                onPressed: _revokingSessionId == null
                                    ? () => _revoke(session.id)
                                    : null,
                                icon: const Icon(Icons.logout),
                              ),
                      ),
              );
            },
          ),
        ),
        if (_revokeError != null) ...[
          const SizedBox(height: 12),
          Text(
            _revokeError!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        ],
      ],
    );
  }

  Future<void> _revoke(String sessionId) async {
    setState(() {
      _revokingSessionId = sessionId;
      _revokeError = null;
    });
    try {
      await ref.read(authApiProvider).revokeSession(sessionId);
      ref.invalidate(authSessionsProvider);
    } catch (_) {
      if (mounted) {
        setState(() => _revokeError = '退出设备失败，请稍后重试');
      }
    } finally {
      if (mounted) {
        setState(() => _revokingSessionId = null);
      }
    }
  }

  String _formatLocal(DateTime value) {
    String twoDigits(int number) => number.toString().padLeft(2, '0');
    return '${value.year}-${twoDigits(value.month)}-${twoDigits(value.day)} '
        '${twoDigits(value.hour)}:${twoDigits(value.minute)}';
  }
}

typedef _PasswordSubmit = Future<String?> Function({
  required String currentPassword,
  required String newPassword,
});

class _ChangePasswordDialog extends StatefulWidget {
  const _ChangePasswordDialog({required this.onSubmit});

  final _PasswordSubmit onSubmit;

  @override
  State<_ChangePasswordDialog> createState() => _ChangePasswordDialogState();
}

class _ChangePasswordDialogState extends State<_ChangePasswordDialog> {
  final _currentController = TextEditingController();
  final _newController = TextEditingController();
  final _confirmController = TextEditingController();
  bool _submitting = false;
  bool _obscureCurrent = true;
  bool _obscureNew = true;
  String? _error;

  @override
  void dispose() {
    _currentController.dispose();
    _newController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('修改密码'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _currentController,
              obscureText: _obscureCurrent,
              decoration: InputDecoration(
                labelText: '当前密码',
                suffixIcon: IconButton(
                  tooltip: _obscureCurrent ? '显示密码' : '隐藏密码',
                  onPressed: () => setState(
                    () => _obscureCurrent = !_obscureCurrent,
                  ),
                  icon: Icon(
                    _obscureCurrent
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                  ),
                ),
              ),
              textInputAction: TextInputAction.next,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _newController,
              obscureText: _obscureNew,
              decoration: InputDecoration(
                labelText: '新密码，至少 6 位',
                suffixIcon: IconButton(
                  tooltip: _obscureNew ? '显示密码' : '隐藏密码',
                  onPressed: () => setState(() => _obscureNew = !_obscureNew),
                  icon: Icon(
                    _obscureNew
                        ? Icons.visibility_outlined
                        : Icons.visibility_off_outlined,
                  ),
                ),
              ),
              textInputAction: TextInputAction.next,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _confirmController,
              obscureText: true,
              decoration: const InputDecoration(labelText: '确认新密码'),
              onSubmitted: (_) => _submit(),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed:
              _submitting ? null : () => Navigator.of(context).pop(false),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: _submitting ? null : _submit,
          child: Text(_submitting ? '修改中' : '确认修改'),
        ),
      ],
    );
  }

  Future<void> _submit() async {
    final currentPassword = _currentController.text;
    final newPassword = _newController.text;
    final confirmPassword = _confirmController.text;
    String? localError;
    if (currentPassword.isEmpty) {
      localError = '请输入当前密码';
    } else if (newPassword.length < 6) {
      localError = '新密码至少需要 6 位';
    } else if (newPassword == currentPassword) {
      localError = '新密码不能与当前密码相同';
    } else if (newPassword != confirmPassword) {
      localError = '两次输入的新密码不一致';
    }
    if (localError != null) {
      setState(() => _error = localError);
      return;
    }

    setState(() {
      _submitting = true;
      _error = null;
    });
    final error = await widget.onSubmit(
      currentPassword: currentPassword,
      newPassword: newPassword,
    );
    if (!mounted) {
      return;
    }
    if (error == null) {
      Navigator.of(context).pop(true);
      return;
    }
    setState(() {
      _submitting = false;
      _error = error;
    });
  }
}

class _StorageSummaryTile extends StatelessWidget {
  const _StorageSummaryTile({
    required this.stats,
    required this.onRetry,
  });

  final AsyncValue<DocumentStats> stats;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return stats.when(
      data: (value) {
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('存储空间', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 12,
                  runSpacing: 8,
                  children: [
                    _MetricChip(label: '资料', value: value.total.toString()),
                    _MetricChip(label: '已索引', value: value.indexed.toString()),
                    _MetricChip(
                      label: '处理中',
                      value: value.processing.toString(),
                    ),
                    _MetricChip(label: '失败', value: value.failed.toString()),
                    _MetricChip(
                      label: '已取消',
                      value: value.cancelled.toString(),
                    ),
                    _MetricChip(
                      label: '文件空间',
                      value: _formatBytes(value.storageBytes),
                    ),
                  ],
                ),
              ],
            ),
          ),
        );
      },
      error: (_, _) => Card(
        child: ListTile(
          leading: const Icon(Icons.storage_outlined),
          title: const Text('存储空间'),
          subtitle: const Text('暂时无法加载资料统计'),
          trailing: IconButton(
            tooltip: '重新加载资料统计',
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
          ),
        ),
      ),
      loading: () => const Card(
        child: ListTile(
          leading: Icon(Icons.storage_outlined),
          title: Text('存储空间'),
          subtitle: LinearProgressIndicator(),
        ),
      ),
    );
  }

  String _formatBytes(int bytes) {
    if (bytes < 1024) {
      return '$bytes B';
    }
    const units = ['KB', 'MB', 'GB', 'TB'];
    var value = bytes / 1024;
    var unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    final digits = value >= 10 ? 0 : 1;
    return '${value.toStringAsFixed(digits)} ${units[unitIndex]}';
  }
}

class _MetricChip extends StatelessWidget {
  const _MetricChip({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Chip(label: Text('$label $value'));
  }
}
