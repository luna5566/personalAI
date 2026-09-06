# Flutter App 结构与页面交互设计

## 目标

第一版移动端 App 的目标不是做复杂知识管理工具，而是让用户能顺畅完成三个核心动作：

```text
添加资料
  -> 查看资料状态
  -> 基于资料提问或整理
```

App 需要优先保证：

- 入口简单
- 上传和索引状态清楚
- 问答过程像聊天一样自然
- 回答能看到引用来源
- AI 整理结果可以保存为新笔记

## 技术选择

```text
Flutter
Dart
Riverpod 或 Bloc 做状态管理
Dio 做 HTTP 请求
go_router 做路由
secure_storage 保存 token
file_picker 选择文件
```

第一版推荐：

```text
状态管理：Riverpod
路由：go_router
网络请求：Dio
```

原因是移动端页面会围绕资料、聊天、任务状态刷新，Riverpod 的粒度比较适合。

## App 信息架构

底部导航使用 5 个 Tab：

```text
首页
资料
提问
整理
我的
```

对应用户心智：

- 首页：快速入口和最近动态
- 资料：管理个人知识库
- 提问：直接问自己的资料
- 整理：不明确提问时，让 AI 主动归纳
- 我的：账号、模型、隐私和设置

## 页面结构

### 1. 启动页

用途：

- 检查本地 token
- 判断是否已登录
- 拉取当前用户信息
- 决定进入登录页或首页

状态：

- loading
- authenticated
- unauthenticated
- error

接口：

```text
GET /auth/me
```

### 2. 登录注册页

第一版支持邮箱密码登录。

页面包含：

- 邮箱输入框
- 密码输入框
- 登录按钮
- 后端开放注册时显示注册入口

接口：

```text
GET /auth/config
POST /auth/login
POST /auth/register
```

登录页不预填本地默认邮箱或密码，字段通过系统 autofill hints 接受用户已保存的凭据。`GET /auth/config` 成功且 `registration_enabled=true` 时才显示“创建新账号”；能力查询失败只隐藏注册入口，不阻断已有账号登录。直接进入注册路由时必须等待同一能力查询，关闭时显示“当前不开放新账号注册”，查询失败则提供重试和返回登录操作，后端 `403` 仍是最终授权边界。能力响应的 `invitation_required=true` 时，注册表单增加邀请码字段并在本地拒绝空值；提交时去除首尾空白并映射为 `invite_code`，无效、过期和已使用错误统一显示后端消息。

认证状态把启动会话恢复与交互操作分开：`initializing=true` 只表示 App 正在读取本地 token 或请求 `GET /auth/me`，路由仅在这个阶段进入 `/loading`；`loading=true` 则还可表示登录、注册、改密和退出等当前页面操作，只用于禁用对应控件，不得卸载表单。登录或注册失败时页面、输入和校验上下文继续保留；登录页把焦点移回密码框并全选原密码，便于直接修正后重试。

登录成功后：

```text
保存 access_token
跳转首页
```

### 3. 首页

首页承担快捷入口，不做复杂信息流。

页面模块：

```text
顶部区域：
- 问候语
- 快速提问输入框

快捷操作：
- 记一条
- 上传资料
- 问我的资料
- 一键整理

最近资料：
- 标题
- 摘要
- 标签
- 状态

最近问答：
- 问题
- 简短回答
- 时间
```

交互：

- 点击“记一条”进入创建笔记页
- 点击“上传资料”打开文件选择器
- 点击“问我的资料”进入提问页
- 在顶部输入问题后直接进入提问页并发送问题
- 点击最近资料进入资料详情页
- 最近资料和最近问答各自维护加载、数据和错误状态；失败时显示稳定文案和带 tooltip 的刷新图标
- 点击某一区块的刷新只失效对应 Riverpod provider，不重新请求或清空另一区块

接口：

```text
GET /documents?page=1&page_size=5
GET /chat/conversations?page=1&page_size=3
POST /documents/upload
```

第一版如果后端没有最近问答接口，可以先只展示最近资料。

### 4. 资料库页

资料库是用户管理个人资料的主页面。

页面模块：

```text
顶部：
- 搜索框
- 上传按钮

筛选：
- 全部
- 笔记
- PDF
- TXT
- Markdown
- AI 生成

标签筛选：
- 横向标签列表

资料列表：
- 标题
- 摘要
- 标签
- 来源类型
- 创建时间
- 处理状态
```

