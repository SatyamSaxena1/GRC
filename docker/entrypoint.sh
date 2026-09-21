#!/bin/sh
# Apply schema, then run whatever CMD was given (uvicorn by default).
# RUN_MIGRATIONS=0 skips the upgrade — used where migrations run as a separate
# pre-deploy step under a different (owner) database role, e.g. Render.
set -e
if [ "${RUN_MIGRATIONS:-1}" != "0" ]; then
  echo "==> alembic upgrade head"
  alembic upgrade head
fi
echo "==> starting: $*"
exec "$@"
