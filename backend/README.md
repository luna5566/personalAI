# 后端服务

这是个人 AI 知识助手的 FastAPI 后端。

## 当前状态

已完成 MVP 后端闭环：

- 严格 Bearer 认证和用户数据隔离
- 笔记、TXT、Markdown、PDF、图片 OCR 和音频转写资料处理
- 文本清洗、分页切片、embedding、关键词混合检索和 rerank
- 最低相关度过滤、引用来源、页码/offset 定位和多轮会话
- 自动摘要、自动标签、单篇及多资料整理
- 带心跳和历史分页的可恢复后台任务、资料统计和列表接口
- local / S3-compatible 存储及 OpenAI-compatible 模型 Provider
- 稳定 JSON 错误响应和管理员运行时设置
- 管理员一次性注册邀请码的创建、分页筛选和撤销
- Embedding 配置变化后的全用户索引重建和任务恢复

## 本地启动

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

健康检查：

```text
GET http://127.0.0.1:8000/api/health
```

存活检查不访问外部依赖；接入流量前应使用 readiness 检查数据库、pgvector 扩展、HNSW 索引、任务恢复 supervisor 和对象存储删除 supervisor：

```text
GET http://127.0.0.1:8000/api/health/ready
```

依赖不可用、连接池饱和、任一 supervisor 已停止、扫描或删除批次失败、单次处理超时或最近成功结果过期时，readiness 返回 `503` 和稳定状态字段，不返回内部异常。连接池由 `DATABASE_POOL_SIZE`（默认 5）和 `DATABASE_POOL_MAX_OVERFLOW`（默认 10）定义总容量；响应返回 checked-in、checked-out、overflow、利用率和 saturated 状态，饱和时不再等待 checkout。所有运行时连接默认使用 `DATABASE_STATEMENT_TIMEOUT_SECONDS`（默认 30 秒），普通 API、worker 和原始 engine 连接都不会无限等待；health、恢复和存储删除事务再分别覆盖为自己的场景上限。readiness 同时返回存储删除最近领取、完成、失败数量和 freshness，便于区分队列空闲、外部删除失败与 supervisor 停止。

readiness 还在同一个 health 数据库事务内聚合共享 `storage_deletions`，返回 `storage_deletion_queue_pending`、`failed`、`abandoned`、`active_leases`、`eligible`、最早创建时间和最早下次尝试时间。`last_error` 非空的持久失败会以 `persistent_deletion_failed` 让所有实例降级；已经尝试、没有错误记录且租约已释放或过期的任务以 `abandoned_deletion_lease` 降级。刚入队且 `attempts=0` 的普通任务、有效租约中的首次处理不会单独使 readiness 失败。数据库不可用或连接池已饱和时这些共享字段为 `null`，整体 readiness 已由数据库状态返回 `503`。

修复外部存储或恢复原配置后，可以先按精确 key 只读检查失败任务：

```powershell
.\.venv\Scripts\python.exe scripts\retry_storage_deletion.py documents/<exact-key>
```

状态为 `failed_backoff` 或 `abandoned_backoff` 时，显式把下次尝试重排到数据库当前时间：

```powershell
.\.venv\Scripts\python.exe scripts\retry_storage_deletion.py documents/<exact-key> --retry
```

命令只查询当前 backend/scope，不展开通配符。它用 `FOR UPDATE` 锁定任务，只允许已经尝试、没有有效 lease 且仍处于未来退避的行；`active_lease`、`invalid_lease`、`not_attempted`、`not_found` 和非法 key 都不修改。重排保留 attempts 与 `last_error`，只更新 `next_attempt_at` 并清理已经过期的 lease，不直接执行对象删除。任务已经 `eligible` 时无需重写。运行中的 supervisor 会在下一扫描周期领取；CLI 不绕过批量上限、租约或 provenance guard。

普通 API 遇到数据库连接失败、statement timeout 或连接池 checkout timeout 时统一返回 `503`，响应体为稳定的 `message/detail`，并通过 `Retry-After` 指示重试等待秒数；默认由 `DATABASE_RETRY_AFTER_SECONDS=5` 配置。响应和警告日志都不包含原始 SQL、参数、数据库 URL 或凭据。

## 认证

当前支持：

```text
GET /api/auth/config
POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
POST /api/auth/logout-all
POST /api/auth/change-password
GET /api/auth/sessions
DELETE /api/auth/sessions/{session_id}
GET /api/auth/registration-invites
POST /api/auth/registration-invites
DELETE /api/auth/registration-invites/{invite_id}
GET /api/auth/me
```

`GET /auth/config` 是无需登录的最小能力接口，只返回 `registration_enabled` 和有效的 `invitation_required`，并带 `Cache-Control: no-store`；不会返回环境名、密钥、限流参数或账号信息。未显式配置 `AUTH_REGISTRATION_ENABLED` 时，`local/test` 环境默认开放注册，其它环境默认关闭。生产确需开放时必须明确设置：

```text
AUTH_REGISTRATION_ENABLED=true
```

生产环境显式开放注册后，未配置 `AUTH_REGISTRATION_INVITE_REQUIRED` 时默认要求一次性邀请码；`local/test` 默认不要求。只有明确设置下面组合才会开放无邀请注册：

```text
AUTH_REGISTRATION_ENABLED=true
AUTH_REGISTRATION_INVITE_REQUIRED=false
```

关闭注册只阻止创建新账号，不影响已有账号登录。被关闭的 `POST /auth/register` 在进入共享限流、用户查询和 Argon2 前返回稳定 `403` 与“当前不开放新账号注册”。Flutter 根据能力接口决定是否显示注册入口，登录字段不会预填仓库内置的本地账号或密码；本地开发账号仍可按下文手动输入。

