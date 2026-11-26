import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./stock_brief.db")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
engine_options = {
    "connect_args": {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    "pool_pre_ping": True,
}
if not DATABASE_URL.startswith("sqlite"):
    engine_options["pool_recycle"] = int(os.getenv("DB_POOL_RECYCLE_SECONDS", "300"))
    if os.getenv("STOCK_BRIEF_LOW_MEMORY") == "1":
        engine_options.update(pool_size=2, max_overflow=0, pool_timeout=30)
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def require_postgresql(bind) -> None:
    """Measurement scripts refuse to run against a non-PostgreSQL DB (e.g. a missing DATABASE_URL)."""
    if bind.dialect.name != "postgresql":
        raise SystemExit(f"DB dialect가 {bind.dialect.name}입니다. DATABASE_URL을 PostgreSQL로 지정하세요.")


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
