# 个人 AI 知识助手 MVP 任务清单

## 产品目标

做一个移动端优先的个人知识助手，支持用户上传和保存个人笔记、学习资料、灵感和文档。系统能够解析资料、切片、建立向量索引，并基于用户自己的资料进行问答、整理、归纳和联想。

关键技术和产品决策见：[项目关键决策记录](./project-decisions.md)。

## MVP 原则

第一阶段不要追求完整 App，而是先跑通一个最小 RAG 闭环：

```text
创建笔记
  -> 清洗文本
  -> 文本切片
  -> 生成 embedding
  -> 检索相关片段
  -> 基于片段生成回答
  -> 返回引用来源
```

## 版本里程碑

移动端结构、页面交互和前后端对齐细节见：[Flutter App 结构与页面交互设计](./flutter-app-structure.md)。

### v0.1：笔记问答闭环

- [x] 初始化 FastAPI 后端项目
- [x] 配置 PostgreSQL 数据库连接
- [x] 配置 pgvector 向量扩展
- [x] 添加 Alembic 数据库迁移
- [x] 添加用户模型和基础认证
- [x] 添加资料模型
- [x] 添加资料切片模型
- [x] 添加切片向量模型
- [x] 添加会话和消息模型
- [x] 实现创建笔记接口
- [x] 实现资料列表接口
- [x] 实现资料详情接口
- [x] 实现文本清洗
- [x] 实现文本切片
- [x] 实现 embedding provider 抽象层
- [x] 为笔记切片生成 embedding
- [x] 实现向量检索
- [x] 实现提问接口
- [x] 用检索到的片段构建 prompt
- [x] 实现 LLM provider 抽象层并生成回答
- [x] 回答返回引用来源
- [x] 保存会话和消息记录

### v0.2：文件资料

- [x] 添加本地文件存储
- [x] 实现文件上传接口
- [x] 支持 TXT 解析
- [x] 支持 Markdown 解析
- [x] 支持 PDF 解析
- [x] 支持 DOCX、HTML、Excel（xlsx）和 EPUB 解析
- [x] 扫描版 PDF 逐页混合处理：只对没有足够文字的页回退 OCR Provider，并限制单次 OCR 页数
- [x] 添加资料处理状态流转
- [x] 添加异步任务表
- [x] 添加任务状态查询接口
- [x] 使用后台任务处理资料
- [x] 清晰展示解析或索引失败原因
- [x] 支持限定某一份资料进行问答

### v0.3：整理能力

- [x] 生成资料摘要
- [x] 生成资料标签
- [x] 添加标签表
- [x] 添加资料和标签关系表
- [x] 支持重命名和删除标签
- [x] 实现单份资料总结接口
- [x] 实现单份资料大纲接口
- [x] 实现知识点提取接口
- [x] 实现多资料整理接口
- [x] 实现主题归纳模式
- [x] 实现资料关联分析模式
- [x] 支持将 AI 整理结果保存为新笔记

### v0.4：移动端 App