管理员可以在 Flutter“我的 > 注册邀请码”中创建和管理邀请码，也可以通过管理脚本创建；脚本默认有效 168 小时，并支持指定正整数小时：

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\create_registration_invite.py --valid-hours 168
```

管理 API 只允许 `RUNTIME_SETTINGS_ADMIN_USER_ID` 对应用户访问。`GET /auth/registration-invites` 支持 `page`、`page_size` 和 `status=active|used|expired|revoked`，`POST` 接受 1–8760 小时有效期，`DELETE` 只撤销仍有效的邀请码；首次和重复撤销都返回 `204`，已使用或已过期返回 `409`。列表和创建响应使用 `Cache-Control: no-store`。

原始邀请码只在脚本输出或创建 API 响应中出现一次，后续列表不会返回原码或摘要。数据库只保存使用 `AUTH_SECRET_KEY` 计算的 HMAC-SHA256 摘要、到期、使用和撤销时间。注册请求在 `invite_code` 字段提交；缺失、未知、过期、已使用或已撤销的邀请码统一返回 `403` 与“邀请码无效或已过期”。有效邀请码使用行锁读取，并和用户、首个会话及 `used_at` 在同一事务提交，因此并发复用只能成功一次。轮换 `AUTH_SECRET_KEY` 会同时使尚未使用的邀请码失效，轮换后需要重新生成。

注册成功返回 `201`。邮箱已经存在时，无论是在注册前检查发现，还是多个实例并发插入触发 `uq_users_email` 唯一约束，都返回稳定的 `409` 和“邮箱已注册”；并发失败事务会先回滚，响应不包含 SQL、约束诊断或密码哈希。其它完整性错误不会伪装成邮箱重复。

注册入口还使用 PostgreSQL 共享客户端额度，默认每个 ASGI 客户端地址每小时允许 5 个通过请求体校验的注册请求，第 6 个请求在用户查询和 Argon2 之前返回 `429` 与 `Retry-After: 3600`。重复邮箱和后续数据库失败仍消耗已取得的额度，成功注册不会重置额度；多个进程并发消费也只能有 5 个请求继续。配置项如下：

```text
AUTH_REGISTRATION_CLIENT_MAX_ATTEMPTS=5
AUTH_REGISTRATION_WINDOW_SECONDS=3600
AUTH_REGISTRATION_LOCKOUT_SECONDS=3600
AUTH_REGISTRATION_ATTEMPT_RETENTION_SECONDS=86400
```

注册作用域只保存客户端地址的 HMAC，客户端地址信任规则与登录限流相同。该限制约束单一来源的账号创建与 Argon2 消耗，不替代邮箱验证、邀请制、验证码或针对分布式来源的网关防护。

登录成功返回 Bearer token：

```json
{
  "access_token": "...",
  "token_type": "bearer",
  "user": {
    "id": "...",
    "email": "user@example.com",
    "name": "用户名"
  }
}
```

后续请求可以带：

```text
Authorization: Bearer <access_token>
```

除健康检查、注册和登录外，所有业务接口都必须携带有效 token。缺少 token 或 token 无效时返回 `401`，不会回退到默认用户。

新 token 必须包含用户 `sub`、数据库会话 `jti`、`iat/exp`、固定 `iss/aud` 和 `token_type=access`。每次认证同时校验 JWT 签名与声明、`auth_sessions` 会话是否存在且属于同一用户，以及用户记录是否仍存在；旧版只有 `sub/exp` 的 token 不再兼容，部署本版本后需要重新登录。配置项如下：

```text
AUTH_TOKEN_ISSUER=personal-ai-backend
AUTH_TOKEN_AUDIENCE=personal-ai-client
AUTH_TOKEN_CLOCK_SKEW_SECONDS=30
AUTH_MAX_ACTIVE_SESSIONS_PER_USER=10
```

每个用户最多保留 10 个活跃设备会话；继续登录会按创建时间撤销当前用户最旧的会话，不在认证请求中扫描全表。签发路径先锁定用户行，再用按 `created_at DESC, id DESC` 排序和固定 OFFSET 的 CTE 驱动单条 `DELETE`；历史异常会话再多也不会把全部 ID 拉回应用或构造大 `IN` 参数。过期会话由后台限批维护清理。`POST /auth/logout` 只删除当前 `jti` 对应的会话，同一用户其它设备保持登录；被删除会话的 JWT 即使签名和 `exp` 仍有效也会立即返回 `401`。

客户端可以在注册、登录和改密请求中发送 `X-Client-Name`。后端折叠首尾及连续空白并最多保存 128 个字符，不保存客户端提供的 IP、User-Agent 或设备指纹；未发送该头的历史和兼容客户端显示为未知设备。Flutter 根据运行平台发送 `Personal AI Web/Android/iOS/Windows/macOS/Linux` 等稳定名称。

`GET /auth/sessions` 只返回当前用户尚未过期的会话，按创建时间倒序且最多返回 `AUTH_MAX_ACTIVE_SESSIONS_PER_USER` 项，提供 `id`、`client_name`、`created_at`、`expires_at` 和 `is_current`。`DELETE /auth/sessions/{session_id}` 可以撤销当前用户指定会话并返回 `204`；不存在和属于其它用户的 ID 统一返回 `404`，避免泄露会话归属。Flutter 的设备列表明确标记当前设备，只为其它设备显示选择性退出操作；撤销后重新从服务端加载列表，不使用离线缓存。

Flutter 退出时先携带当前 token 请求服务端注销，最多等待 2 秒，再清除本机 token、加密缓存和内存用户。断网或后端失败不能完成远端撤销，但不会阻止本机退出；这类 token 只能等待过期、服务端会话被其它管理流程删除或最旧会话淘汰。

修改密码请求包含 `current_password` 和至少 6 位的 `new_password`。当前密码错误与登录失败共享账号和客户端限流；新旧密码相同返回 `400`。成功后在同一事务中写入新 Argon2id 哈希、删除全部旧会话并创建一个当前设备替换会话，响应格式与登录相同；客户端必须保存新的 `access_token`。`POST /auth/logout-all` 删除当前用户全部会话并返回 `204`，包括发起请求的当前设备。

`local` 和 `test` 环境可以使用开发密钥；其它环境启动时会拒绝已知占位值以及少于 32 个 UTF-8 字节的 `AUTH_SECRET_KEY`。部署前应生成独立的随机密钥，例如：

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

`ACCESS_TOKEN_EXPIRE_MINUTES` 默认是 10080（7 天），允许范围为 1–43200 分钟。更换认证密钥会立即使此前签发的 token 和会话失去可用凭据。

登录失败限制由 PostgreSQL 跨进程共享，默认在 15 分钟窗口内分别限制同一账号 5 次、同一客户端地址 20 次失败；达到任一阈值时返回 `429` 和 `Retry-After`，阻止 15 分钟。配置项如下：

```text
AUTH_LOGIN_ACCOUNT_MAX_FAILURES=5
AUTH_LOGIN_CLIENT_MAX_FAILURES=20
AUTH_LOGIN_WINDOW_SECONDS=900
AUTH_LOGIN_LOCKOUT_SECONDS=900
AUTH_LOGIN_ATTEMPT_RETENTION_SECONDS=86400
```

数据库只保存账号和客户端地址的 HMAC，不保存原始邮箱或 IP；未知账号也对固定虚拟哈希执行一次密码验证并使用相同失败响应。成功登录只清除账号维度的失败状态，不清除客户端维度。客户端地址直接使用 ASGI 提供的 `request.client.host`，应用不会自行信任 `X-Forwarded-For`；部署在反向代理后时，应通过 Uvicorn 的 `FORWARDED_ALLOW_IPS` 只信任实际代理地址，不能把任意来源加入信任范围。

新注册和新密码哈希使用 Argon2id，固定参数为 19 MiB 内存、2 次迭代、1 路并行；编码后的哈希自带算法版本和成本参数。历史 `pbkdf2_sha256$salt$digest` 哈希继续按原 210,000 次 PBKDF2-HMAC-SHA256 验证，用户下一次成功登录时会在签发 token 前自动改写为当前 Argon2id 格式。错误密码、未知格式或损坏哈希不会触发改写；以后调整 Argon2 参数时，同一机制会根据哈希内参数再次渐进升级。

本地管理员用户可通过下面命令创建：

```powershell
cd backend
.\.venv\Scripts\python scripts\ensure_default_user.py
```

本地默认账号为 `local@example.com` / `123456`，仅用于本机开发。非本地环境不应创建或使用这个默认账号。

`documents`、`document_chunks`、`chunk_embeddings`、`conversations`、`messages`、`jobs` 和 `tags` 的 `user_id` 都通过已验证的外键引用 `users.id`。这些业务数据使用 `ON DELETE RESTRICT`，直接删除仍持有资料、会话、任务或标签的用户会失败，避免绕过文件存储和运行任务的受控清理流程；仅可撤销的 `auth_sessions` 随用户使用 `ON DELETE CASCADE`。迁移 `0017_user_owner_fks` 不会自动重写或删除历史孤儿数据，升级遇到孤儿记录时会回滚并报错，部署者必须先确认数据归属再修复。

普通用户可以提交当前密码和固定确认值永久删除账号：

```text
DELETE /api/auth/account
```

```json
{
  "current_password": "...",
  "confirmation": "DELETE"
}
```

当前密码错误与登录、改密共享账号和客户端限流并返回 `400`，不会注销有效会话；达到阈值返回 `429 + Retry-After`。配置为 `RUNTIME_SETTINGS_ADMIN_USER_ID` 的管理员返回 `409`，必须先把管理员职责迁移到其它用户。成功路径锁定用户、任务和资料，检查跨表所有权一致性，把所有文件 key 写入持久删除 outbox，删除切片、向量、消息、任务、会话、资料、标签和用户后返回 `204`。全部设备 token 随用户删除立即失效；物理文件由 outbox supervisor 最终收敛。该操作没有软删除或恢复窗口。

## 文件资料

当前支持上传：

- TXT
- Markdown
- PDF
- 图片（已接入上传和处理状态；默认未启用 OCR provider）
- 音频（已接入上传和处理状态；默认未启用语音转文字 provider）

上传接口：

```text
POST /api/documents/upload
```

整个 HTTP 请求体默认最多 30 MiB，由 `MAX_REQUEST_BODY_SIZE_BYTES` 配置；文件内容默认最多 25 MiB，由 `MAX_UPLOAD_SIZE_BYTES` 配置。请求体上限必须至少比文件上限多 64 KiB，用于 multipart 元数据和边界。已知 `Content-Length` 和无长度的分块传输都会在 ASGI 层计数，超限返回 `413` 且不进入认证、路由或数据库。上传文件名最多 255 个字符，MIME 类型最多 128 个字符；这些元数据和标签会在调用存储层前校验，超限或上传失败时不会保留不完整文件。

文件落地后，`documents`、标签关系和 `index_document` job 在同一个数据库事务提交，不再先提交资料再单独创建任务。flush 或业务构造阶段失败时回滚并直接删除尚未被数据库引用的文件；commit 抛错时事务结果可能已经在数据库生效，因此保留文件，不能冒险制造“已提交资料引用缺失对象”。commit 后 refresh 或 HTTP 响应丢失同样保留持久 job，由恢复器继续处理；确定回滚后遗留的文件由存储一致性审计识别为 orphan。

返回：

```json
{
  "document_id": "...",
  "job_id": "...",
  "filename": "example.txt",
  "status": "uploaded"
}
```

上传后会通过后台任务执行：

```text
保存文件 -> 解析文本 -> 清洗 -> 切片 -> embedding -> indexed
```

索引完成前还会生成资料摘要和最多 5 个自动标签。每份资料合计最多 20 个标签，单个标签最多 64 个字符；已有用户标签优先保留，自动标签只填充剩余名额。富化模型暂时失败不会影响资料检索，错误会记录在资料 metadata 中。重建向量索引时复用已有 chunk，只有 chunk 缺失才重新切片，不重复生成摘要和标签。

任务状态：

```text
GET /api/jobs/{job_id}
```

当前用户的任务历史支持状态、类型和分页筛选：

```text
GET /api/jobs?page=1&page_size=20&status=running&job_type=index_document
```

等待中或运行中的任务可以取消；失败或已取消任务可以重试：

```text
POST /api/jobs/{job_id}/cancel
POST /api/jobs/{job_id}/retry
```

取消采用协作式检查点：解析或模型调用已经开始时不会强制中断线程，而是在当前调用返回后、事务提交前安全退出。worker 的启动、进度和终态更新都校验数据库中的前置状态，取消请求不会被稍后的普通写入覆盖。重试会创建新的任务记录，通过 `retry_of_job_id` 关联直接来源任务，原任务保留用于审计，并阻止同一资料或同类重建出现第二个活动重试。

任务记录持久化在数据库中。运行中任务默认每 30 秒更新一次心跳；服务启动时立即恢复遗留的 pending 任务和超过 `STALE_JOB_AFTER_MINUTES` 未更新的 running 任务，运行期间再按 `JOB_RECOVERY_INTERVAL_SECONDS`（默认 60 秒）周期扫描，不需要等待服务重启。启动和周期维护、恢复认领都在线程池执行，不阻塞处理 API 和 readiness 的事件循环；认领期间收到关闭请求时，会先为已经取得的数据库租约派发 worker，再结束 supervisor。恢复 SQL 使用事务级 `JOB_RECOVERY_STATEMENT_TIMEOUT_SECONDS`（默认 30 秒），超时只回滚当前扫描且不会污染连接池中的后续查询。恢复状态记录当前扫描开始时间和最近扫描耗时；单次扫描超过 `JOB_RECOVERY_SCAN_STALE_AFTER_SECONDS`（默认 30 秒）或最近成功超过三个扫描周期时，readiness 降级。每次扫描最多领取 `JOB_RECOVERY_BATCH_SIZE`（默认 50）条，同时进程内未完成的恢复 worker 不超过 `JOB_RECOVERY_MAX_ACTIVE_WORKERS`（默认 50）；上一轮仍在运行时只领取剩余容量，避免跨扫描周期扩张事件循环和线程池队列。启动和周期扫描派发的恢复 task 由同一个注册表跟踪；服务关闭时先停止 supervisor，再按 `JOB_RECOVERY_SHUTDOWN_TIMEOUT_SECONDS`（默认 30 秒）等待 worker 完成，超时后取消剩余的 asyncio 包装任务。普通 worker 只能从 `pending` 首次领取任务，恢复器原子领取后由恢复 worker 从 `running` 续跑；每次领取写入新的内部 `run_token`，进度、心跳和终态都必须匹配该令牌，晚到、失去租约或重复的 worker 无副作用退出。心跳间隔由 `JOB_HEARTBEAT_INTERVAL_SECONDS` 配置，并自动限制在 stale 阈值的三分之一以内。

普通上传、重试、手工重建和恢复 worker 共享同一个进程级 permit 池，统一受 `JOB_RECOVERY_MAX_ACTIVE_WORKERS` 限制。普通 `BackgroundTasks` 使用异步包装等待 permit，不占用 AnyIO 的同步路由线程；取得 permit 后与恢复任务一样进入 asyncio 默认执行器。恢复扫描先按剩余 permit 数量预留容量，再以该数量领取数据库任务，不会把已经改为 `running` 的任务堆积在线程池队列中。asyncio 包装任务被取消时，permit 仍由底层同步线程持有，直到线程真实退出才释放。readiness 的 `job_worker_occupied_slots`、`job_worker_waiting_tasks` 和 `job_worker_max_active_workers` 返回统一容量状态；`job_recovery_active_workers` 继续只表示恢复 supervisor 跟踪的任务数。

后台维护统一清理过期认证会话、旧限流记录和终态任务历史。每张表单轮最多删除 `MAINTENANCE_CLEANUP_BATCH_SIZE`（默认 1000）行，候选按到期或更新时间排序，并使用 `FOR UPDATE SKIP LOCKED` 支持多实例并行；成功、失败和已取消任务默认保留 `JOB_RETENTION_DAYS`（默认 30）天。登录与注册的失败记录不会在请求路径清理；维护 cutoff 采用两类 `*_ATTEMPT_RETENTION_SECONDS` 中较长的配置，避免一个策略提前删除另一个策略仍有效的阻止记录。迁移 `0022_jobs_updated_at_index` 使用 PostgreSQL 并发建索引为任务历史的 `(updated_at, id)` 排序提供支持，升级时不持有阻塞任务写入的普通建索引表锁。

恢复候选查询显式限定 `pending`、`cancel_requested` 和 `running` 三种固定状态，并使用只包含活跃任务的 `(created_at, id)` 部分索引；因此批量领取不会扫描或排序已经完成的历史任务。任务历史默认按 `updated_at DESC, created_at DESC, id DESC` 稳定分页，并使用 `(user_id, updated_at, created_at, id)` 索引反向扫描。迁移 `0023_job_query_indexes` 通过 PostgreSQL 并发创建和删除这两个索引，可在任务 worker 继续写入时升级或降级。

资料、会话和消息分页同样使用唯一 ID 作为最终排序键：资料为 `created_at DESC, id DESC`，会话为 `updated_at DESC, id DESC`，消息为 `created_at, id`。迁移 `0024_stable_pagination` 并发建立对应的用户或会话复合索引，并为管理员邀请码的既有 `created_at DESC, id DESC` 顺序增加索引；新索引 ready 后才删除被其前缀完全覆盖的旧单列索引。页码、总数、筛选参数和响应格式保持不变。

所有页码列表最多允许跳过 100,000 行；`(page - 1) * page_size` 超界时在 count/list SQL 前返回稳定 `422`，service 直接调用也执行同一校验。页面 UI 继续使用原有页码协议；需要完整遍历的标签、消息和可选资料改用 `GET /api/tags/scan`、`GET /api/chat/conversations/{conversation_id}/messages/scan` 和 `GET /api/documents/scan`。scan 响应为 `items + next_cursor`，客户端把非空游标原样传回同一路径并保持筛选条件不变；后端使用现有唯一排序键执行 keyset 条件和一行 lookahead，不执行 OFFSET，也不依赖总数猜测是否还有下一批。会话详情首屏改用 `GET /api/chat/conversations/{conversation_id}/messages/recent`，默认从最新位置读取 50 条；其非空游标继续读取更早一页，不能与正序完整 scan 的游标混用。每个 recent 响应页仍按时间正序展示，客户端把更早页前插。所有消息列表和 scan 只在 SQL 中读取每条正文的前 32,000 个字符，并通过 `content_truncated` 明确标识历史超大消息；最近模型上下文每条只读取前 2,000 个字符，不会先加载完整 `messages.content`。

应用 Session 在阶段 commit 后保留已经加载的 ORM 值，避免 worker 随后读取 document/chunk 属性时隐式重新 checkout 连接。解析、Embedding 和摘要/标签 Provider 前都明确结束任务状态或取消检查产生的读事务；慢 Provider 期间只有独立心跳按短事务更新 job，不长期占用业务 Session。全量重建在调用 Embedding 前先持久化必要切片并再次检查取消，因此取消请求不会再多执行一次模型调用。

同一恢复事务还按批量上限锁定 `uploaded` 文件资料，并为完全没有任何历史 `index_document` job 的旧资料补建 pending 任务；`FOR UPDATE SKIP LOCKED` 防止多实例重复补建。新版本上传已通过单事务从源头消除这一中间状态，该扫描用于修复旧版本崩溃或两次提交之间故障留下的数据。

`jobs.error_message`、`documents.error_message` 和 `metadata.enrichment_error` 都会通过 API 返回，因此 worker 不保存任意异常的 `str(exc)`。只有显式 `PublicJobError` 和存储配置变化等已审核业务错误可以保留原文；文件解析按 TXT/Markdown、PDF、图片 OCR 和音频转写映射稳定提示，切片、Embedding 和全量重建使用阶段兜底。未知 pypdf、httpx、SQLAlchemy、文件系统或 Provider 异常只写入服务端 traceback，客户端看不到绝对路径、URL、驱动诊断、请求细节或凭据字样。

同步 API 路由也只把服务层命名业务异常转换为 HTTP 错误，不能捕获内置 `ValueError`、`LookupError` 或 `PermissionError` 后直接返回原文。模型设置的已知权限和配置错误分别使用 `RuntimeSettingsAccessError` 与 `RuntimeSettingsValidationError`；`.env` 文件权限错误、Provider 内部异常或其它意外内置异常继续进入全局稳定 `500/503` 边界。相关资料不存在返回 `404`，资料尚未完成索引返回 `409`。

请求 schema 校验失败仍返回 `422`，顶层 `message` 使用首条稳定中文校验消息，`detail` 中每项只包含 `type`、`loc` 和映射后的公开 `msg`。必填、文本和列表长度、UUID、枚举、Literal、数字、布尔、日期、URL 与数据结构错误都有固定分类，未知类型返回“请求参数不合法”。Pydantic 提供的原始 `msg`、`input`、`ctx`、错误文档 URL 及其它扩展字段不会进入响应，避免框架英文和版本措辞成为 API 契约，也避免超长密码、邀请码、访问令牌或模型 API Key 在失败响应、代理和客户端日志中被再次记录。

整个 `/api` 命名空间的成功和错误响应统一包含 `Cache-Control: no-store` 与 `Pragma: no-cache`。access token、用户资料、原文、聊天记录、模型配置和错误详情不得进入浏览器 HTTP 缓存或共享代理；需要离线读取的白名单 GET 数据只由 Flutter 的 token 指纹隔离加密缓存管理。OpenAPI 和其它非 API 正常响应不强制套用这一策略，未处理 `500` 响应仍显式禁缓存。

资料统计包含各处理状态数量和上传文件占用字节数：

```text
GET /api/documents/stats
```

本地文件默认保存到：

```text
backend/storage_data/
```

文件资料会在上传时把 `storage_backend` 和不含凭据的 `storage_scope` 与 key 一起保存在 `documents`。解析前必须确认当前配置仍与这份来源一致；配置已经切换时任务进入明确失败状态，不会读取新命名空间中的同 key 对象，恢复原配置后可以从任务历史重试。删除资料和删除账号也从资料行读取这份快照，再与业务删除写入同一事务的 `storage_deletions` outbox。来源字段缺失时单资料删除返回 `409`，账号删除同样停止，不能根据删除时的当前配置猜测旧文件位置。

删除资料时，资料行和 `storage_deletions` outbox 任务在同一数据库事务提交；`204` 表示资料已从业务数据中删除且文件清理已被持久接收，不要求当前 HTTP 请求同步等待本地文件或 S3。路由会触发一次即时删除批次，启动和周期 supervisor 继续处理积压；临时失败按指数退避重试，成功后才删除 outbox 行。

已索引资料可以查询混合检索得到的相关资料，结果会排除资料自身并按资料去重：

```text
GET /api/documents/{document_id}/related?limit=5
```

## 标签

创建笔记时可以传入：

```json
{
  "tags": ["英语", "学习"]
}
```

笔记正文以及保存为笔记的整理结果最多 200,000 个字符；字段超限返回 `422`，service 内部调用也会在文本清洗、Embedding 或数据库写入前拒绝。同步创建笔记时先释放认证读事务，在无数据库连接的阶段完成切片、全部 Embedding 和摘要/标签生成，最后用一个短事务原子写入资料、切片、向量与标签。保存整理结果的 `ai_generated` 来源和来源资料 ID 也包含在这次首次提交中，不存在提交普通笔记后再补 provenance 的窗口。

上传文件时可以通过表单字段传入逗号分隔的标签：

```text
tags=英语,学习
```

标签列表：

```text
GET /api/tags?page=1&page_size=100
```

标签总数通过 `X-Total-Count` 响应头返回。资料总量和处理状态统计使用 `GET /api/documents/stats`。

完整遍历接口使用不透明游标，不受页码 OFFSET 边界影响：

```text
GET /api/tags/scan?page_size=100&cursor=<next_cursor>
GET /api/documents/scan?page_size=100&status=indexed&cursor=<next_cursor>
GET /api/chat/conversations/{conversation_id}/messages/scan?page_size=100&cursor=<next_cursor>
GET /api/chat/conversations/{conversation_id}/messages/recent?page_size=50&cursor=<older_cursor>
```

资料页码列表和 scan 列表只返回卡片需要的 id、标题、来源、状态、时间、标签，以及最多 500 字符的 `summary` / `error_message` 预览。SQL 使用显式 loader projection，不读取 `raw_text`、`cleaned_text`、metadata、存储位置或其它详情列，并对排除列启用 raiseload；关键词仍可在数据库索引和 WHERE 中匹配全文，但命中行不会把正文传回应用进程。`GET /api/documents/{document_id}` 继续返回完整资料详情；Flutter 详情页始终按 ID 独立加载，不依赖列表对象携带正文。

把一个标签重命名为当前用户已有名称时会合并两个标签。后端只锁定按 UUID 稳定排序的源、目标两行，使用单条 `INSERT INTO document_tags ... SELECT ... ON CONFLICT DO NOTHING` 把源关联并入目标，再直接删除源标签；重叠资料关系保留一份，数据库外键级联移除源关系。普通删除标签同样执行带 owner 条件的直接 `DELETE` 并依赖数据库级联，不会把该标签关联的全部资料 ID 或关系对象加载到应用内存。

资料列表支持按标签筛选：

```text
GET /api/documents?tag=英语
```

问答和整理也支持按标签限定范围：

```json
{
  "scope": {
    "tags": ["英语"]
  }
}
```

聊天范围一次最多包含 100 个资料 ID、20 个标签和全部 7 种资料来源。显式资料 ID 使用有界 `IN`，标签通过相关 `EXISTS`、来源通过资料列条件直接下推到向量与关键词检索，不会先把某个标签命中的全部资料 ID 拉进内存。资料列表搜索词最多 255 个字符，标签筛选最多 64 个字符；超限请求在生成查询 embedding 或进入业务 SQL 前返回 `422`。

资料列表关键词会对标题、原文、清洗正文和摘要执行不区分大小写的字面子串搜索；`%`、`_` 和反斜杠会被转义，不作为客户端可注入的 LIKE 通配符。四字段先通过一个合并文本的 `pg_trgm` GIN 表达式索引筛选候选，再保留字段级 OR 复核，因此索引不会改变原有命中语义。会话标题搜索使用独立 trigram GIN。资料标签筛选同时约束 tag owner 和名称，使 `(user_id, name)` 唯一索引与 `document_tags(tag_id)` 索引形成完整关联路径。

混合检索的关键词分支不会在无序命中上直接截断。chunk 内容/章节标题与资料标题分别通过各自 trigram GIN 生成 chunk ID 候选，两支使用 `UNION` 去重；数据库按与应用 `_keyword_score` 相同的词频和标题加权公式全局排序，再稳定截取 `max(6 × top_k, 24)` 条交给最终 rerank。这样候选上限约束返回和评分规模，但不会因表物理顺序漏掉位于后面的高相关 chunk。

聊天请求把数据库工作分为短读取、短检索和最终短写入三段：读取会话与历史后释放连接，检索完成后再次释放连接，LLM 调用期间不持有数据库连接。Provider 成功后才重新校验并锁定已有会话，把 scope、用户消息和助手消息原子提交；Embedding、LLM 或最终提交失败都不会留下半轮消息。模型回答最多 32,000 个字符，整理结果最多 200,000 个字符，自动摘要最多 20,000 个字符，自动标签原始输出最多 4,000 个字符；超限在任何业务写入前拒绝，聊天和整理返回稳定 `502`，不会无提示截断新内容。单篇整理、多资料整理和相关资料查询同样会先把 ORM 数据压缩为字符串与 ID，再释放读事务后调用 Provider。

## 数据库迁移

确认 PostgreSQL 已创建数据库后运行：

```powershell
cd backend
alembic upgrade head
```

如果还没有创建数据库，可以先运行：

```powershell
cd backend
.\.venv\Scripts\python scripts\create_database.py
```

第一版迁移会尝试创建 pgvector 扩展：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

`alembic upgrade head` 创建向量列和 HNSW 索引，因此必须先安装 pgvector。第一条迁移在扩展不可用时只会输出提示，后续向量表迁移仍会失败。

迁移 `0025_trigram_search` 还会执行 `CREATE EXTENSION IF NOT EXISTS pg_trgm`，并并发创建资料和会话搜索索引。`pg_trgm` 属于 PostgreSQL contrib 扩展，数据库角色必须有安装该扩展的权限；降级会删除本项目的搜索索引，但不会删除可能被数据库其它对象共用的扩展。

迁移 `0026_chunk_search` 使用同一扩展并发创建 chunk 内容与章节标题的合并 trigram GIN 表达式索引。迁移可在线往返，降级只删除该索引，不影响资料列表和会话标题的 `0025` 搜索索引。

## Windows 安装 pgvector

当前本机 PostgreSQL 路径：

```text
D:\postgresql\18
```

如果需要重新安装 pgvector，可以先下载 PostgreSQL 版本对应的 Windows 预编译包，展开后运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_pgvector_windows.ps1 -SourceRoot <展开目录> -PostgresRoot D:\postgresql\18
```

