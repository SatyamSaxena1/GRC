import os
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.models import Base

# ponytail: create_all is the dev path; Alembic owns the schema for anything real
# (see alembic/ and ADR-001). DATABASE_URL switches SQLite <-> PostgreSQL.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./grc.db")
engine = create_engine(DATABASE_URL)


def is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


def init_db() -> None:
    Base.metadata.create_all(engine)


def set_tenant(db: Session, org_id: str | None) -> None:
    """Bind the tenant to the transaction so Postgres RLS can enforce isolation
    in the database, not only in application WHERE clauses. A no-op on SQLite,
    where application-level scoping is the only layer available."""
    if org_id and db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"),
                   {"tenant": org_id})


def get_session():
    with Session(engine) as session:
        yield session


@contextmanager
def session_scope():
    """For background jobs, which have no request to hang a dependency off."""
    with Session(engine) as session:
        yield session