资料状态展示：

```text
uploaded      已上传
parsing       解析中
parsed        已解析
summarizing   总结中
chunking      切片中
embedding     索引中
indexed       可提问
failed        处理失败
```

交互：

- 搜索关键词后刷新资料列表
- 点击筛选类型刷新列表
- 点击标签刷新列表
- 点击资料卡片进入资料详情页
- 长按或更多按钮支持删除资料

接口：

```text
GET /documents
DELETE /documents/{document_id}
```

### 5. 创建笔记页

这是最高频的输入场景之一，要轻。

页面字段：

```text
标题，可选
正文，必填
标签，可选
保存按钮
```

交互：

- 标题为空时，后端可根据内容生成标题
- 保存后显示“正在建立索引”
- 保存成功后返回资料详情页或资料库页

接口：

```text
POST /documents/note
GET /documents/{document_id}
```

请求示例：

```json
{
  "title": "英语学习方法",
  "content": "今天看到一个方法，先大量听，再模仿输出...",
  "tags": ["英语", "学习"]
}
```

### 6. 上传资料流程

上传入口可以来自：

- 首页
- 资料库页
- 资料详情页的补充资料入口

支持格式：

```text
v0.2：
- PDF
- TXT
- Markdown

v0.3 或之后：
- 图片 OCR
- 语音转文字
```

交互流程：

```text
点击上传
  -> 选择文件
  -> 确认文件名和类型
  -> 上传
  -> 创建资料记录
  -> 显示处理进度
  -> indexed 后可提问
```

处理进度页展示：

```text
文件名
当前状态
进度条
状态说明
失败原因，如果有
```

接口：

```text
POST /documents/upload
GET /jobs/{job_id}
GET /documents/{document_id}
```

轮询策略：

```text
上传后每 2 秒查询一次 job
成功或失败后停止
用户离开页面后降低频率或停止
资料库页刷新时根据 document.status 展示状态
```

### 7. 资料详情页

资料详情页是用户理解单份资料的地方。

页面模块：

```text
标题
来源类型
标签
处理状态
摘要
原文内容
AI 操作区
```

AI 操作区：

```text
提问
总结
生成大纲
提取知识点
找相关资料
```

交互：

- 状态不是 `indexed` 时，提问按钮不可用
- 点击“提问”进入提问页，并将 scope 限定为当前资料
- 点击“总结”调用整理接口
- 整理结果支持保存为新笔记

接口：

```text
GET /documents/{document_id}
POST /chat/query
POST /organize/document
POST /documents/note
```

### 8. 提问页

提问页是核心体验，形态接近聊天。

页面模块：

```text
顶部：
- 当前问答范围
- 范围选择按钮

聊天区域：
- 用户问题
- AI 回答
- 引用来源
- 推荐追问

底部：
- 输入框
- 发送按钮
- 附加范围按钮
```

问答范围：

```text
全部资料
某个标签
某一份资料
最近 7 天资料
手动选择多份资料
```

第一版建议先支持：

```text
全部资料
某一份资料
某个标签
```

发送问题流程：

```text
用户输入问题
  -> App 立即显示用户消息
  -> 显示 AI 思考中
  -> POST /chat/query
  -> 展示回答
  -> 展示引用来源
  -> 展示推荐追问
```

回答卡片结构：

```text
回答正文

引用来源：
- 资料标题
- 片段预览
- 页码或段落位置

推荐追问：
- 帮我整理成计划
- 这些观点有什么联系？
- 哪些内容最重要？
```

接口：

```text
POST /chat/query
```

请求示例：

```json
{
  "conversation_id": null,
  "question": "我之前记录过哪些英语学习方法？",
  "scope": {
    "document_ids": [],
    "tags": ["英语"],
    "source_types": []
  }
}
```

### 9. 引用来源展示

引用来源要做成可点击的来源卡片。

来源卡片展示：

```text
资料标题
来源类型
页码或段落
片段预览
相似度，可选
```

点击来源卡片：

```text
打开资料详情页
滚动到对应片段，如果已有 offset 或 page 信息
```

第一版可以先打开资料详情页，不强制实现精确定位。

### 10. 整理页