安装后在目标数据库执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

当前本地 `personal_ai` 数据库已启用：

```text
vector 0.8.2
```

## Embedding Provider

本地开发默认使用：

```text
EMBEDDING_PROVIDER=local_hash
```

它不需要外部 API key，用于验证 chunk、pgvector 写入和向量检索流程。它不是语义 embedding，后续接入真实模型时改为：

```text
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_KEY=<your-api-key>
EMBEDDING_BASE_URL=<provider-base-url>
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
```

当前数据库列和 HNSW 索引固定为 1536 维，运行时设置页不能修改维度。切换模型时必须选择输出 1536 维向量的模型，并在保存后重建索引。

文件处理和索引重建不会把整份资料的高维 Python 向量与 ORM 对象同时留在内存。Provider 仍按默认 64 条分批调用，每批结果立即转换为紧凑 float32 并写入最多 8 MiB 内存的 spool，超过后自动转为随句柄关闭删除的匿名临时文件；全部 Provider 批次成功前不执行删除旧向量或其它持久化 SQL。随后后端在一个数据库事务中删除旧向量，按批读取 spool、flush 新向量并 detach 已持久化 ORM 对象，整份资料成功后才由 worker commit。Provider 失败不会触碰旧索引，数据库中途失败由调用方 rollback 恢复旧索引；向量数量或维度不符合 Provider 契约时也在数据库阶段前失败。

