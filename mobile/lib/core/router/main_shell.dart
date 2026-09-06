import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

class MainShell extends StatelessWidget {
  const MainShell({required this.child, super.key});

  final Widget child;

  static const _tabs = [
    _TabItem('/app/home', Icons.home_outlined, '首页'),
    _TabItem('/app/documents', Icons.folder_outlined, '资料'),
    _TabItem('/app/chat', Icons.chat_bubble_outline, '提问'),
    _TabItem('/app/organize', Icons.auto_awesome_outlined, '整理'),
    _TabItem('/app/me', Icons.person_outline, '我的'),
  ];

  @override
  Widget build(BuildContext context) {
    final location = GoRouterState.of(context).matchedLocation;
    final currentIndex = _tabs
        .indexWhere((tab) => location.startsWith(tab.path))
        .clamp(0, _tabs.length - 1)
        .toInt();

    return Scaffold(
      body: child,
      bottomNavigationBar: NavigationBar(
        selectedIndex: currentIndex,
        onDestinationSelected: (index) => context.go(_tabs[index].path),
        destinations: [
          for (final tab in _tabs)
            NavigationDestination(icon: Icon(tab.icon), label: tab.label),
        ],
      ),
    );
  }
}

class _TabItem {
  const _TabItem(this.path, this.icon, this.label);

  final String path;
  final IconData icon;
  final String label;
}
