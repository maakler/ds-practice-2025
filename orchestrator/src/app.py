import os
import sys
import uuid
import threading
import logging
import json

from flask import Flask, request, jsonify
from flask_cors import CORS
import grpc

import sys
FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/checkout'))
sys.path.insert(0, PROTO_DIR)
import checkout_pb2 as pb
import checkout_pb2_grpc as pb_grpc

PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/queue'))
sys.path.insert(0, PROTO_DIR)
import queue_pb2 as qp
import queue_pb2_grpc as qp_grpc



app = Flask(__name__)
CORS(app)
logging.basicConfig(
    level=logging.INFO,
    format='[Orchestrator] %(asctime)s %(levelname)s: %(message)s'
)

# Connect to the 3 microservices
verif_channel = grpc.insecure_channel(os.getenv("VERIF_HOST", "verification_service:50052"))
fraud_channel = grpc.insecure_channel(os.getenv("FRAUD_HOST", "fraud_service:50051"))
sugg_channel  = grpc.insecure_channel(os.getenv("SUGG_HOST",  "suggestions_service:50053"))

verif_stub = pb_grpc.VerificationServiceStub(verif_channel)
fraud_stub = pb_grpc.FraudServiceStub(fraud_channel)
sugg_stub  = pb_grpc.SuggestionsServiceStub(sugg_channel)

# Connect to the Order Queue
queue_channel = grpc.insecure_channel(os.getenv("ORDER_QUEUE_HOST", "order_queue:6000"))
queue_stub = qp_grpc.OrderQueueStub(queue_channel)

@app.route('/run_demo', methods=['GET'])
def run_demo():
    """
    Demonstrates a partial-order event flow using vector clocks.
    We'll do something simpler than a real checkout:
      1) Orchestrator calls InitOrder on all 3 services
      2) Parallel: VerifyItems & VerifyUserData
      3) Then sequential: VerifyCreditCard -> CheckUserFraud -> CheckCreditCardFraud -> GenerateSuggestions
    We'll track each step's vector clock in a logs list.
    Returns JSON with final VC and logs.
    """
    logs = []
    order_id = str(uuid.uuid4())
    logs.append(f"[Orchestrator] Starting demo for order_id={order_id}")

    # 1) Build a dummy order that won't fail checks
    # (Add or remove fields as your microservice expects)
    user = pb.UserData(name="DemoUser", contact="demo@example.com")
    cc   = pb.CreditCardData(number="1234123412341234", expirationDate="12/25", cvv="123")
    items = [pb.ItemData(name="DemoBook", quantity=1, price=42.0)]
    order_data = pb.OrderData(user=user, credit_card=cc, items=items)

    init_req = pb.OrderInitRequest(order_id=order_id, data=order_data)

    # 2) Call InitOrder on each service
    v_init = verif_stub.InitOrder(init_req)
    logs.append(f"[Orchestrator] verif.InitOrder => success={v_init.success}, VC={v_init.vc}")
    f_init = fraud_stub.InitOrder(init_req)
    logs.append(f"[Orchestrator] fraud.InitOrder => success={f_init.success}, VC={f_init.vc}")
    s_init = sugg_stub.InitOrder(init_req)
    logs.append(f"[Orchestrator] sugg.InitOrder => success={s_init.success}, VC={s_init.vc}")

    # We'll assume all start with [0,0,0], but each call sets their local state

    # 3) Parallel calls: (a) VerifyItems, (b) VerifyUserData
    # we spawn 2 threads
    results = {}
    base_vc = v_init.vc  # We'll pass the same VC to both calls

    def event_a():
        req_a = pb.OrderEventRequest(order_id=order_id, vc=base_vc)
        resp_a = verif_stub.VerifyItems(req_a)
        results["a"] = resp_a
        logs.append(f"[Orchestrator] verif.VerifyItems => fail={resp_a.fail}, msg={resp_a.message}, VC={resp_a.vc}")

    def event_b():
        req_b = pb.OrderEventRequest(order_id=order_id, vc=base_vc)
        resp_b = verif_stub.VerifyUserData(req_b)
        results["b"] = resp_b
        logs.append(f"[Orchestrator] verif.VerifyUserData => fail={resp_b.fail}, msg={resp_b.message}, VC={resp_b.vc}")

    t_a = threading.Thread(target=event_a)
    t_b = threading.Thread(target=event_b)
    t_a.start(); t_b.start()
    t_a.join(); t_b.join()

    if results["a"].fail or results["b"].fail:
        logs.append("[Orchestrator] Early fail, skipping further steps.")
        final_vc = results["a"].vc if results["a"].fail else results["b"].vc
        # Optionally ClearOrder
        _clear_all(order_id, final_vc, logs)
        return jsonify({
            "orderId": order_id,
            "finalVC": final_vc,
            "logs": logs
        }), 200

    # 4) Next steps in sequence:
    # c) VerifyCreditCard
    req_c = pb.OrderEventRequest(order_id=order_id, vc=results["a"].vc) # or merge (a) and (b) if desired
    r_c = verif_stub.VerifyCreditCard(req_c)
    logs.append(f"[Orchestrator] verif.VerifyCreditCard => fail={r_c.fail}, msg={r_c.message}, VC={r_c.vc}")
    if r_c.fail:
        _clear_all(order_id, r_c.vc, logs)
        return jsonify({"orderId": order_id, "finalVC": r_c.vc, "logs": logs}), 200

    # d) CheckUserFraud
    # We'll pass r_c's VC in
    req_d = pb.OrderEventRequest(order_id=order_id, vc=r_c.vc)
    r_d = fraud_stub.CheckUserFraud(req_d)
    logs.append(f"[Orchestrator] fraud.CheckUserFraud => fail={r_d.fail}, msg={r_d.message}, VC={r_d.vc}")
    if r_d.fail:
        _clear_all(order_id, r_d.vc, logs)
        return jsonify({"orderId": order_id, "finalVC": r_d.vc, "logs": logs}), 200

    # e) CheckCreditCardFraud
    # merge r_c and r_d if you want strict partial order
    merged_cd = [max(r_c.vc[i], r_d.vc[i]) for i in range(len(r_c.vc))]
    req_e = pb.OrderEventRequest(order_id=order_id, vc=merged_cd)
    r_e = fraud_stub.CheckCreditCardFraud(req_e)
    logs.append(f"[Orchestrator] fraud.CheckCreditCardFraud => fail={r_e.fail}, msg={r_e.message}, VC={r_e.vc}")
    if r_e.fail:
        _clear_all(order_id, r_e.vc, logs)
        return jsonify({"orderId": order_id, "finalVC": r_e.vc, "logs": logs}), 200

    # f) GenerateSuggestions
    req_f = pb.OrderEventRequest(order_id=order_id, vc=r_e.vc)
    r_f = sugg_stub.GenerateSuggestions(req_f)
    logs.append(f"[Orchestrator] sugg.GenerateSuggestions => fail={r_f.fail}, msg={r_f.message}, VC={r_f.vc}")

    final_vc = list(r_f.vc)
    if r_f.fail:
        _clear_all(order_id, final_vc, logs)
        return jsonify({"orderId": order_id, "finalVC": final_vc, "logs": logs}), 200

    # If everything passed, we can ClearOrder or not, just for the sake of cleaning up
    _clear_all(order_id, final_vc, logs)

    logs.append("[Orchestrator] Demo flow completed successfully!")
    return jsonify({
        "orderId": order_id,
        "finalVC": final_vc,
        "logs": logs
    }), 200

