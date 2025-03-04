import os
import sys
import uuid
import logging
import threading

from flask import Flask, request, jsonify
from flask_cors import CORS
import grpc

# Path to compiled proto stubs
FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/checkout'))
sys.path.insert(0, PROTO_DIR)

import checkout_pb2 as pb
import checkout_pb2_grpc as pb_grpc

logging.basicConfig(
    level=logging.INFO,
    format='[Orchestrator] %(asctime)s %(levelname)s: %(message)s'
)

app = Flask(__name__)
CORS(app)

# Create gRPC channels & stubs (we do this once on startup).
# You can also do it per request, but reusing channels is generally fine.
fraud_channel = grpc.insecure_channel(os.getenv("FRAUD_SERVICE_HOST", "fraud_service:50051"))
verification_channel = grpc.insecure_channel(os.getenv("VERIF_SERVICE_HOST", "verification_service:50052"))
suggestions_channel = grpc.insecure_channel(os.getenv("SUGG_SERVICE_HOST", "suggestions_service:50053"))

fraud_stub = pb_grpc.FraudServiceStub(fraud_channel)
verification_stub = pb_grpc.VerificationServiceStub(verification_channel)
suggestions_stub = pb_grpc.SuggestionsServiceStub(suggestions_channel)

@app.route('/', methods=['GET'])
def index():
    return "Orchestrator is up", 200

@app.route('/checkout', methods=['POST'])
def checkout():
    """
    Handles the REST request for placing an order.
    - Validates the JSON payload.
    - Calls fraud, verification, suggestions in parallel.
    - Returns JSON with "Order Approved" or "Order Rejected" plus optional suggestions.
    """
    data = request.get_json() or {}
    logging.info("Received /checkout request")

    # Basic validation
    items = data.get('items', [])
    if not items or not isinstance(items, list):
        return jsonify({"error": {"message": "Invalid 'items' field"}}), 400

    user = data.get('user', {})
    if not user.get('name') or not user.get('contact'):
        return jsonify({"error": {"message": "User 'name' and 'contact' are required"}}), 400

    cc_info = data.get('creditCard', {})
    if not cc_info.get('number') or not cc_info.get('expirationDate') or not cc_info.get('cvv'):
        return jsonify({"error": {"message": "Credit card info incomplete"}}), 400

    # Calculate total price in a naive way (assuming each item has a "quantity" and a "price")
    # Or the frontend might pass total price directly. We'll just assume:
    total_price = 0.0
    for it in items:
        price = it.get('price', 0.0)
        qty = it.get('quantity', 1)
        total_price += price * qty

    order_id = str(uuid.uuid4())

    # Build a gRPC OrderRequest
    order_request = pb.OrderRequest(
        order_id=order_id,
        total_price=total_price,
        user_name=user['name'],
        user_contact=user['contact'],
        credit_card_number=cc_info['number'],
        credit_card_expiration=cc_info['expirationDate'],
        credit_card_cvv=cc_info['cvv'],
    )
    # Add each item
    for it in items:
        name = it.get('name', 'unknown')
        qty = it.get('quantity', 1)
        price = it.get('price', 0.0)
        order_request.items.add(name=name, quantity=qty, price=price)

    # We will store results in a dict that threads can update
    results = {
        "fraud": None,
        "verification": None,
        "suggestions": None
    }

    # Define worker functions
    def call_fraud():
        try:
            resp = fraud_stub.CheckFraud(order_request, timeout=5.0)
            results["fraud"] = resp
            logging.info(f"FraudService result: is_fraud={resp.is_fraud}, reason={resp.reason}")
        except grpc.RpcError as e:
            logging.error(f"FraudService call failed: {e}")
            # If fail, treat as is_fraud = True (safe approach) or handle differently
            results["fraud"] = pb.FraudResponse(is_fraud=True, reason="Service error")

    def call_verification():
        try:
            resp = verification_stub.VerifyOrder(order_request, timeout=5.0)
            results["verification"] = resp
            logging.info(f"VerificationService result: is_valid={resp.is_valid}, msg={resp.message}")
        except grpc.RpcError as e:
            logging.error(f"VerificationService call failed: {e}")
            # If fail, treat as not valid or handle differently
            results["verification"] = pb.VerificationResponse(is_valid=False, message="Service error")

    def call_suggestions():
        try:
            resp = suggestions_stub.GetSuggestions(order_request, timeout=5.0)
            results["suggestions"] = resp
            logging.info(f"SuggestionsService returned {len(resp.suggestions)} suggestions")
        except grpc.RpcError as e:
            logging.error(f"SuggestionsService call failed: {e}")
            # If fail, no suggestions
            results["suggestions"] = pb.SuggestionsResponse(suggestions=[])

    # Spawn threads for parallel calls
    t1 = threading.Thread(target=call_fraud)
    t2 = threading.Thread(target=call_verification)
    t3 = threading.Thread(target=call_suggestions)

    # Start threads
    t1.start()
    t2.start()
    t3.start()

    # Wait for them to finish
    t1.join()
    t2.join()
    t3.join()

    fraud_resp = results["fraud"]
    verify_resp = results["verification"]
    sugg_resp = results["suggestions"]

    # Decide final status
    if fraud_resp.is_fraud or not verify_resp.is_valid:
        status = "Order Rejected"
        suggested_books = []
    else:
        status = "Order Approved"
        # Convert suggestions to JSON
        suggested_books = []
        if sugg_resp:
            for sb in sugg_resp.suggestions:
                suggested_books.append({
                    "bookId": sb.book_id,
                    "title": sb.title,
                    "author": sb.author
                })

    response_body = {
        "orderId": order_id,
        "status": status,
        "suggestedBooks": suggested_books
    }

    return jsonify(response_body), 200

if __name__ == '__main__':
    port = os.getenv("ORCH_PORT", "8081")
    logging.info(f"Orchestrator starting on port {port}")
    app.run(host='0.0.0.0', port=int(port), debug=False)