大文件切片同样采用有界批处理。chunker 逐条产出 `ChunkData`，文件 worker 默认每 256 条创建、flush 并 detach ORM chunk；旧切片删除与全部批次插入仍在一个事务中，任一批失败由 worker rollback。Embedding 不再加载整份 chunk ORM 列表，而是按 `(document_id, chunk_index)` keyset 每次只读取一个 Provider 批次的 `id/content`，查询后先 rollback 释放连接，再调用 Provider。spool 的每条记录同时保存 chunk UUID 和定长 float32 向量，因此全部 Provider 成功后无需重新物化 chunk 即可批量替换索引。摘要和自动标签只读取按 `chunk_index` 排序的前 8 条 chunk，并继续受 6,000 字符上下文预算限制。同步笔记正文仍由 200,000 字符上限约束，可使用原有内存原子创建路径。

解析阶段同样避免正文的可消除全量中间副本。文本清洗按 CR/LF 边界扫描，每次只规范化当前行并增量写入 `StringIO`，不再同时构造规范化全文、完整行列表和清洗行列表；已有非空 `cleaned_text` 的资料在重建切片时直接复用。PDF 提取结果按页增量写入最终缓冲区，不保留完整页面文本列表；空正文检查使用 `isspace()`，不为大字符串创建 `strip()` 副本。数据库仍按原契约保存原文和清洗正文，这些必要结果不受影响。