整理页解决“用户不知道该问什么”的问题。

页面模块：

```text
整理对象：
- 最近 7 天资料
- 某个标签
- 某一份资料
- 手动选择多份资料

整理方式：
- 归纳主题
- 生成摘要
- 找关联
- 生成学习计划
- 生成文章大纲
- 提取行动项

结果区域：
- AI 输出内容
- 保存为笔记
- 继续追问
```

第一版建议支持：

```text
单份资料总结
单份资料大纲
多资料主题归纳
保存为笔记
```

接口：

```text
POST /organize/document
POST /organize/collection
POST /documents/note
```

### 11. 我的页

第一版保持简单。

页面模块：

```text
账号信息
模型设置
注册邀请码（仅管理员）
存储空间
隐私设置
登录设备
修改密码
退出所有设备
清空本地缓存
退出登录
```

第一版模型设置可以先只展示，不一定开放复杂配置。

接口：

```text
GET /auth/me
POST /auth/logout
GET /auth/sessions
DELETE /auth/sessions/{session_id}
POST /auth/change-password
POST /auth/logout-all
GET /auth/registration-invites
POST /auth/registration-invites
DELETE /auth/registration-invites/{invite_id}
```

App 先用当前 token 请求服务端撤销对应数据库会话，调用预算为 2 秒；无论请求成功、断网、超时或本机安全存储删除失败，最终都清空内存用户并尝试清理本地 token 与加密缓存。离线退出只能保证当前设备不再使用 token，不能证明服务端已经撤销。

“我的”页提供修改密码和退出所有设备。改密对话框校验当前密码、新密码至少 6 位、不能复用以及二次确认；成功后保存后端返回的替换 token，继续保留当前设备登录并提示其它设备已退出。替换 token 保存失败时旧会话已被后端撤销，App 必须清理本机状态并要求重新登录。全设备退出在服务端确认前保留当前会话，网络失败显示错误并允许重试；成功后清除本机状态并返回登录页。

普通用户在“我的”页看到红色“删除账号”入口，固定管理员不展示。删除对话框说明账号、资料、问答、标签和设备会永久删除，要求输入当前密码并勾选明确确认后才提交 `DELETE /auth/account`；失败时保留对话框、密码和当前登录状态，服务端成功后即使本机安全存储清理失败也结束内存会话并返回登录页，因为远端账号和全部 token 已不可恢复。客户端固定发送 `confirmation=DELETE`，后端仍以当前密码、管理员保护和数据库事务作为最终边界。

资料统计的加载、成功和失败状态使用同一张存储空间卡片，避免请求状态变化造成布局跳动。统计请求失败时只显示“暂时无法加载资料统计”，不渲染 Dio、XMLHttpRequest 或其它底层异常文本；刷新图标带有明确 tooltip，点击后使 `documentStatsProvider` 失效并重新请求。

“登录设备”对话框实时读取未过期会话，显示平台名称、本地登录时间和有效期。当前会话使用“当前设备”状态标记且不显示远程退出按钮，其它会话提供带 tooltip 的退出图标；撤销成功后使 `authSessionsProvider` 失效并重新请求，失败则保留列表并显示可重试错误。会话列表属于安全状态，不加入 GET 离线缓存。Dio 在所有请求中发送只描述 App 平台的 `X-Client-Name`，不发送设备指纹、IP 或 User-Agent。

管理员看到“注册邀请码”入口，普通用户不展示；后端仍以管理员用户 ID 做最终鉴权。管理页支持分页、按可使用/已使用/已过期/已失效筛选、1–8760 小时有效期创建和仅对可使用项执行确认撤销。创建后的原码只在一次性对话框中显示并提供复制操作，关闭后不能从列表恢复；列表加载、创建和撤销失败都保留明确的重试或错误状态。

## 路由设计

```text
/splash
/login
/register
/app
/app/home
/app/documents
/app/documents/:id
/app/documents/new-note
/app/chat
/app/organize
/app/me
/app/settings/invites
/app/jobs/:id
```

`/app` 下使用底部 Tab Shell。

## Flutter 目录结构

