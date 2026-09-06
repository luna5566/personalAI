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

默认使用本地开发模型（`local_extractive` + `local_hash`），不依赖外部 API Key。接入真实模型时，在 `docker-compose.yml` 的 `api.environment` 中配置 `LLM_*` / `EMBEDDING_*` 后重建容器；可选的模型重排在 `backend/.env.example` 的 `RERANK_*` 中说明。

### 方式 A 的 Web 镜像说明

`web` 服务在构建期把 `API_BASE_URL` 编译进 Flutter Web 产物（默认 `http://127.0.0.1:8000/api`）。如果 API 不在本机 8000 端口，用构建参数覆盖：

```powershell
docker compose build --build-arg API_BASE_URL=https://api.example.com/api web
docker compose up -d web
```

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
alembic check

cd ..\mobile
flutter analyze
flutter test
flutter build web --dart-define=API_BASE_URL=http://127.0.0.1:8000/api
```

Windows 构建含插件的桌面应用前需要启用 Developer Mode。Android 分发构建还需要把本地 debug 签名替换为私有 release 签名。

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