- [x] 初始化 Flutter App 源码骨架
- [x] 添加后端 API 客户端
- [x] 添加登录流程
- [x] 启动认证临时失败时保留 token 并支持重试原深链接
- [x] 登录和注册提交期间保留当前表单，失败后不丢失用户输入
- [x] 添加注册流程
- [x] 构建首页
- [x] 首页最近资料和最近问答失败时支持互不影响的区块级重试
- [x] 构建资料库页面
- [x] 资料库支持按标签筛选
- [x] 资料库支持关键词搜索
- [x] 构建资料详情页面
- [x] 资料详情展示来源类型、处理状态和失败原因
- [x] 资料详情支持编辑标题和标签
- [x] 资料详情支持删除资料
- [x] 资料库支持批量选择、批量改标签和批量删除
- [x] 构建创建笔记流程
- [x] 构建文件上传流程
- [x] 上传资料时支持编辑标题和选择标签
- [x] 构建提问聊天页面
- [x] 提问页支持多轮消息展示
- [x] 提问失败后支持保留范围并一键重试
- [x] 提问页支持查看会话历史
- [x] 提问页支持查看历史会话消息
- [x] 提问页支持从历史会话继续提问
- [x] 从历史会话继续提问时恢复并显示原问答范围
- [x] 会话历史支持搜索、重命名和删除
- [x] 提问页支持按标签限定问答范围
- [x] 提问页支持按具体资料限定问答范围
- [x] 展示回答引用来源
- [x] 引用来源支持点击打开原资料
- [x] 引用来源打开资料时展示并高亮引用片段
- [x] 引用来源支持按 chunk offset 精确定位并滚动到原文片段
- [x] 构建整理页面
- [x] 整理页支持文章大纲和按来源资料继续追问
- [x] 整理页支持按标签限定整理范围
- [x] 整理页支持手动多选资料限定整理范围
- [x] 整理结果保存为笔记后可直接打开
- [x] 构建账号和设置页面
- [x] 模型设置页展示后端运行配置
- [x] 模型设置页支持编辑 provider、模型、Base URL、API Key，并展示固定 embedding 维度
- [x] 文档索引后自动生成摘要和标签
- [x] 支持配置 OpenAI-compatible 图片 OCR 和语音转文字 Provider
- [x] GET 数据使用加密本地缓存并支持断网回退
- [x] 资料详情整理结果支持保存为新笔记
- [x] 实时麦克风录音和语音提问
- [x] S3 / OSS / MinIO 对象存储后端
- [x] 构建标签管理页面
- [x] 展示上传和索引进度
- [x] 资料详情一键进入限定当前资料的提问
- [x] 资料详情查找并打开相关资料
- [x] 引用展示来源类型、页码或段落及相关度
- [x] 资料统计不依赖列表第一页
- [x] 资料统计包含上传文件实际占用字节数
- [x] “我的”页资料统计失败时隐藏底层异常并提供重试
- [x] 拒绝纯空白笔记、问题、标题和标签
- [x] 未处理异常返回不泄露内部细节的稳定 JSON
- [x] Flutter 统一隐藏传输、存储和插件异常，只展示结构化业务消息或稳定兜底
- [x] 问答和整理页首屏只加载有界资料与标签快捷项，完整选择使用服务端搜索和分页
- [x] 会话历史搜索覆盖全部分页数据
- [x] 会话搜索使用防抖避免逐字符重复请求
- [x] 显式整理范围无资料时不回退到其它资料
- [x] 资料详情保存整理结果时保留 AI 来源类型和来源资料
- [x] 资料删除后遗留的后台任务进入明确失败状态
- [x] 资料列表标签使用批量查询避免 N+1
- [x] 多资料整理限制资料数量和模型上下文规模
- [x] Embedding 配置变化由后端自动创建全用户索引重建任务
- [x] 全用户索引重建串行执行并支持服务恢复
- [x] 长任务使用独立心跳避免被恢复机制重复领取
- [x] 任务历史支持用户隔离、状态筛选和分页
- [x] readiness 检查数据库、pgvector 扩展和向量索引
- [x] 等待中和运行中任务支持协作式取消
- [x] 失败和已取消任务支持创建新任务重试
- [x] 过期认证会话、旧限流记录和终态任务历史在启动及周期恢复时统一限批清理
- [x] 任务历史维护使用更新时间复合索引，并通过 PostgreSQL 并发迁移上线
- [x] 恢复候选和任务历史分页使用匹配索引，分页排序包含唯一任务 ID
- [x] 资料、会话、消息和邀请码分页使用唯一稳定排序与匹配复合索引
- [x] 资料与会话模糊搜索使用 trigram 索引，LIKE 元字符按字面量处理
- [x] 资料标签筛选显式约束 tag owner 并使用完整关联索引链路
- [x] 混合检索关键词候选使用双 GIN 分支，并在限批前执行全局等价评分
- [x] HNSW 作用域过滤使用有界 iterative scan，避免近邻先过滤后不足 top-k
- [x] readiness 验证 HNSW 有效性、列、维度和距离 opclass，不只检查索引名
- [x] HNSW 使用显式构建参数和可恢复的并发替换迁移，升级期间保留可用索引
- [x] 页码 OFFSET 在 SQL 前限制工作量，标签、消息和可选资料的完整遍历使用 keyset cursor
- [x] 标签合并和删除使用集合化 SQL 与数据库级联，不物化无界资料关联
- [x] 文件向量化使用有界内存 spool 和分批持久化，同时保持旧索引原子替换
- [x] 单用户和全用户索引重建使用轻量 keyset 批次，不一次加载全部资料或失败文本
- [x] worker 状态转换使用前置状态条件，避免取消与启动、进度或失败写入互相覆盖
- [x] 重试任务记录来源任务，历史列表和详情明确标识重试链路
- [x] 全局重建锁使用专用数据库连接，避免业务提交导致 session-level lock 泄漏
- [x] 普通 worker 和恢复 worker 使用不同领取前置状态，重复执行者无副作用退出
- [x] 任务执行使用 run token fencing，恢复领取后旧 worker 不能继续写入
- [x] 服务运行期间周期扫描 stale 任务，无需依赖进程重启触发恢复
- [x] readiness 暴露恢复 supervisor 状态、最近扫描时间和连续失败次数
- [x] 恢复扫描使用可配置批量上限，并暴露派发数和活动 worker 数
- [x] 恢复调度使用进程内全局并发上限，跨扫描周期只领取剩余容量
- [x] 启动和周期恢复 worker 统一注册，并在服务关闭时限时等待收敛
- [x] 恢复清理和认领移出事件循环，关闭竞态不会遗留无 worker 的租约
- [x] readiness 监控恢复扫描耗时和成功 freshness，并返回稳定降级原因
- [x] 恢复清理和认领使用事务级 PostgreSQL statement timeout
- [x] 数据库 engine 配置连接建立和连接池等待超时
- [x] readiness 和 capabilities 数据库查询使用独立 statement timeout
- [x] readiness 暴露连接池容量与利用率，并在池饱和时快速失败
- [x] 所有运行时数据库连接使用默认 statement timeout，场景事务可覆盖
- [x] 数据库连接、SQL 和连接池超时统一返回可重试的稳定 503
- [x] Flutter 白名单 GET 遇到 503 时回退缓存，写请求保持失败
- [x] Flutter 全局提示离线缓存与服务不可用缓存来源
- [x] Flutter 缓存回退横幅持续显示来源与缓存更新时间，实时请求恢复后自动隐藏
- [x] Flutter 缓存回退横幅支持去重的 readiness 主动重连，失败时保持缓存提示
- [x] readiness 恢复后重验证缓存 API provider，真实业务 GET 成功前不隐藏横幅
- [x] 缓存重验证按代次跟踪全部活动请求，部分回退和响应乱序不误清横幅
- [x] Flutter 加密缓存串行维护索引，注销清理不遗漏并发写入条目
- [x] Flutter 缓存键使用 token SHA-256 指纹隔离账号，清理失败也不能跨会话读取
- [x] Flutter 缓存索引记录时间与字节数，按 64 条和 4 MiB 上限自动回收
- [x] Flutter 缓存读写清理使用 2 秒调用预算，安全存储挂起不阻塞业务
- [x] Flutter token 读写删除使用 2 秒调用预算，注销超时仍结束内存会话
- [x] Flutter token 操作串行，保存超时的晚到写入条件回滚且不误删新 token
- [x] 非本地环境启动时校验 JWT 密钥强度和 token 有效期范围
- [x] 登录失败使用 PostgreSQL 共享账号和客户端限流，并隐藏账号存在性时序差异
- [x] 新密码使用 Argon2id，旧 PBKDF2 用户成功登录时原子升级哈希
- [x] 并发注册唯一键冲突回滚并稳定返回 409，不泄露数据库异常
- [x] 注册入口使用 PostgreSQL 共享客户端额度，在 Argon2 前原子限流
- [x] JWT 绑定可撤销数据库会话，Flutter 在线退出撤销当前设备 token
- [x] 修改密码原子撤销旧会话并替换当前 token，支持退出所有设备
- [x] 登录设备列表标记当前会话，并支持选择性远程退出其它设备
- [x] 非本地环境默认关闭公开注册，Flutter 不预填开发账号并按后端策略显示注册入口
- [x] 生产开放注册时默认要求一次性邀请码，并在事务内防止并发复用
- [x] 管理员可分页筛选、创建和撤销注册邀请码，原码只展示一次
- [x] 所有用户业务数据通过数据库外键引用真实用户，并阻止绕过受控清理直接删除用户
- [x] 资料删除使用持久化对象存储 outbox，支持多实例租约、退避重试和 readiness 降级
- [x] 文件资料持久化上传时的存储后端和位置快照，删除时不从当前配置猜测来源
- [x] 文件解析校验上传时的存储来源，配置切换后不读取新命名空间中的同 key 对象
- [x] 提供只读存储一致性审计，区分缺失引用、待删除对象、非法 key 和孤立对象
- [x] 孤立对象按精确 key 二次审计，显式确认后通过持久 outbox 处置
- [x] 对象删除 outbox 按 backend、scope 和 key 数据库级去重，并发入队保持幂等
- [x] readiness 聚合共享 outbox 持久失败与 abandoned lease，重启和多实例不误报健康
- [x] 失败或 abandoned 删除任务支持按精确 key 安全重排到数据库当前时间
- [x] 后台任务持久错误使用显式公开类型和阶段兜底，不向客户端泄露内部异常
- [x] API 路由只公开命名业务异常，不把内置 ValueError、LookupError 或 PermissionError 原文返回客户端
- [x] 422 校验响应删除原始 input、ctx 和错误 URL，不回显密码、邀请码或模型 API Key
- [x] 422 校验消息按错误类型映射稳定中文，不依赖 Pydantic 英文原文或版本措辞
- [x] 全部 API 响应统一禁止浏览器和代理缓存，个人数据只由 Flutter 加密缓存管理
- [x] 本地运行时模型设置串行写入并原子替换 .env，失败不截断旧配置或污染内存状态
- [x] Embedding 配置指纹持久协调，数据库恢复、服务重启或配置回切后正确补建全用户重建任务
- [x] 文件资料、标签和索引任务单事务提交，恢复扫描补建旧 uploaded 无任务资料
- [x] 请求集合和数据库字符串字段统一设限，上传元数据在文件落盘前完成校验
- [x] 聊天标签和来源范围下推到检索 SQL，避免按标签物化无界资料 ID 列表
- [x] ASGI 层限制完整请求体字节数，笔记与整理结果正文统一限制字符数
- [x] 同步 Embedding/LLM 调用与数据库事务分离，笔记计算后单事务落库
- [x] 后台解析、Embedding 和富化 Provider 调用前释放 worker 数据库连接
- [x] LLM 业务文本在持久化前统一设限，历史消息列表使用有界正文投影并显式标记截断
- [x] 会话详情从最近页按需加载更早消息，客户端历史窗口保持有界
- [x] 实时提问状态只保留最近 200 条消息，并在裁剪后提供历史入口
- [x] 标签管理、资料筛选及问答/整理选择器使用服务端搜索和分页，不自动遍历完整目录
- [x] 整理、相关资料和删除等非详情工作流使用资料窄行投影，删除依赖数据库级联而不加载完整切片集合
- [x] 向量与关键词检索只返回有界切片窄行，上下文总长度包含首条和分隔符的硬边界
- [x] 整理与自动富化共享轻量上下文切片查询，历史宽切片在进入 Python 前截断
- [x] 任务消息和错误在写入、历史列表、详情及路由响应四层保持有界，并排除私有运行字段
- [x] 资料详情只传输一份 canonical 正文并排除存储 key 与 metadata，标题/标签更新不加载正文
- [x] 大资料详情正文按 50,000 字符窗口加载，深层引用保持全局 offset 精确定位
- [x] 会话目录、消息归属检查及回合写回使用窄投影，删除依赖数据库级联而不加载历史消息集合
- [x] 历史消息引用按 8 项结构化窄投影，字段在 SQL、schema 与新写入三层保持有界
- [x] 会话详情与继续提问按结构化 scope 投影，历史额外键、超量数组和非法值不进入 ORM
- [x] 登录、改密和用户公开资料使用头像有界投影，重复注册与账号删除只读取必要用户字段
- [x] 受保护请求使用单查询会话/用户存在性窄投影，认证依赖不加载 User 或 AuthSession ORM
- [x] 普通用户可在当前密码确认后永久删除账号、全部业务数据和登录会话

