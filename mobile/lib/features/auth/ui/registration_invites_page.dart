import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/user_error_message.dart';
import '../models/registration_invite.dart';
import '../providers/registration_invites_provider.dart';

class RegistrationInvitesPage extends ConsumerStatefulWidget {
  const RegistrationInvitesPage({super.key});

  @override
  ConsumerState<RegistrationInvitesPage> createState() =>
      _RegistrationInvitesPageState();
}

class _RegistrationInvitesPageState
    extends ConsumerState<RegistrationInvitesPage> {
  int _page = 1;
  String _status = 'all';
  bool _creating = false;
  String? _revokingId;

  RegistrationInviteQuery get _query => (
        page: _page,
        status: _status == 'all' ? null : _status,
      );

  @override
  Widget build(BuildContext context) {
    final invites = ref.watch(registrationInvitesPageProvider(_query));
    return Scaffold(
      appBar: AppBar(
        title: const Text('注册邀请码'),
        actions: [
          SizedBox.square(
            dimension: 48,
            child: _creating
                ? const Center(
                    child: SizedBox.square(
                      dimension: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  )
                : IconButton(
                    tooltip: '创建邀请码',
                    onPressed: _createInvite,
                    icon: const Icon(Icons.add),
                  ),
          ),
        ],
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: DropdownButtonFormField<String>(
              initialValue: _status,
              decoration: const InputDecoration(labelText: '状态'),
              items: const [
                DropdownMenuItem(value: 'all', child: Text('全部')),
                DropdownMenuItem(value: 'active', child: Text('可使用')),
                DropdownMenuItem(value: 'used', child: Text('已使用')),
                DropdownMenuItem(value: 'expired', child: Text('已过期')),
                DropdownMenuItem(value: 'revoked', child: Text('已失效')),
              ],
              onChanged: (value) {
                if (value == null || value == _status) {
                  return;
                }
                setState(() {
                  _status = value;
                  _page = 1;
                });
              },
            ),
          ),
          Expanded(
            child: invites.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (_, _) => _InviteLoadError(
                onRetry: () => ref.invalidate(
                  registrationInvitesPageProvider(_query),
                ),
              ),
              data: (page) => _buildPage(page),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildPage(RegistrationInvitePage page) {
    if (page.items.isEmpty) {
      return Center(
        child: FilledButton.icon(
          onPressed: _creating ? null : _createInvite,
          icon: const Icon(Icons.add),
          label: const Text('创建邀请码'),
        ),
      );
    }
    return Column(
      children: [
        Expanded(
          child: RefreshIndicator(
            onRefresh: () => ref.refresh(
              registrationInvitesPageProvider(_query).future,
            ),
            child: ListView.separated(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.symmetric(horizontal: 16),
              itemCount: page.items.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (context, index) {
                final invite = page.items[index];
                return _RegistrationInviteTile(
                  invite: invite,
                  revoking: _revokingId == invite.id,
                  actionsEnabled: _revokingId == null,
                  onRevoke: () => _revokeInvite(invite),
                );
              },
            ),
          ),
        ),
        if (page.totalPages > 1)
          SizedBox(
            height: 64,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                IconButton(
                  tooltip: '上一页',
                  onPressed: page.hasPrevious
                      ? () => setState(() => _page -= 1)
                      : null,
                  icon: const Icon(Icons.chevron_left),
                ),
                SizedBox(
                  width: 88,
                  child: Text(
                    '${page.page} / ${page.totalPages}',
                    textAlign: TextAlign.center,
                  ),
                ),
                IconButton(
                  tooltip: '下一页',
                  onPressed:
                      page.hasNext ? () => setState(() => _page += 1) : null,
                  icon: const Icon(Icons.chevron_right),
                ),
              ],
            ),
          ),
      ],
    );
  }

  Future<void> _createInvite() async {
    final validHours = await showDialog<int>(
      context: context,
      builder: (context) => const _CreateInviteDialog(),
    );
    if (validHours == null || !mounted) {
      return;
    }
    setState(() => _creating = true);
    CreatedRegistrationInvite? created;
    try {
      created = await ref
          .read(registrationInvitesApiProvider)
          .create(validHours: validHours);
      ref.invalidate(registrationInvitesPageProvider);
    } catch (error) {
      if (mounted) {
        _showError(
          userFacingErrorMessage(
            error,
            fallback: '创建邀请码失败，请稍后重试',
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _creating = false);
      }
    }
    if (created != null && mounted) {
      await showDialog<void>(
        context: context,
        builder: (context) => _CreatedInviteDialog(code: created!.code),
      );
    }
  }

  Future<void> _revokeInvite(RegistrationInviteInfo invite) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('使邀请码失效'),
        content: Text('邀请码 ${_shortId(invite.id)} 将不能再用于注册。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('确认失效'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) {
      return;
    }
    setState(() => _revokingId = invite.id);
    try {
      await ref.read(registrationInvitesApiProvider).revoke(invite.id);
      ref.invalidate(registrationInvitesPageProvider);
    } catch (error) {
      if (mounted) {
        _showError(
          userFacingErrorMessage(
            error,
            fallback: '使邀请码失效失败，请稍后重试',
          ),
        );
      }
    } finally {
      if (mounted) {
        setState(() => _revokingId = null);
      }
    }
  }

  void _showError(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message)),
    );
  }
}

