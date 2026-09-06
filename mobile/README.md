# Flutter Mobile App

这是个人 AI 知识助手的 Flutter 移动端。

## 当前状态

已完成 MVP 移动端主体流程：

- Material 3 主题
- go_router 路由和底部导航
- Riverpod 状态管理
- Dio API client
- Token 存储
- 登录页
- Token 失效后自动返回登录页
- 启动认证临时失败时保留 token、展示错误页并支持重试原深链接
- 首页
- 资料库
- 资料库和会话历史分页
- 会话历史服务端全量搜索并使用输入防抖
- 会话详情默认只加载最近 50 条，按需加载更早消息且内存窗口最多保留 200 条
- 当前提问页同样只保留最近 200 条展示消息，裁剪后提供会话历史入口
- 资料详情
- 资料详情通过混合检索查找并打开相关资料
- 创建笔记
- 文件上传入口
- 上传后任务进度页
- 按状态筛选和分页的任务历史页
- 任务安全取消和失败/已取消任务重试
- 任务历史和详情展示重试来源标识
- 提问页
- 按资料类型、资料和标签限定问答范围
- 问答和整理的资料选择器自动加载全部已索引资料
- 从资料详情直接进入限定当前资料的提问
- 历史会话继续提问时恢复并显示原问答范围
- 回答引用来源、来源类型、页码/段落和相关度展示
- 整理页
- 整理页支持文章大纲和按来源资料继续追问
- 多资料整理最多选择 20 份并显示选择数量
- 单篇资料整理入口
- 整理结果保存为新笔记
- 管理员配置图片 OCR 和语音转文字 Provider
- Embedding 配置变化后跟踪后端创建的全用户索引重建任务
- 按授权会话隔离并并发安全地加密缓存资料、标签、会话和当前用户，断网或 GET 返回 503 时自动回退
- 持续横幅提示当前正在显示离线缓存或服务不可用时的缓存，显示缓存更新时间，并在主动重连后重新加载当前缓存数据
- 加密缓存最多保留 64 条和 4 MiB 正文，自动回收过期及最旧条目
- 安全存储缓存操作最多等待 2 秒，插件异常不会长期阻塞业务响应
- 登录凭据读写删除最多等待 2 秒，保存失败不进入登录态、删除失败仍退出内存会话
- token 保存超时后的晚到写入会条件回滚，不会在登录失败后遗留凭据或覆盖新登录
- 离线缓存保留分页总数响应头
- 聊天页实时麦克风语音输入
- 我的页面
- 完整资料状态和上传文件占用统计

## Flutter SDK

当前机器 Flutter SDK 路径：

```powershell
D:\flutter\bin\flutter.bat
```

在本目录执行：

```powershell
D:\flutter\bin\flutter.bat pub get
D:\flutter\bin\flutter.bat analyze
D:\flutter\bin\flutter.bat test
```

## 后端地址

默认后端地址：

```text
http://127.0.0.1:8000/api
```

运行时可以覆盖：

```powershell
flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000/api
```

运行 Web 开发版时固定使用后端默认允许的 `5600` 端口：

```powershell
flutter run -d chrome --web-hostname 127.0.0.1 --web-port 5600 --dart-define=API_BASE_URL=http://127.0.0.1:8000/api
```

## 本机验证记录

- `flutter analyze` 通过
- `flutter test` 通过
- `flutter build web --dart-define=API_BASE_URL=http://127.0.0.1:8000/api` 通过
- 本机未检测到 Android 设备或模拟器；当前只验证到 Web/桌面预览层
- Windows 桌面插件构建需要启用 Developer Mode；Android 分发前需要配置私有 release 签名
