"""
Tiny HTTP façade for Payment gRPC service so the dashboard
can hit /charge and /refund from the browser.
"""
import os, json, grpc
from flask import Flask, request, jsonify
from waitress import serve

import sys
FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/DB'))
sys.path.insert(0, PROTO_DIR)

import payment_pb2 as pp
import payment_pb2_grpc as pp_grpc

PAY_GRPC_PORT = os.getenv("PAY_PORT", "7100")
channel = grpc.insecure_channel(f"localhost:{PAY_GRPC_PORT}")
pay_stub = pp_grpc.PaymentStub(channel)

app = Flask(__name__)

@app.after_request
def add_cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return r

@app.route("/charge", methods=["POST"])
def charge():
    data = request.get_json(force=True)
    r = pay_stub.Prepare(pp.PrepareReq(order_id=data["order"], amount=data["amount"]))
    if not r.ready:
        return jsonify(error="not ready"), 400
    pay_stub.Commit(pp.CommitReq(order_id=data["order"]))
    return jsonify(success=True)

@app.route("/refund", methods=["POST"])
def refund():
    data = request.get_json(force=True)
    pay_stub.Abort(pp.AbortReq(order_id=data["order"]))
    return jsonify(refunded=True)

if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=80)