## 后端开发顺序

### 阶段 1：后端基础工程

- [x] 创建 `backend/` 项目结构
- [x] 添加 `app/main.py`
- [x] 添加 `core/config.py`
- [x] 添加 `core/database.py`
- [x] 添加 `api/router.py`
- [x] 添加健康检查接口
- [x] 添加 SQLAlchemy 基础模型配置
- [x] 添加 Alembic 配置
- [x] 创建第一版数据库迁移

### 阶段 2：资料和笔记

- [x] 添加 `documents` 表
- [x] 添加资料相关 schemas
- [x] 添加资料 service
- [x] 添加创建笔记接口
- [x] 添加资料列表接口
- [x] 添加资料详情接口
- [x] 添加删除资料接口
- [x] 添加资料状态枚举

### 阶段 3：文本切片 Pipeline

- [x] 添加 `document_chunks` 表
- [x] 添加文本清洗工具
- [x] 添加 chunker 模块
- [x] 实现 chunk 长度和 overlap 规则
- [x] 保存 chunk_index
- [x] 保存 chunk 在原文中的位置
- [x] 保存 chunk 字符数或 token 数
- [x] 创建笔记后自动触发切片

### 阶段 4：Embedding 和检索

- [x] 添加 `chunk_embeddings` 表
- [x] 添加 embedding provider 接口
- [x] 添加第一个 embedding provider 实现
- [x] 支持批量生成 embedding
- [x] 将向量存入 pgvector
- [x] 添加向量索引迁移
- [x] 实现向量检索
- [x] 支持按用户和资料做 metadata 过滤
- [x] 添加 retrieval service

