#!/bin/sh
set -e

# RUN_MIGRATIONS defaults to true for local compose / dev, false in production
RUN_MIG="${RUN_MIGRATIONS:-true}"

if [ "$RUN_MIG" = "true" ] || [ "$RUN_MIG" = "1" ]; then
    echo "[entrypoint] RUN_MIGRATIONS is true: running alembic upgrade head..."
    alembic upgrade head
else
    echo "[entrypoint] RUN_MIGRATIONS is '$RUN_MIG': skipping startup migrations."
fi

# Run the command passed or default uvicorn
if [ $# -eq 0 ]; then
    exec uvicorn nexafreight.main:app --host 0.0.0.0 --port "${PORT:-8000}"
else
    exec "$@"
fi
