#!/bin/sh
# Apply schema, then run whatever CMD was given (uvicorn by default).
set -e
echo "==> alembic upgrade head"
alembic upgrade head
echo "==> starting: $*"
exec "$@"
