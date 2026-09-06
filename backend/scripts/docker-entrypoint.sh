#!/bin/sh
set -eu

echo "Waiting for database..."
python - <<'PY'
import os
import sys
import time

from sqlalchemy import create_engine, text

url = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@db:5432/personal_ai",
)
engine = create_engine(url, pool_pre_ping=True)
deadline = time.time() + 60
last_error = None
while time.time() < deadline:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Database is ready.")
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - wait loop
        last_error = exc
        time.sleep(1)
print(f"Database not ready: {last_error}", file=sys.stderr)
sys.exit(1)
PY

echo "Running migrations..."
alembic upgrade head

echo "Ensuring default local user..."
python scripts/ensure_default_user.py || true

echo "Starting API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
