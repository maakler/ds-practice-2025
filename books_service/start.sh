#!/usr/bin/env bash
# small helper: launch gRPC server first, then (only on primary) the HTTP façade
python /app/books_service/src/server.py &

if [[ "$ROLE" == "primary" ]]; then
  # one simple Flask + Waitress process that exposes /read and /delta
  python /app/books_service/src/http_api.py
else
  # keep backup container alive
  tail -f /dev/null
fi