class _RegistrationInviteTile extends StatelessWidget {
  const _RegistrationInviteTile({
    required this.invite,
    required this.revoking,
    required this.actionsEnabled,
    required this.onRevoke,
  });

  final RegistrationInviteInfo invite;
  final bool revoking;
  final bool actionsEnabled;
  final VoidCallback onRevoke;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: const Icon(Icons.vpn_key_outlined),
      title: Row(
        children: [
          Expanded(child: Text('邀请码 ${_shortId(invite.id)}')),
          _InviteStatusChip(status: invite.status),
        ],
      ),
      subtitle: Text(_inviteDetails(invite)),
      isThreeLine: true,
      trailing: invite.canRevoke
          ? SizedBox.square(
              dimension: 48,
              child: revoking
                  ? const Center(
                      child: SizedBox.square(
                        dimension: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    )
                  : IconButton(
                      tooltip: '使邀请码失效',
                      onPressed: actionsEnabled ? onRevoke : null,
                      icon: const Icon(Icons.block),
                    ),
            )
          : const SizedBox.square(dimension: 48),
    );
  }
}

class _InviteStatusChip extends StatelessWidget {
  const _InviteStatusChip({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (status) {
      'active' => ('可使用', Colors.green),
      'used' => ('已使用', Colors.blueGrey),
      'expired' => ('已过期', Colors.orange),
      _ => ('已失效', Colors.red),
    };
    return Chip(
      label: Text(label),
      side: BorderSide(color: color.withValues(alpha: 0.45)),
      backgroundColor: color.withValues(alpha: 0.08),
    );
  }
}

class _InviteLoadError extends StatelessWidget {
  const _InviteLoadError({required this.onRetry});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text('暂时无法加载邀请码'),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            label: const Text('重试'),
          ),
        ],
      ),
    );
  }
}

class _CreateInviteDialog extends StatefulWidget {
  const _CreateInviteDialog();

  @override
  State<_CreateInviteDialog> createState() => _CreateInviteDialogState();
}

class _CreateInviteDialogState extends State<_CreateInviteDialog> {
  final _hoursController = TextEditingController(text: '168');
  String? _error;

  @override
  void dispose() {
    _hoursController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('创建邀请码'),
      content: TextField(
        controller: _hoursController,
        decoration: InputDecoration(
          labelText: '有效小时数',
          errorText: _error,
        ),
        keyboardType: TextInputType.number,
        inputFormatters: [FilteringTextInputFormatter.digitsOnly],
        autofocus: true,
        onSubmitted: (_) => _submit(),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: _submit,
          child: const Text('创建'),
        ),
      ],
    );
  }

  void _submit() {
    final value = int.tryParse(_hoursController.text);
    if (value == null || value < 1 || value > 8760) {
      setState(() => _error = '请输入 1 到 8760 之间的小时数');
      return;
    }
    Navigator.of(context).pop(value);
  }
}

class _CreatedInviteDialog extends StatelessWidget {
  const _CreatedInviteDialog({required this.code});

  final String code;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('邀请码已创建'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('原码仅显示一次'),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(child: SelectableText(code)),
              IconButton(
                tooltip: '复制邀请码',
                onPressed: () async {
                  await Clipboard.setData(ClipboardData(text: code));
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('邀请码已复制')),
                    );
                  }
                },
                icon: const Icon(Icons.copy),
              ),
            ],
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('关闭'),
        ),
      ],
    );
  }
}

String _shortId(String id) => id.length <= 8 ? id : id.substring(0, 8);

String _inviteDetails(RegistrationInviteInfo invite) {
  final parts = [
    '创建于 ${_formatLocal(invite.createdAt)}',
    '到期于 ${_formatLocal(invite.expiresAt)}',
  ];
  if (invite.usedAt != null) {
    parts.add('使用于 ${_formatLocal(invite.usedAt!)}');
  } else if (invite.revokedAt != null) {
    parts.add('失效于 ${_formatLocal(invite.revokedAt!)}');
  }
  return parts.join('\n');
}

String _formatLocal(DateTime value) {
  final local = value.toLocal();
  String twoDigits(int number) => number.toString().padLeft(2, '0');
  return '${local.year}-${twoDigits(local.month)}-${twoDigits(local.day)} '
      '${twoDigits(local.hour)}:${twoDigits(local.minute)}';
}
