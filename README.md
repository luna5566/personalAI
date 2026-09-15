# 个人 AI 知识助手

这是一个由 FastAPI、PostgreSQL/pgvector 和 Flutter 组成的个人资料知识助手，支持资料导入、混合检索问答、引用定位、AI 整理、离线缓存和多种模型/存储 Provider。资料与标签目录使用服务端搜索和分页，较大知识库不会在打开选择器时自动下载完整目录。

## 目录

- `backend/`：认证、资料处理、RAG、整理、任务恢复和运行时设置 API
- `mobile/`：Android、iOS、Web 和桌面端共用的 Flutter 应用
- `docs/`：MVP 清单、页面交互设计和项目决策

## 本地启动

### 方式 A：Docker Compose（推荐）

需要已安装 Docker Desktop。在项目根目录执行：

```powershell
docker compose up --build
```

服务就绪后：

- Web 应用：`http://127.0.0.1:5600`
- API：`http://127.0.0.1:8000/api/health`
- Swagger：`http://127.0.0.1:8000/docs`
- Postgres：`localhost:5432`（用户/密码/库均为 `postgres` / `postgres` / `personal_ai`）

三个服务的端口默认只绑定本机回环地址（`127.0.0.1`），部署到服务器时数据库、API（含 `/metrics`、`/docs`）不会对公网暴露。需要局域网访问 Web 时，把 `docker-compose.yml` 里 `web` 的端口改成 `"5600:80"`，并自行前置 TLS 反向代理。

默认使用本地开发模型（`local_extractive` + `local_hash`），不依赖外部 API Key。接入真实模型时，在 `docker-compose.yml` 的 `api.environment` 中配置 `LLM_*` / `EMBEDDING_*` 后重建容器；可选的模型重排在 `backend/.env.example` 的 `RERANK_*` 中说明。

### 方式 A 的 Web 镜像说明

`web` 服务的 `API_BASE_URL` 通过运行时环境变量注入：容器每次启动时把该值写入产物内的 `env.js`，Flutter 启动时读取，因此修改 API 地址不需要重建镜像，改 `docker-compose.yml` 里 `web.environment.API_BASE_URL` 后执行 `docker compose up -d web` 即可。

### 方式 A：不使用 Web 容器本地调试 Flutter

```powershell
cd mobile
flutter pub get
flutter run -d chrome --web-hostname 127.0.0.1 --web-port 5600 --dart-define=API_BASE_URL=http://127.0.0.1:8000/api
```

### 方式 B：本机 Python

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
alembic upgrade head
python scripts\ensure_default_user.py
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端启动 Flutter Web：

```powershell
cd mobile
flutter pub get
flutter run -d chrome --web-hostname 127.0.0.1 --web-port 5600 --dart-define=API_BASE_URL=http://127.0.0.1:8000/api
```

默认本地账号为 `local@example.com` / `123456`，只用于本机开发。

## 验证

```powershell
cd backend
.venv\Scripts\python -m pytest -q
# 带覆盖率（CI 门槛为 85%）
.venv\Scripts\python -m pytest -q --cov=app --cov-report=term-missing:skip-covered --cov-fail-under=85
.venv\Scripts\python -m ruff check app tests scripts
alembic check

cd ..\mobile
flutter analyze
flutter test
flutter build web --dart-define=API_BASE_URL=http://127.0.0.1:8000/api
```

Windows 构建含插件的桌面应用前需要启用 Developer Mode。

## 检索质量评测

调整切片策略、更换 embedding 模型或修改 `CHAT_RETRIEVAL_TOP_K` 前后，用评测脚本量化检索效果（recall@k 与 MRR）：

1. 准备评测集（参考 `backend/scripts/retrieval_eval_set.example.jsonl`，JSONL 格式，每行一个用例）：

```json
{"question": "……", "expected_document_ids": ["<资料 UUID>"]}
{"question": "……", "expected_keywords": ["向量检索"]}
```

2. 在 `backend` 目录运行（需已完成 `alembic upgrade head` 并有真实资料入库）：

```powershell
.venv\Scripts\python scripts\eval_retrieval.py --top-k 8
.venv\Scripts\python scripts\eval_retrieval.py --min-recall 0.8 --json
```

命中判定、跳过规则（如期望资料不在库中）见脚本头部说明。`--min-recall` 可作为换模型时的门禁。

### 检索延迟基准

评估大知识库下的检索吞吐（离线 local_hash 向量，HNSW 行为与生产一致）：

```powershell
.venv\Scripts\python scriptsench_retrieval.py                          # 默认 500 篇 / 50 次查询
.venv\Scripts\python scriptsench_retrieval.py --documents 2000 --ef-search 40
```

输出 chunk 总量与每查询 P50/P90/P99 延迟，可对比 HNSW 参数；语料基准结束后自动清理。

CI 已内置同样的门禁：`seed_eval_documents.py` 播种 15 篇固定语料，`retrieval_eval_set.ci.jsonl` 是对应评测集，每次 CI 运行 `eval_retrieval.py --min-recall 0.8`，检索链路回归会在流水线上直接失败。本地复现：

