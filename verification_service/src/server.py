import os
import logging
import grpc
from concurrent import futures
import re

import sys
FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/checkout'))
sys.path.insert(0, PROTO_DIR)

import checkout_pb2 as pb
import checkout_pb2_grpc as pb_grpc

logging.basicConfig(
    level=logging.INFO,
    format='[VerificationService] %(asctime)s %(levelname)s: %(message)s'
)

class VerificationService(pb_grpc.VerificationServiceServicer):
    def VerifyOrder(self, request, context):
        """
        Validates basic conditions:
         - At least 1 item
         - Credit card number is 16 digits
         - Not empty user name/contact
         - total_price >= 0
        """
        logging.info(f"Received verification request for order_id={request.order_id}, user={request.user_name}")

        # Basic validations
        if len(request.items) == 0:
            return pb.VerificationResponse(is_valid=False, message="No items in order")

        # Check credit card number format (simplified)
        card_pattern = r"^\d{16}$"
        if not re.match(card_pattern, request.credit_card_number):
            return pb.VerificationResponse(is_valid=False, message="Credit card number must be 16 digits")

        if not request.user_name or not request.user_contact:
            return pb.VerificationResponse(is_valid=False, message="User name or contact is missing")

        if request.total_price < 0:
            return pb.VerificationResponse(is_valid=False, message="Total price cannot be negative")

        logging.info("Verification passed.")
        return pb.VerificationResponse(is_valid=True, message="All checks passed")

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_VerificationServiceServicer_to_server(VerificationService(), server)
    port = os.getenv("VERIFICATION_SERVICE_PORT", "50052")
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logging.info(f"Verification Service is listening on port {port}")
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
