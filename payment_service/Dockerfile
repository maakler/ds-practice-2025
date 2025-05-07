# ──────────────────────────────────────────────────────────────
# base image
FROM python:3.11

# ──────────────────────────────────────────────────────────────
# working dir
WORKDIR /app

# ──────────────────────────────────────────────────────────────
# copy pip requirements
COPY ./payment_service/requirements.txt .

# install everything
RUN pip install --no-cache-dir -r requirements.txt

# ──────────────────────────────────────────────────────────────
# copy service code
COPY ./payment_service/src /app/payment_service/src

# ──────────────────────────────────────────────────────────────
# expose gRPC port + HTTP façade port 80
EXPOSE 7100 80

# ──────────────────────────────────────────────────────────────
# use the helper script as entrypoint
COPY ./payment_service/start.sh /app/payment_service/start.sh
ENTRYPOINT ["/app/payment_service/start.sh"]