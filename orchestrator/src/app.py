import sys
import os
import uuid
import logging
import json

# This set of lines are needed to import the gRPC stubs.
# The path of the stubs is relative to the current file, or absolute inside the container.
# Change these lines only if strictly needed.
FILE = __file__ if '__file__' in globals() else os.getenv("PYTHONFILE", "")
fraud_detection_grpc_path = os.path.abspath(os.path.join(FILE, '../../../utils/pb/fraud_detection'))
sys.path.insert(0, fraud_detection_grpc_path)
import fraud_detection_pb2 as fraud_detection
import fraud_detection_pb2_grpc as fraud_detection_grpc

import grpc
#test
def greet(name='you'):
    # Establish a connection with the fraud-detection gRPC service.
    with grpc.insecure_channel('fraud_detection:50051') as channel:
        # Create a stub object.
        stub = fraud_detection_grpc.HelloServiceStub(channel)
        # Call the service through the stub object.
        response = stub.SayHello(fraud_detection.HelloRequest(name=name))
    return response.greeting

# Import Flask.
# Flask is a web framework for Python.
# It allows you to build a web application quickly.
# For more information, see https://flask.palletsprojects.com/en/latest/
from flask import Flask, request, jsonify
from flask_cors import CORS
import json

# Create a simple Flask app.
app = Flask(__name__)
# Enable CORS for the app.
CORS(app, resources={r'/*': {'origins': '*'}})

# Define a GET endpoint.
@app.route('/', methods=['GET'])
def index():
    """
    Responds with 'Hello, [name]' when a GET request is made to '/' endpoint.
    """
    # Test the fraud-detection gRPC service.
    response = greet(name='orchestrator')
    # Return the response.
    return response


# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

@app.route('/checkout', methods=['POST'])
def checkout():
    """
    Handles POST requests to /checkout from the frontend.
    Responds with a JSON object containing order ID, status, and suggested books,
    following the OpenAPI spec in bookstore.yaml.
    """
    try:
        # Try to parse JSON, fallback if Content-Type is wrong
        try:
            request_data = request.get_json()
        except Exception:
            if request.data:
                request_data = json.loads(request.data.decode('utf-8'))
            else:
                request_data = None

        # Validate request data
        if not request_data or 'items' not in request_data:
            return jsonify({'error': 'Invalid request: "items" field is required'}), 400

        # Validate items field
        items = request_data['items']
        if not isinstance(items, list) or not items:
            return jsonify({'error': 'Invalid request: "items" must be a non-empty list'}), 400

        # Validate each item (expecting 'name' and 'quantity' from frontend)
        for item in items:
            if not isinstance(item, dict) or 'name' not in item or 'quantity' not in item:
                return jsonify({
                    'error': 'Invalid item format: each item must have "name" and "quantity"'
                }), 400
            if not isinstance(item['quantity'], int) or item['quantity'] <= 0:
                return jsonify({'error': 'Invalid request: "quantity" must be a positive integer'}), 400

        # Generate a unique order ID
        order_id = str(uuid.uuid4())

        # Simulate order processing
        order_status = 'Order Approved'
        suggested_books = [
            {'bookId': '123', 'title': 'The Best Book', 'author': 'Author 1'},
            {'bookId': '456', 'title': 'The Second Best Book', 'author': 'Author 2'}
        ]

        # Build and return response
        order_status_response = {
            'orderId': order_id,
            'status': order_status,
            'suggestedBooks': suggested_books
        }
        return jsonify(order_status_response), 200

    except ValueError:
        return jsonify({'error': 'Invalid JSON format'}), 400
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500


if __name__ == '__main__':
    # Run the app in debug mode to enable hot reloading.
    # This is useful for development.
    # The default port is 5000.
    app.run(host='0.0.0.0')