### 阶段 5：问答和引用

- [x] 添加 `conversations` 表
- [x] 添加 `messages` 表
- [x] 添加 chat schemas
- [x] 添加 LLM provider 接口
- [x] 添加问答 prompt 模板
- [x] 添加 context builder
- [x] 添加 citation builder
- [x] 实现 `/chat/query`
- [x] 保存用户问题
- [x] 保存 AI 回答
- [x] 返回答案、引用来源和推荐追问

### 阶段 6：文件上传和任务状态

- [x] 添加本地存储 service
- [x] 添加上传接口
- [x] 保存原始文件 metadata
- [x] 解析 TXT
- [x] 解析 Markdown
- [x] 解析 PDF
- [x] 添加 `jobs` 表
- [x] 添加 job service
- [x] 添加 `/jobs/{job_id}`
- [x] Pipeline 中实时更新资料处理状态
- [x] 向 App 返回处理进度

### 阶段 7：整理功能

- [x] 添加总结 prompt
- [x] 添加大纲 prompt
- [x] 添加知识点 prompt
- [x] 添加多资料整理 prompt
- [x] 实现 `/organize/document`
- [x] 实现 `/organize/collection`
- [x] 支持将整理结果保存为笔记

## 推荐后端目录结构

```text
backend/
  app/
    main.py
    core/
      config.py
      database.py
      security.py
      exceptions.py
    api/
      deps.py
      router.py
      routes/
        auth.py
        documents.py
        chat.py
        organize.py
        jobs.py
        tags.py
    models/
      user.py
      document.py
      chunk.py
      embedding.py
      tag.py
      conversation.py
      message.py
      job.py
    schemas/
      auth.py
      document.py
      chat.py
      organize.py
      job.py
      tag.py
    services/
      auth_service.py
      document_service.py
      parsing_service.py
      chunking_service.py
      embedding_service.py
      retrieval_service.py
      chat_service.py
      organize_service.py
      job_service.py
    ai/
      llm_provider.py
      embedding_provider.py
      prompts/
        qa.py
        summarize.py
        organize.py
        intent.py
    rag/
      chunker.py
      retriever.py
      reranker.py
      context_builder.py
      citation_builder.py
    storage/
      local_storage.py
    workers/
      document_pipeline.py
    utils/
      text_cleaner.py
      hash.py
      tokens.py
  alembic/
  tests/
  requirements.txt
  .env.example
```