```powershell
.venv\Scripts\python scripts\ensure_default_user.py
.venv\Scripts\python scripts\seed_eval_documents.py
.venv\Scripts\python scripts\eval_retrieval.py --eval-set scripts\retrieval_eval_set.ci.jsonl --min-recall 0.8
```

## Android release 签名

分发构建需要私有 release 签名。生成 keystore 并创建 `mobile/android/key.properties`（已被 git 忽略，模板见 `key.properties.example`）：

```powershell
keytool -genkey -v -keystore personal-ai-release.jks -keyalg RSA -keysize 2048 -validity 10000 -alias personal-ai
copy mobile\android\key.properties.example mobile\android\key.properties
# 编辑 key.properties，填入 keystore 路径和密码
cd mobile
flutter build apk --release
```

没有 `key.properties` 时，release 构建自动回退到 debug 签名，仅供本机预览。

## 可观测性

- `GET /api/metrics`：Prometheus 指标（HTTP 请求计数/时延按路由模板，AI Provider 出站调用按域名，任务队列深度按状态）。可用 `METRICS_ENABLED=false` 关闭；公网部署时应通过网络策略限制访问。
- 请求追踪：每个响应带 `X-Request-ID`，客户端可传入同名请求头串联链路。
- 结构化日志：设置 `LOG_FORMAT=json` 输出 JSON 日志（含 `request_id`），默认人类可读格式。

## 监控面板（可选）

`docker-compose.yml` 内置可选监控栈（`monitoring` profile，不影响默认启动）：

```powershell
docker compose --profile monitoring up -d
# Grafana: http://127.0.0.1:3300 （admin / personal-ai）
# Prometheus: http://127.0.0.1:9090
```

数据源和「请求速率 / P95 延迟 / 任务队列深度 / AI Provider 调用」面板已自动预置。监控镜像使用 latest，首次拉取后建议在 compose 里改成具体版本号。生产环境若开启 `METRICS_REQUIRE_LOCAL`，需将 Prometheus 改为宿主机网络采集。

## 备份与恢复

个人资料和索引都在 PostgreSQL 与 `personal_ai_storage` 卷里。使用 Docker Compose 运行时，执行：

```powershell
powershell -ExecutionPolicy Bypass -File ops\backup.ps1
powershell -ExecutionPolicy Bypass -File ops\backup.ps1 -OutputDir D:\backups -KeepDays 14
```

脚本会把数据库（`pg_dump -Fc`）和文件存储卷分别备份到指定目录，并按 `KeepDays` 清理过期备份。

恢复数据库（PowerShell 管道会破坏二进制流，用 `docker cp` 传入容器）：

```powershell
docker cp backups\personal_ai_db_时间戳.dump db:/tmp/dump
docker compose exec db pg_restore -U postgres -d personal_ai --clean --if-exists /tmp/dump
docker compose exec db rm /tmp/dump
```

恢复文件存储：

```powershell
docker run --rm -v personal_ai_storage:/data -v (Resolve-Path backups).Path`:/backup alpine sh -c "cd /data && rm -rf ./* && tar xzf /backup/personal_ai_storage_时间戳.tar.gz -C /data"
```

注意：非 Docker 部署时直接用本机 `pg_dump` / `pg_restore`，并备份 `backend/storage_data` 目录。恢复旧备份后，如模型配置发生过变化，可在管理页执行全量索引重建。

### 定时备份

脚本不会自动运行，建议注册系统计划任务：

Windows（任务计划程序，每天 03:00 执行，用管理员 PowerShell 注册一次）：

```powershell
schtasks /Create /TN "personal-ai-backup" /SC DAILY /ST 03:00 /TR `
  "powershell -ExecutionPolicy Bypass -NoProfile -File C:\Users\shouju\Desktop\code\personalAI\ops\backup.ps1 -OutputDir D:\backups -KeepDays 14"
```

Linux / macOS（cron，每天 03:00）：

```bash
0 3 * * * cd /path/to/personalAI && ./ops/backup.sh --output-dir /var/backups/personal-ai --keep-days 14
```

Linux / macOS 也可以直接用 `ops/backup.sh`（参数 `--output-dir` 与 `--keep-days`，与 PowerShell 版一致）。注册后先用 `schtasks /Run /TN "personal-ai-backup"` 或手动跑一次确认备份文件生成。

### 恢复演练

定期验证备份可用性（建议每月一次）：把最近的备份恢复到一个临时库名，而不是覆盖生产库：

```powershell
# 1. 用备份文件在数据库容器内恢复到临时库 personal_ai_drill
docker cp backups\personal_ai_db_时间戳.dump db:/tmp/dump
docker compose exec db createdb -U postgres personal_ai_drill
docker compose exec db pg_restore -U postgres -d personal_ai_drill --no-owner /tmp/dump
docker compose exec db psql -U postgres -d personal_ai_drill -c "SELECT count(*) FROM documents;"
docker compose exec db psql -U postgres -d personal_ai_drill -c "SELECT count(*) FROM chunk_embeddings;"
docker compose exec db dropdb -U postgres personal_ai_drill
docker compose exec db rm /tmp/dump
```

两个 count 都返回非零、dropdb 无报错，说明备份可恢复。文件存储卷的演练可以用 `tar -tzf personal_ai_storage_时间戳.tar.gz | head` 确认归档完整可读。