单用户和全用户索引重建也不会一次加载全部 `Document` 行。任务先按扫描开始时间固定创建时间上界并统计总数，再使用 `(user_id, created_at, id)` 每批读取最多 100 个轻量键；每个键只加载一份完整资料，并在交给后续处理前 detach + rollback。资料在等待期间被删除、转为其它状态或改变 owner 时会在完整读取时重新校验并跳过；扫描开始后创建的资料留给下一次重建。键批次复用 `ix_documents_user_created_id`，不使用跨 Provider 的服务器端 cursor。失败总数独立累计，任务错误详情只保留前三份样本，不能随全库失败数量增长。

带用户、模型、资料、标签或来源过滤的 HNSW 查询使用 pgvector `0.8.0` 以上提供的 iterative scan。每次向量检索事务都会设置 `hnsw.iterative_scan=strict_order`，并使用 `HNSW_EF_SEARCH`（默认 100，范围 1–1000）和 `HNSW_MAX_SCAN_TUPLES`（默认 20000，范围 1–1000000）约束初始候选广度与最大扫描量。设置通过事务级 `set_config(..., true)` 应用，不会泄漏到连接池中的后续请求；readiness 在 vector 扩展低于 0.8 时返回 not ready，并暴露当前三个搜索参数。

readiness 不仅检查 HNSW 索引名称，还通过 PostgreSQL 系统目录验证索引属于当前 schema 的 `chunk_embeddings`、使用 `hnsw` access method、处于 ready/valid/live 状态、只有一个非唯一键、没有表达式或部分谓词，并精确索引 `embedding vector(1536)` 与 `vector_l2_ops`。同名 B-tree、失败的并发索引、错误列、维度或距离 opclass 都会使 readiness 返回 index missing。