## 数据模型清单

- [x] `users`：用户表
- [x] `documents`：资料表
- [x] `document_chunks`：资料切片表
- [x] `chunk_embeddings`：切片向量表
- [x] `tags`：标签表
- [x] `document_tags`：资料标签关系表
- [x] `conversations`：会话表
- [x] `messages`：消息表
- [x] `jobs`：异步任务表
- [x] `auth_sessions`：可撤销登录会话及可选客户端平台名称
- [x] `auth_registration_invites`：只保存摘要、到期、使用和撤销状态的一次性注册邀请码
- [x] `storage_deletions`：保存对象存储来源快照、有限租约和退避状态的删除 outbox
- [x] `embedding_configuration_state`：保存已持久协调的 Embedding 配置指纹

## API 清单

- [x] `POST /auth/register`：注册
- [x] `POST /auth/login`：登录
- [x] `GET /auth/config`：公开查询是否允许注册，不暴露认证配置
- [x] `GET /auth/me`：获取当前用户
- [x] `POST /auth/logout`：撤销当前登录会话
- [x] `POST /auth/logout-all`：撤销当前用户全部登录会话
- [x] `POST /auth/change-password`：改密并换发当前设备 token
- [x] `GET /auth/sessions`：查询当前用户有效登录设备
- [x] `DELETE /auth/sessions/{session_id}`：选择性撤销指定登录设备
- [x] `DELETE /auth/account`：校验当前密码并永久删除普通用户账号与全部数据
- [x] `GET /auth/registration-invites`：管理员分页和按状态查询注册邀请码
- [x] `POST /auth/registration-invites`：管理员创建一次性注册邀请码并返回一次原码
- [x] `DELETE /auth/registration-invites/{invite_id}`：管理员幂等撤销有效邀请码
- [x] `POST /documents/note`：创建笔记
- [x] `POST /documents/upload`：上传资料
- [x] `GET /documents`：资料列表
- [x] `GET /documents/scan`：使用不透明游标完整遍历筛选后的资料
- [x] `GET /documents/stats`：资料总量和状态统计
- [x] `GET /documents/{document_id}`：资料详情
- [x] `GET /documents/{document_id}/related`：查询相关资料
- [x] `PATCH /documents/{document_id}`：更新资料标题和标签
- [x] `DELETE /documents/{document_id}`：删除资料
- [x] `GET /tags`：标签列表
- [x] `GET /tags/scan`：使用不透明游标完整遍历标签
- [x] `PATCH /tags/{tag_id}`：重命名标签
- [x] `DELETE /tags/{tag_id}`：删除标签
- [x] `GET /settings/runtime`：运行时模型配置
- [x] `PATCH /settings/runtime`：更新运行时模型配置、写入 `.env` 并在需要时返回全用户重建任务
- [x] `POST /jobs/rebuild-all-embeddings`：管理员手动重建所有用户的资料索引
- [x] `POST /chat/query`：基于资料提问
- [x] `GET /chat/conversations`：分页查询会话
- [x] `GET /chat/conversations/{conversation_id}`：查询会话及问答范围
- [x] `GET /chat/conversations/{conversation_id}/messages`：分页查询消息
- [x] `GET /chat/conversations/{conversation_id}/messages/scan`：使用不透明游标完整遍历消息
- [x] `GET /chat/conversations/{conversation_id}/messages/recent`：从最新位置按不透明游标加载更早消息
- [x] `PATCH /chat/conversations/{conversation_id}`：重命名会话
- [x] `DELETE /chat/conversations/{conversation_id}`：删除会话
- [x] `POST /organize/document`：整理单份资料
- [x] `POST /organize/collection`：整理多份资料
- [x] `POST /organize/save-result`：保存已生成的整理结果并保留来源
- [x] `GET /jobs/{job_id}`：查询任务状态
- [x] `GET /jobs`：分页查询当前用户任务历史
- [x] `GET /health/ready`：检查数据库和向量检索依赖
- [x] `POST /jobs/{job_id}/cancel`：安全取消等待中或运行中的任务
- [x] `POST /jobs/{job_id}/retry`：重试失败或已取消任务

