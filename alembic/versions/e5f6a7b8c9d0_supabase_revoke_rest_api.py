"""revoke Supabase auto-exposed REST API grants

Supabase runs PostgREST, which serves every table in `public` to the `anon` and
`authenticated` roles over HTTP. This app talks to Postgres directly as the
`postgres` role and never uses PostgREST, so the tables without RLS
(organizations, users, audit_firms, and the association tables) would otherwise
be reachable through the auto API. Cut the grants entirely.

Postgres only — on SQLite these roles don't exist, so it's a no-op, matching
the RLS migrations' convention (see a1b2c3d4e5f6).

Revision ID: e5f6a7b8c9d0
Revises: d3e4f5a6b7c8
"""

from __future__ import annotations

from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated")
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated")
    op.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE ALL ON TABLES FROM anon, authenticated"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE ALL ON SEQUENCES FROM anon, authenticated"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated")
    op.execute("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT ALL ON TABLES TO anon, authenticated"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT ALL ON SEQUENCES TO anon, authenticated"
    )
