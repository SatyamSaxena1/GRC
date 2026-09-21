"""One place that reads DATABASE_URL, shared by the app and Alembic.

Hosts like Render, Heroku and Railway hand out `postgres://` or `postgresql://`,
which SQLAlchemy would route to psycopg2 — this project ships psycopg 3 only.
"""

import os


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite:///./grc.db")
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url[len(scheme):]
    return url