## RAG 策略清单

- [x] 切片前先清洗文本
- [x] 切片优先使用语义或结构边界
- [x] 默认 chunk 大小使用 600-900 个中文字符
- [x] 默认 overlap 使用 100-150 个中文字符
- [x] 每个 chunk 保存来源 metadata
- [x] 为每个 chunk 生成 embedding
- [x] 使用向量相似度检索
- [x] 实现关键词检索并与向量结果合并
- [x] 实现 rerank 重排和最低相关度过滤
- [x] 支持可选的 Cohere/Jina 兼容模型 Rerank Provider，失败时自动退回启发式重排
- [x] 根据 top chunks 构建回答上下文
- [x] 约束回答只能基于提供的资料
- [x] 返回资料引用来源
- [x] 资料不足时明确说明无法确定

## 待决策问题

- [x] 选择第一版 LLM provider：使用 OpenAI-compatible provider 抽象
- [x] 选择第一版 embedding 模型和向量维度：默认 `text-embedding-3-small`，`1536` 维
- [x] 决定 v0.1 是否包含登录注册，还是先用单用户模式：v0.1 先用单用户模式
- [x] 决定是否先做一个极简 Web 页面，再做 Flutter App：先用后端 Swagger 或极简调试页验证，再接 Flutter
- [x] 决定早期测试使用本地存储还是 S3 兼容对象存储：早期使用本地存储
- [x] 决定 MVP 只支持中文，还是一开始支持多语言：MVP 中文优先
