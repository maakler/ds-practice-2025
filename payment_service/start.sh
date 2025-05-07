#!/usr/bin/env bash
python /app/payment_service/src/server.py &          # gRPC
python /app/payment_service/src/http_api.py          # HTTP façade