HNSW 构建参数固定为 `m=16`、`ef_construction=64`，模型元数据和 readiness 都验证这两个显式 reloption。迁移 `0027_online_hnsw_options` 不直接阻塞式重建线上索引：它先以临时名称执行 `CREATE INDEX CONCURRENTLY`，确认临时索引 ready/valid 后才并发删除旧索引并切换名称。迁移在临时索引已完成、旧索引已删除或名称切换后中断都可以幂等重跑；downgrade 使用相同步骤在线恢复扩展默认参数。

运行时有效 Embedding 索引身份或 OpenAI-compatible API Key 变化时，后端会创建覆盖所有用户资料的重建任务，并在设置响应头中返回：

```text
X-Embedding-Rebuild-Job-Id: <job-id>
```

当前有效配置指纹与“已协调指纹”保存在单例 `embedding_configuration_state` 中。状态更新和带目标指纹的全用户任务在同一数据库事务提交；如果 `.env` 已成功更新但任务数据库提交失败，PATCH 返回可重试 `503`，状态仍保留旧指纹。启动和周期任务恢复会重新比较当前指纹，数据库恢复后自动补建缺失任务。相同目标指纹已有 pending/running 任务时不重复创建；cancel_requested 会在恢复时直接取消，success/failed/cancelled 也不能替代本轮义务，因此配置 A→B→A 会为最后一次 A 新建任务。首次升级若现有资料的切片和向量索引身份一致，只初始化状态。