```text
mobile/
  lib/
    main.dart
    app.dart

    core/
      config/
        app_config.dart
      network/
        api_client.dart
        auth_interceptor.dart
        api_error.dart
        user_error_message.dart
      router/
        app_router.dart
      storage/
        token_storage.dart
      theme/
        app_theme.dart
      widgets/
        loading_view.dart
        error_view.dart
        empty_view.dart

    features/
      auth/
        data/
          auth_api.dart
          auth_repository.dart
          registration_invites_api.dart
        models/
          auth_session.dart
          registration_invite.dart
          user.dart
        providers/
          auth_provider.dart
          registration_invites_provider.dart
        ui/
          login_page.dart
          register_page.dart
          registration_invites_page.dart

      home/
        ui/
          home_page.dart

      documents/
        data/
          documents_api.dart
          documents_repository.dart
        models/
          document.dart
          document_status.dart
          document_tag.dart
        providers/
          documents_provider.dart
          document_detail_provider.dart
        ui/
          documents_page.dart
          document_detail_page.dart
          new_note_page.dart
          upload_document_page.dart
        widgets/
          document_card.dart
          document_status_badge.dart
          tag_chip.dart

      chat/
        data/
          chat_api.dart
          chat_repository.dart
        models/
          conversation.dart
          message.dart
          citation.dart
          chat_scope.dart
        providers/
          chat_provider.dart
        ui/
          chat_page.dart
          scope_selector_sheet.dart
        widgets/
          message_bubble.dart
          citation_card.dart
          suggested_question_chip.dart

      organize/
        data/
          organize_api.dart
          organize_repository.dart
        models/
          organize_mode.dart
          organize_result.dart
        providers/
          organize_provider.dart
        ui/
          organize_page.dart
          organize_result_page.dart

      jobs/
        data/
          jobs_api.dart
        models/
          job.dart
        providers/
          job_provider.dart
        ui/
          job_progress_page.dart

      me/
        ui/
          me_page.dart
          settings_page.dart
  pubspec.yaml
```

用户可见错误统一通过 `userFacingErrorMessage` 映射。客户端只信任后端 JSON 中非空字符串类型的 `message` 或 `detail`；Dio 连接诊断、超时、HTML/非结构化响应、安全存储异常、插件错误和普通 Dart 异常都使用调用场景提供的稳定中文兜底。后台任务模型中的 `error_message` 是后端主动生成的业务处理原因，继续按原文展示。

## 前端模型字段

### Document

```dart
class Document {
  final String id;
  final String title;
  final String sourceType;
  final String? summary;
  final List<DocumentTag> tags;
  final DocumentStatus status;
  final String? rawText;
  final String? errorMessage;
  final DateTime createdAt;
  final DateTime updatedAt;
}
```

### Citation

```dart
class Citation {
  final String documentId;
  final String documentTitle;
  final String chunkId;
  final String text;
  final int? pageNumber;
  final double? score;
}
```

### ChatScope

```dart
class ChatScope {
  final List<String> documentIds;
  final List<String> tags;
  final List<String> sourceTypes;
}
```

### Job

```dart
class Job {
  final String id;
  final String? documentId;
  final String jobType;
  final String status;
  final int progress;
  final String? message;
  final String? errorMessage;
}
```

### AuthSessionInfo

```dart
class AuthSessionInfo {
  final String id;
  final String? clientName;
  final DateTime createdAt;
  final DateTime expiresAt;
  final bool isCurrent;
}
```

### AuthConfig

```dart
class AuthConfig {
  final bool registrationEnabled;
  final bool invitationRequired;
}
```

## API 对齐清单

### 认证

- [x] 登录页依赖 `POST /auth/login`
- [x] 注册页依赖 `POST /auth/register`
- [x] 登录和注册入口依赖 `GET /auth/config` 获取注册策略
- [x] 启动页依赖 `GET /auth/me`
- [x] 路由只在认证启动初始化期间进入 `/loading`，交互提交保持当前页面
- [x] 当前设备退出依赖 `POST /auth/logout`
- [x] 登录设备列表依赖 `GET /auth/sessions`
- [x] 选择性设备退出依赖 `DELETE /auth/sessions/{session_id}`
- [x] 删除账号依赖 `DELETE /auth/account`
- [x] 修改密码依赖 `POST /auth/change-password`
- [x] 全设备退出依赖 `POST /auth/logout-all`
- [x] 管理员邀请码列表依赖 `GET /auth/registration-invites`
- [x] 管理员创建邀请码依赖 `POST /auth/registration-invites`
- [x] 管理员撤销邀请码依赖 `DELETE /auth/registration-invites/{invite_id}`

