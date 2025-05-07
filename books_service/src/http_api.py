"""
Light‑weight HTTP façade for the gRPC BooksDB primary replica.
Only READ and delta‑WRITE are exposed so the demo dashboard
can talk with plain fetch() from the browser.
Start it **only** in the *primary* container.
"""
import os, json, grpc
from flask import Flask, request, jsonify, make_response
from waitress import serve                                   # prod‑grade WSGI

# ─── import stubs ────────────────────────────────────────────
import sys
FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/DB'))
sys.path.insert(0, PROTO_DIR)

import books_pb2 as bp
import books_pb2_grpc as bp_grpc

# ─── gRPC stub to local BooksDB (same container) ────────────
BOOKS_GRPC_PORT = os.getenv("BOOKS_PORT", "7000")
channel = grpc.insecure_channel(f"localhost:{BOOKS_GRPC_PORT}")
db_stub = bp_grpc.BooksDBStub(channel)

app = Flask(__name__)

@app.after_request
def add_cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return r

@app.route("/read")
def read():
    title = request.args.get("title", "")
    stock = db_stub.Read(bp.ReadReq(title=title)).stock
    print(f"[HTTP] READ  {title}  → {stock}", flush=True)
    return jsonify(stock=stock)

@app.route("/delta", methods=["POST"])
def delta():
    data = request.get_json(force=True)
    title = data["title"]; delta = int(data["delta"])
    cur   = db_stub.Read(bp.ReadReq(title=title)).stock
    try:
        ok = db_stub.Write(bp.WriteReq(title=title, new_stock=cur+delta)).success
    except grpc.RpcError:
        ok = False                       # replication failed but primary updated itself
    print(f"[HTTP] WRITE {title}  Δ={delta:+}  new={cur+delta}", flush=True)
    return jsonify(title=title, new_stock=cur+delta, success=ok)

if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=80)          # HTTP port 80 inside container
