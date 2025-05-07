# ──────────────────────────────────────────────────────────────
# base image
FROM python:3.11

# ──────────────────────────────────────────────────────────────
# working dir
WORKDIR /app

# ──────────────────────────────────────────────────────────────
# copy pip requirements
COPY ./books_service/requirements.txt .

# install everything
RUN pip install --no-cache-dir -r requirements.txt

# ──────────────────────────────────────────────────────────────
# copy service code
COPY ./books_service/src /app/books_service/src

# ──────────────────────────────────────────────────────────────
# expose gRPC port + HTTP façade port 80
EXPOSE 7000 80

# ──────────────────────────────────────────────────────────────
# use the helper script as entrypoint
COPY ./books_service/start.sh /app/books_service/start.sh
ENTRYPOINT ["/app/books_service/start.sh"]
