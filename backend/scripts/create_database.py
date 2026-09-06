from __future__ import annotations

import os
from urllib.parse import urlparse

import psycopg


def main() -> None:
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:123456@localhost:5432/personal_ai",
    )
    parsed = urlparse(database_url.replace("postgresql+psycopg://", "postgresql://"))
    database_name = parsed.path.lstrip("/")
    admin_url = parsed._replace(path="/postgres").geturl()

    with psycopg.connect(admin_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database_name,))
            if cur.fetchone():
                print(f"database already exists: {database_name}")
                return
            cur.execute(f'CREATE DATABASE "{database_name}"')
            print(f"database created: {database_name}")


if __name__ == "__main__":
    main()