全用户重建任务使用 PostgreSQL advisory lock 串行执行，锁由独立数据库连接持有并在同一连接释放，不受任务进度事务提交影响；服务恢复后仍保持全用户范围。管理员也可以手动创建任务：

```text
POST /api/jobs/rebuild-all-embeddings
```

普通用户原有的 `POST /api/jobs/rebuild-embeddings` 只重建自己的资料。

## LLM Provider

本地开发默认使用：

```text
LLM_PROVIDER=local_extractive
```

它不需要外部 API key，用于验证 `/chat/query`、上下文构建、引用来源和消息保存流程。它不是完整大模型，后续接入真实模型时改为：

```text
LLM_PROVIDER=openai_compatible
LLM_API_KEY=<your-api-key>
LLM_BASE_URL=<provider-base-url>
LLM_MODEL=<model-name>
AI_PROVIDER_MAX_RESPONSE_SIZE_BYTES=8388608
AI_PROVIDER_MAX_CONCURRENT_REQUESTS=8
```

所有 OpenAI-compatible LLM、Embedding、OCR 和语音转写响应共用 `AI_PROVIDER_MAX_RESPONSE_SIZE_BYTES`，默认 8 MiB，可配置范围为 64 KiB–64 MiB。后端使用流式响应：HTTP 状态失败时不读取错误正文；成功响应若声明的 `Content-Length` 已超限会立即关闭，未声明长度的分块响应则按 64 KiB 逐块累计。计数使用 HTTPX 解压后的字节，因此 gzip 等压缩响应不能用较小的传输体绕过边界；只有完整 JSON 在限制内时才进入解析和业务字段校验。当前值可通过 `GET /api/health/capabilities` 的 `ai_provider.max_response_size_bytes` 核对。

所有 OpenAI-compatible 调用还共用进程级 `AI_PROVIDER_MAX_CONCURRENT_REQUESTS`，默认 8，可配置范围为 1–100。前台聊天、整理和相关资料检索与后台解析、富化、Embedding 进入同一个 FIFO 等待队列；等待者在取得 permit 前不会打开 Provider HTTP 连接，成功、HTTP 错误、响应越界、JSON 错误和网络异常都会释放槽位。`/api/health/ready` 暴露带 `ai_provider_` 前缀的 max/active/waiting 指标，`/api/health/capabilities` 在 `ai_provider` 对象中返回相同容量快照。该限制在进程启动时创建，修改环境变量后必须重启；多 Uvicorn worker 或多实例部署的全局最大并发是各进程上限之和，需按 Provider 配额统一折算。

## 运行时模型设置

```text
GET /api/settings/runtime
PATCH /api/settings/runtime
```

只有 `RUNTIME_SETTINGS_ADMIN_USER_ID` 对应的用户可以访问这些接口。在线修改只允许在 `local`、`dev` 或 `development` 环境；生产环境应通过部署系统更新环境变量和密钥。

在线更新在单进程内使用互斥锁串行执行完整的校验、文件持久化和内存应用。`.env` 内容先写入同目录临时文件并执行 `flush + fsync`，成功后通过 `os.replace` 原子替换；写入或替换失败时旧文件保持完整，内存配置不会提前改变，异常临时文件会清理。临时文件模式已加入 `.gitignore`，避免极端进程崩溃后的残留凭据被误提交。

这不是跨实例配置分发协议。多 worker 或多实例部署的各进程拥有独立内存设置，不能使用在线修改保证同时生效；这类环境必须由部署系统更新环境变量并统一重启。生产环境继续由接口权限检查禁止在线写入。

迁移 `0021_embedding_config_state` 为任务增加不可公开的目标配置指纹，并创建协调状态表。指纹只包含索引身份和截断 SHA-256 凭据摘要，不保存或返回原始 API Key。

## 后端测试

```powershell
cd backend
pip install -r requirements-dev.txt
pytest -q
alembic check
```

## OCR 和语音转文字

当前图片和音频资料已经可以上传，并会进入同一套任务状态流转。默认配置为：

```text
OCR_PROVIDER=disabled
SPEECH_TO_TEXT_PROVIDER=disabled
```

在未启用 provider 时，图片资料会以“图片 OCR 尚未启用”失败，音频资料会以“语音转文字尚未启用”失败。配置兼容 Provider 后，新上传的图片和音频会进入正常的解析、摘要、标签和索引流程。

当前已实现 OpenAI-compatible Provider，可以在管理员模型设置页配置，也可以使用环境变量：

```text
OCR_PROVIDER=openai_compatible
OCR_BASE_URL=https://api.openai.com/v1
OCR_API_KEY=<your-api-key>
OCR_MODEL=gpt-4o-mini

SPEECH_TO_TEXT_PROVIDER=openai_compatible
SPEECH_TO_TEXT_BASE_URL=https://api.openai.com/v1
SPEECH_TO_TEXT_API_KEY=<your-api-key>
SPEECH_TO_TEXT_MODEL=whisper-1
```

图片通过兼容的视觉聊天接口提取文字，上传音频通过 `/audio/transcriptions` 转写。聊天页实时麦克风输入由 Flutter 调用设备语音识别能力完成。

OpenAI-compatible OCR 请求把图片按 57 KiB 原始文件块逐块 Base64 编码，并在固定 JSON 前后缀之间流式发送；请求预先计算精确 `Content-Length`，不会把完整图片、完整 Base64 文本和完整 JSON 请求体同时物化到内存。音频转写的 multipart 请求直接传递打开的文件对象，同样不先读取完整媒体文件。

## 存储后端

当前存储后端为：

```text
STORAGE_BACKEND=local
```

本地文件保存到 `backend/storage_data/`。也可以切换到 S3 / OSS / MinIO 兼容对象存储：

```text
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://s3.example.com
S3_REGION=us-east-1
S3_BUCKET=personal-ai
S3_ACCESS_KEY_ID=<access-key>
S3_SECRET_ACCESS_KEY=<secret-key>
S3_USE_SSL=true
S3_KEY_PREFIX=documents
```

