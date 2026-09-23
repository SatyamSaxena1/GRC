from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.dburl import database_url
from app.models import Base

# ponytail: create_all is the dev path; Alembic owns the schema for anything real
# (see alembic/ and ADR-001). DATABASE_URL switches SQLite <-> PostgreSQL.
DATABASE_URL = database_url()
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


def set_firm(db: Session, audit_firm_id: str | None) -> None:
    """The second tenancy axis. Firm-owned rows (onboarding requests, staffing,
    and a firm's view of its engagements) are scoped by audit_firm_id, not by
    org_id, so RLS needs its own GUC for them — see the firm policies in
    alembic/versions/*_firm_onboarding.py. A no-op on SQLite, as with set_tenant."""
    if audit_firm_id and db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT set_config('app.firm_id', :firm, true)"),
                   {"firm": audit_firm_id})


def get_session():
    # expire_on_commit=False: the default expires every attribute at commit,
    # so a route that does `db.commit(); return {"id": obj.id, ...}` re-SELECTs
    # obj afterward — and app.tenant_id/app.firm_id are set with SET LOCAL
    # (set_tenant/set_firm above), scoped to the transaction that just ended.
    # Under FORCE ROW LEVEL SECURITY that re-SELECT sees no tenant GUC, matches
    # nothing, and SQLAlchemy raises ObjectDeletedError on a row that is very
    # much still there. The in-memory values are already correct — they were
    # set (or postfetched) earlier in the same transaction, while the GUC was
    # live — so there is nothing to gain by re-reading them anyway.
    with Session(engine, expire_on_commit=False) as session:
        yield session


@contextmanager
def session_scope():
    """For background jobs, which have no request to hang a dependency off."""
    with Session(engine, expire_on_commit=False) as session:
        yield session