### 资料

- [x] 首页最近资料依赖 `GET /documents`
- [x] 资料库依赖 `GET /documents`
- [x] 资料详情依赖 `GET /documents/{document_id}`
- [x] 创建笔记依赖 `POST /documents/note`
- [x] 上传资料依赖 `POST /documents/upload`
- [x] 删除资料依赖 `DELETE /documents/{document_id}`

### 问答

- [x] 提问页依赖 `POST /chat/query`
- [x] 引用来源依赖 chat response 中的 `citations`
- [x] 推荐追问依赖 chat response 中的 `suggested_questions`

### 整理

- [x] 单份资料整理依赖 `POST /organize/document`
- [x] 多份资料整理依赖 `POST /organize/collection`
- [x] 保存整理结果依赖 `POST /documents/note`

### 任务状态

- [x] 上传进度页依赖 `GET /jobs/{job_id}`
- [x] 资料库状态依赖 document 的 `status`

## 第一版交互优先级

### 必须做

- [x] 登录注册
- [x] 首页快捷入口
- [x] 创建笔记
- [x] 资料列表
- [x] 资料详情
- [x] 提问聊天页
- [x] 回答引用来源展示
- [x] 文件上传
- [x] 任务状态展示

### 可以稍后做

- [x] 复杂标签管理
- [x] 批量选择资料
- [x] 精确跳转到引用片段
- [x] 聊天会话列表
- [x] 加密离线缓存和断网回退
- [x] 图片 OCR Provider
- [x] 实时麦克风语音输入

## 空状态和错误状态

### 资料库为空

文案：

```text
还没有资料
先记一条笔记，或者上传一份学习资料。
```

操作：

```text
记一条
上传资料
```

### 提问时没有资料

文案：

```text
还没有可提问的资料
添加资料并完成索引后，就可以向它提问。
```

操作：

```text
添加资料
```

### 资料正在索引

文案：

```text
资料正在建立索引
完成后即可提问。
```

操作：

```text
查看进度
```

### 回答没有找到依据

文案：

```text
我在你的资料中没有找到足够依据。
可以换个问法，或添加更多相关资料。
```

操作：

```text
继续追问
添加资料
```

## App 开发顺序

### 阶段 1：工程和基础能力

- [x] 初始化 Flutter 项目
- [x] 配置主题
- [x] 配置路由
- [x] 配置 Dio
- [x] 配置 token 存储
- [x] 配置登录态判断

### 阶段 2：资料闭环

- [x] 创建笔记页
- [x] 资料库页
- [x] 资料详情页
- [x] 首页最近资料
- [x] 上传资料页
- [x] 任务进度页

### 阶段 3：问答闭环

- [x] 提问页
- [x] scope 选择
- [x] 消息列表
- [x] 引用来源卡片
- [x] 推荐追问
- [x] 错误和重试状态

### 阶段 4：整理闭环

- [x] 整理页
- [x] 整理对象选择
- [x] 整理方式选择
- [x] 整理结果页
- [x] 保存为笔记

## 和后端的关键约定

- document 的 `status` 必须稳定，App 会直接用于状态展示和按钮可用性判断。
- chat response 必须包含 `answer`、`citations`、`suggested_questions`。
- 历史详情和实时提问状态都最多持有 200 条消息；窗口裁剪只影响客户端展示，完整消息仍由后端会话保存。
- citation 至少需要 `document_id`、`document_title`、`chunk_id`、`text`。
- 上传接口最好返回 `document_id` 和 `job_id`，方便 App 立刻展示处理进度。
- 页面列表接口继续支持页码分页；标签总数可通过 `X-Total-Count` 响应头返回。标签和资料选择器的完整遍历使用 `items + next_cursor` 的 keyset scan。会话详情使用独立的最近消息降序游标，首屏 50 条，更早页在客户端前插；内存窗口最多 200 条，超过后丢弃较新端并提供“返回最近消息”。下一请求必须把非空 cursor 原样带回同一路径并保持筛选条件不变，不能通过递增 page 扫描到任意深度。
- 所有接口错误返回需要包含稳定的 `message` 字段。