def _clear_all(order_id, final_vc, logs):
    """Utility to broadcast ClearOrder with final_vc to all 3 services."""
    clr_req = pb.OrderClearRequest(order_id=order_id, final_vc=final_vc)
    try:
        v_res = verif_stub.ClearOrder(clr_req)
        logs.append(f"[ClearOrder] verif => {v_res.success}, {v_res.message}")
    except:
        logs.append("[ClearOrder] verif => error")

    try:
        f_res = fraud_stub.ClearOrder(clr_req)
        logs.append(f"[ClearOrder] fraud => {f_res.success}, {f_res.message}")
    except:
        logs.append("[ClearOrder] fraud => error")

    try:
        s_res = sugg_stub.ClearOrder(clr_req)
        logs.append(f"[ClearOrder] sugg => {s_res.success}, {s_res.message}")
    except:
        logs.append("[ClearOrder] sugg => error")


@app.route('/checkout_extended', methods=['POST'])
def checkout_extended():
    data = request.get_json() or {}
    order_id = str(uuid.uuid4())
    logging.info(f"New checkout request for order_id={order_id}")

    # 1) Initialize the order in all 3 services
    # Convert the raw dict to pb.OrderData via naive approach
    # or just store JSON in the proto for demonstration
    user = pb.UserData(name=data.get("user", {}).get("name", ""), 
                       contact=data.get("user", {}).get("contact", ""))
    cc = pb.CreditCardData(number=data.get("creditCard", {}).get("number", ""),
                           expirationDate=data.get("creditCard", {}).get("expirationDate", ""),
                           cvv=data.get("creditCard", {}).get("cvv", ""))

    items = []
    for it in data.get("items", []):
        item_name = it.get("name") or it.get("title") or "Unknown"
        qty       = int(it.get("quantity", 0))
        price     = float(it.get("price", 0.0))
        items.append(pb.ItemData(name=item_name, quantity=qty, price=price))


    order_data = pb.OrderData(user=user, credit_card=cc, items=items)

    init_req = pb.OrderInitRequest(order_id=order_id, data=order_data)
    try:
        v_init = verif_stub.InitOrder(init_req, timeout=5)
        f_init = fraud_stub.InitOrder(init_req, timeout=5)
        s_init = sugg_stub.InitOrder(init_req, timeout=5)
    except grpc.RpcError as e:
        logging.error(f"InitOrder error: {e}")
        return jsonify({"error": "Initialization failure"}), 500

    # For simplicity, assume they all start with [0,0,0]. We'll keep track of updated VCs as we go.
    base_vc = v_init.vc

    # 2) We define partial order events:
    # (a) VerifyItems (parallel with b)
    # (b) VerifyUserData
    # (c) VerifyCreditCard (depends on a, might overlap with b)
    # (d) CheckUserFraud (depends on b)
    # (e) CheckCreditCardFraud (depends on c & d)
    # (f) GenerateSuggestions (depends on e)

    results = {}
    def event_a():
        req = pb.OrderEventRequest(order_id=order_id, vc=base_vc)
        resp = verif_stub.VerifyItems(req, timeout=5)
        if resp.fail:
            raise Exception(resp.message)
        results["a"] = resp
    def event_b():
        req = pb.OrderEventRequest(order_id=order_id, vc=base_vc)
        resp = verif_stub.VerifyUserData(req, timeout=5)
        if resp.fail:
            raise Exception(resp.message)
        results["b"] = resp

    tA = threading.Thread(target=event_a)
    tB = threading.Thread(target=event_b)
    tA.start(); tB.start(); tA.join(); tB.join()

    # If either event failed, short-circuit
    if "a" not in results or "b" not in results:
        # Clear order on all services
        # ...
        return jsonify({"orderId": order_id, "status": "Order Rejected"}), 400

    # 3) event c: depends on a’s VC
    req_c = pb.OrderEventRequest(order_id=order_id, vc=results["a"].vc)
    r_c = verif_stub.VerifyCreditCard(req_c, timeout=5)
    if r_c.fail:
        clear_all(order_id, r_c.vc)
        return jsonify({"orderId": order_id, "status": "Order Rejected", "reason": r_c.message}), 400

    # 4) event d: depends on b’s VC
    req_d = pb.OrderEventRequest(order_id=order_id, vc=results["b"].vc)
    r_d = fraud_stub.CheckUserFraud(req_d, timeout=5)
    if r_d.fail:
        clear_all(order_id, r_d.vc)
        return jsonify({"orderId": order_id, "status": "Order Rejected", "reason": r_d.message}), 400

    # 5) event e: depends on both c & d => merge VCs
    merged_vc = [ max(r_c.vc[i], r_d.vc[i]) for i in range(len(r_c.vc)) ]
    req_e = pb.OrderEventRequest(order_id=order_id, vc=merged_vc)
    r_e = fraud_stub.CheckCreditCardFraud(req_e, timeout=5)
    if r_e.fail:
        clear_all(order_id, r_e.vc)
        return jsonify({"orderId": order_id, "status": "Order Rejected", "reason": r_e.message}), 400

    # 6) event f: depends on e
    req_f = pb.OrderEventRequest(order_id=order_id, vc=r_e.vc)
    r_f = sugg_stub.GenerateSuggestions(req_f, timeout=5)
    if r_f.fail:
        clear_all(order_id, r_f.vc)
        return jsonify({"orderId": order_id, "status": "Order Rejected", "reason": r_f.message}), 400

    final_vc = list(r_f.vc)

    # 7) If we reach this point => everything is valid => broadcast Clear OR after we enqueue
    # In some flows, we might only Clear after the queue-based execution is done, but for now, we can do it immediately:
    # But let's first push the order to the queue for “execution” by the Executor leader
    # We'll store the entire user JSON in 'order_data' for demonstration.
    # Decide a priority (example: sum of item prices or data["priority"] or 1)
    total_price = sum( it["price"]*it["quantity"] for it in data.get("items", []) )
    # Serialize data as bytes:
    serialized_data = json.dumps(data).encode('utf-8')
    enqueue_req = qp.EnqueueRequest(order_id=order_id, priority=total_price, order_data=serialized_data)

    try:
        eq_resp = queue_stub.Enqueue(enqueue_req, timeout=5)
        if not eq_resp.success:
            logging.error("Failed to enqueue order")
    except grpc.RpcError as e:
        logging.error(f"Queue enqueue error: {e}")

    # Clear local data from the 3 services
    clear_all(order_id, final_vc)

    # Return success to user
    suggestions_list = []
    for s in r_f.suggestions:
        suggestions_list.append({"bookId": s.book_id, "title": s.title, "author": s.author})

    return jsonify({
        "orderId": order_id,
        "status": "Order Approved",
        "suggestedBooks": suggestions_list,
        "finalVC": final_vc
    }), 200

def clear_all(order_id, final_vc):
    # Utility function to call ClearOrder on all 3 services
    clr_req = pb.OrderClearRequest(order_id=order_id, final_vc=final_vc)
    try:
        verif_stub.ClearOrder(clr_req, timeout=3)
    except:
        pass
    try:
        fraud_stub.ClearOrder(clr_req, timeout=3)
    except:
        pass
    try:
        sugg_stub.ClearOrder(clr_req, timeout=3)
    except:
        pass

@app.route('/', methods=['GET'])
def index():
    return "Orchestrator up", 200

if __name__ == '__main__':
    port = os.getenv("ORCH_PORT", "8081")
    logging.info(f"Starting Orchestrator on {port}")
    app.run(host='0.0.0.0', port=int(port), debug=False)