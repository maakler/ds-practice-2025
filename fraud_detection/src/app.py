import os
import logging
import grpc
from concurrent import futures

# Import the generated code from your .proto
import sys
FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/checkout'))
sys.path.insert(0, PROTO_DIR)

import checkout_pb2 as pb
import checkout_pb2_grpc as pb_grpc

logging.basicConfig(
    level=logging.INFO,
    format='[FraudService] %(asctime)s %(levelname)s: %(message)s'
)

class FraudService(pb_grpc.FraudServiceServicer):
    def CheckFraud(self, request, context):
        """Implements a simple rule: if total_price > 1000 => is_fraud = True"""
        logging.info(f"Received fraud check request for order_id={request.order_id}, "
                     f"user={request.user_name}, total={request.total_price}")
        
        if request.total_price > 1000:
            logging.info("Order flagged as FRAUD: total price exceeds 1000.")
            return pb.FraudResponse(is_fraud=True, reason="Total price exceeds threshold")
        else:
            logging.info("No fraud detected.")
            return pb.FraudResponse(is_fraud=False, reason="No rules triggered")

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_FraudServiceServicer_to_server(FraudService(), server)
    port = os.getenv("FRAUD_SERVICE_PORT", "50051")
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logging.info(f"Fraud Service is listening on port {port}")
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
