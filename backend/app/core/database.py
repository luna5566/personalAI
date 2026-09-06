from collections.abc import Generator
from dataclasses import dataclass
from math import ceil

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


@dataclass(frozen=True)
class DatabasePoolSnapshot:
    pool_size: int
    max_overflow: int
    capacity: int
    checked_in: int
    checked_out: int
    overflow: int
    utilization_percent: float
    saturated: bool


def _statement_timeout_ms(timeout_seconds: float) -> int:
    return max(ceil(timeout_seconds * 1000), 1)


def create_database_engine() -> Engine:
    statement_timeout_ms = _statement_timeout_ms(
        settings.database_statement_timeout_seconds
    )
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_pool_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        connect_args={
            "connect_timeout": settings.database_connect_timeout_seconds,
            "options": f"-c statement_timeout={statement_timeout_ms}",
        },
    )


engine = create_database_engine()
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def database_pool_snapshot() -> DatabasePoolSnapshot:
    pool_size = engine.pool.size()
    max_overflow = settings.database_pool_max_overflow
    capacity = pool_size + max_overflow
    checked_out = engine.pool.checkedout()
    return DatabasePoolSnapshot(
        pool_size=pool_size,
        max_overflow=max_overflow,
        capacity=capacity,
        checked_in=engine.pool.checkedin(),
        checked_out=checked_out,
        overflow=max(engine.pool.overflow(), 0),
        utilization_percent=round(checked_out / capacity * 100, 1),
        saturated=checked_out >= capacity,
    )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def set_local_statement_timeout(db: Session, timeout_seconds: float) -> None:
    timeout_ms = _statement_timeout_ms(timeout_seconds)
    db.execute(
        text("SELECT set_config('statement_timeout', :timeout_ms, true)"),
        {"timeout_ms": str(timeout_ms)},
    )


def set_local_hnsw_search_options(
    db: Session,
    *,
    ef_search: int,
    max_scan_tuples: int,
) -> None:
    db.execute(
        text(
            """
            SELECT
                set_config('hnsw.iterative_scan', 'strict_order', true),
                set_config('hnsw.ef_search', :ef_search, true),
                set_config('hnsw.max_scan_tuples', :max_scan_tuples, true)
            """
        ),
        {
            "ef_search": str(ef_search),
            "max_scan_tuples": str(max_scan_tuples),
        },
    )