远端对象会在解析阶段下载到临时文件，解析完成后自动删除；上传、读取、资料删除和处理失败清理均使用同一存储抽象。每条文件资料保存上传时的 backend 和位置快照；普通笔记的 key 与来源字段全部为空，数据库约束拒绝不完整组合。文件物化与 outbox 删除共用严格的配置一致性检查，backend、local 根目录、S3 endpoint、region、bucket 或 SSL 模式任一变化都会停止操作并保留可重试状态。

资料删除的持久队列使用以下配置：

```text
STORAGE_DELETION_INTERVAL_SECONDS=60
STORAGE_DELETION_BATCH_SIZE=50
STORAGE_DELETION_LEASE_SECONDS=300
STORAGE_DELETION_RETRY_BASE_SECONDS=30
STORAGE_DELETION_RETRY_MAX_SECONDS=3600
STORAGE_DELETION_STATEMENT_TIMEOUT_SECONDS=30
STORAGE_DELETION_SHUTDOWN_TIMEOUT_SECONDS=30
```

多实例通过数据库行锁和带 token 的有限租约领取任务，同一对象即使因租约到期被重复处理也依赖本地删除与 S3 删除的幂等语义收敛。队列沿用资料上传时的 `STORAGE_BACKEND` 和不含凭据的存储位置快照：本地使用解析后的根目录，S3 使用 endpoint、region、bucket 与 SSL 模式；处理前任一配置已变化时，任务保留并让 readiness 降级，不会把旧 key 误删到新的存储位置。切换存储配置前应先确认 `storage_deletions` 为空。

迁移 `0020_storage_deletion_unique` 会按 `storage_backend + storage_scope + storage_key` 合并语义相同的历史删除意图，保留每组创建时间和 ID 最早的一行，再创建数据库唯一约束。部署时应先排空旧版本 supervisor 再升级和启动新代码。所有资料删除、账号删除和人工 orphan 处置都使用 `INSERT ... ON CONFLICT DO NOTHING RETURNING id`；并发请求最多创建一行，已有任务继续保留原租约、尝试次数和退避状态，不会被新请求重置。

迁移 `0019_document_storage` 会用执行迁移时的存储配置回填所有历史文件资料，再创建三字段一致性约束。升级前必须确认当前 `STORAGE_BACKEND` 和位置仍指向这些历史 key 的真实命名空间；若历史数据实际分布在多个位置，应先按真实来源补齐数据，不能依赖迁移猜测。迁移完成后再切换配置不会改写已有资料快照。

可以只读审计当前 backend 和 scope 的数据库引用与受管对象：

```powershell
.\.venv\Scripts\python.exe scripts\audit_storage.py
```

审计批次和诊断样本上限由环境配置：

```text
STORAGE_AUDIT_BATCH_SIZE=500
STORAGE_AUDIT_SAMPLE_LIMIT=100
```

命令输出稳定 JSON：资料引用、当前 scope 的待删除 outbox、对象 inventory 和四类 drift 都返回精确数量；缺失资料对象、非法 key 和孤立对象的 key 列表只保留字典序最小的有限样本，`sample_limit` 给出上限，`diagnostics_truncated` 逐类说明是否还有未展示项。状态为 `consistent` 时退出码为 0；发现任一 drift 时退出码为 1。不能把样本列表当作完整处置清单。

数据库引用按 UUID 主键 keyset 限批读取，每批复制轻量 `id/key` 后立即 rollback；去重后的期望 key 写入系统临时目录中的 SQLite `WITHOUT ROWID` 索引，2 MiB page cache 和诊断样本共同限制 Python 常驻内存，临时磁盘占用随唯一引用数增长并在正常退出时删除。随后 local 逐文件生成、S3 逐 paginator page 生成 inventory，与磁盘索引逐项比对，不构造完整 bucket 列表。命令没有删除参数，不会修改业务数据库或对象。local 只枚举 `documents/`；S3 只枚举当前 `S3_KEY_PREFIX`，但会对当前 scope 中位于历史前缀的资料引用单独执行存在性检查。S3 审计需要现有对象读取权限、bucket 列表权限和足够的本机临时磁盘空间。

数据库和对象存储不能提供跨系统原子快照，正在上传且尚未写入资料行的对象可能被短暂报告为 orphan。应在低写入时段运行，发现 drift 后再次审计并核对业务来源；审计结果不能作为自动删除清单。

人工确认某个 key 确实可以处置后，先运行独立命令的默认 dry-run：

```powershell
.\.venv\Scripts\python.exe scripts\enqueue_orphan_deletion.py documents/<exact-key>
```

只有输出 `status=orphan` 后，才可以用相同精确 key 显式入队：

```powershell
.\.venv\Scripts\python.exe scripts\enqueue_orphan_deletion.py documents/<exact-key> --enqueue
```

命令不展开通配符、不接受批量清单，也不枚举完整 inventory。它只对目标 key 依次执行当前受管 prefix、路径合法性、对象存在性和数据库引用/pending outbox 的精确复核；迁移 `0028_storage_audit_lookup` 并发创建 `md5(file_path)` 部分表达式索引来定位资料候选，查询仍用完整 key、backend 和 scope 等值条件复核，hash 碰撞不能把已引用对象误判为 orphan。默认 dry-run 永远返回 `action=none`；非孤立对象和已有 pending outbox 的 key 都返回 `not_orphan` 且不写数据库。`--enqueue` 只在数据库提交一条带当前 backend/scope 快照的删除任务，不同步删除对象；运行中的 supervisor 会在下一批次处理，后端暂时离线时任务也会保留。若另一进程在复核后抢先入队，唯一约束会使响应稳定为 `already_queued`。配置变化仍会由 worker 拒绝并按既有策略重试。

该命令是明确的破坏性运维入口，不能把审计输出直接批量传入。数据库与对象存储之间仍没有原子快照，应在低写入时段对单个 key 完成业务核对和 dry-run，再执行 enqueue。

## 整理接口

单份资料整理：

```text
POST /api/organize/document
```

支持模式：

```text
summary
outline
key_points
action_items
```

多资料整理：

```text
POST /api/organize/collection
```

支持模式：

```text
themes
connections
article_outline
study_plan
```

多资料整理一次最多处理 20 份资料。后端用单次分组查询为每份资料选取前几个 chunk，并把模型上下文限制在 24,000 字符以内；超出范围返回 `400`，资料尚未可整理返回 `409`。

两个接口都支持：

```json
{
  "save_as_note": true
}
```

开启后会把整理结果保存为一条 `ai_generated` 笔记，并进入同一套切片、embedding、检索流程。

如果客户端先展示整理结果、再由用户决定保存，可直接保存已经生成的内容，避免重复调用模型：

```text
POST /api/organize/save-result
```

请求包含标题、整理结果正文和来源资料 ID。后端会校验来源资料归属，并写入 `ai_generated` 类型和来源关联。
