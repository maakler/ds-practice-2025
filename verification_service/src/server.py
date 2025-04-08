import os
import logging
import threading
import grpc
from concurrent import futures

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

class TransactionVerificationService(pb_grpc.VerificationServiceServicer):
    def __init__(self, svc_idx=0, total_svcs=3):
        self.svc_idx = svc_idx
        self.total_svcs = total_svcs
        # orders stores order_id -> {"data": pb.OrderData, "vc": [int]*total_svcs}
        self.orders = {}
        self.lock = threading.Lock()

    def merge_and_increment(self, local_vc, incoming_vc):
        # Merge
        for i in range(self.total_svcs):
            local_vc[i] = max(local_vc[i], incoming_vc[i])
        # Increment this service's own clock index
        local_vc[self.svc_idx] += 1

    def InitOrder(self, request, context):
        with self.lock:
            logging.info(f"InitOrder received for {request.order_id}")
            self.orders[request.order_id] = {
                "data": request.data,
                "vc": [0]*self.total_svcs
            }
            vc_snapshot = self.orders[request.order_id]["vc"]
        return pb.OrderInitResponse(success=True, vc=vc_snapshot, message="Init OK")

    def VerifyItems(self, request, context):
        with self.lock:
            entry = self.orders.get(request.order_id)
            if not entry:
                context.set_details("Order not found")
                context.set_code(grpc.StatusCode.NOT_FOUND)
                return pb.OrderEventResponse(fail=True, vc=[], message="No order")

            self.merge_and_increment(entry["vc"], request.vc)
            logging.info(f"VerifyItems for {request.order_id}, VC: {entry['vc']}")
            if len(entry["data"].items) == 0:
                return pb.OrderEventResponse(
                    fail=True,
                    message="No items in order",
                    vc=entry["vc"]
                )
            return pb.OrderEventResponse(
                fail=False,
                message="Items verified",
                vc=entry["vc"]
            )

    def VerifyUserData(self, request, context):
        with self.lock:
            entry = self.orders.get(request.order_id)
            if not entry:
                return pb.OrderEventResponse(fail=True, vc=[], message="Order not found")

            self.merge_and_increment(entry["vc"], request.vc)
            logging.info(f"VerifyUserData for {request.order_id}, VC: {entry['vc']}")
            user = entry["data"].user
            if not user.name or not user.contact:
                return pb.OrderEventResponse(
                    fail=True,
                    message="User data missing",
                    vc=entry["vc"]
                )
            return pb.OrderEventResponse(
                fail=False,
                message="User data verified",
                vc=entry["vc"]
            )

    def VerifyCreditCard(self, request, context):
        with self.lock:
            entry = self.orders.get(request.order_id)
            self.merge_and_increment(entry["vc"], request.vc)
            cc = entry["data"].credit_card
            logging.info(f"VerifyCreditCard for {request.order_id}, VC: {entry['vc']}")
            # Dummy check: length 16 => pass
            if not cc.number or len(cc.number) != 16:
                return pb.OrderEventResponse(fail=True, message="Invalid CC", vc=entry["vc"])
            return pb.OrderEventResponse(fail=False, message="Credit card OK", vc=entry["vc"])

    def ClearOrder(self, request, context):
        with self.lock:
            entry = self.orders.get(request.order_id)
            if not entry:
                return pb.OrderClearResponse(success=False, message="Not found")

            local_vc = entry["vc"]
            final_vc = request.final_vc

            # Check that local_vc[i] <= final_vc[i] for all i
            if all(local_vc[i] <= final_vc[i] for i in range(self.total_svcs)):
                del self.orders[request.order_id]
                logging.info(f"Cleared order {request.order_id}")
                return pb.OrderClearResponse(success=True, message="Cleared")
            else:
                return pb.OrderClearResponse(success=False, message="Vector clock mismatch")

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_VerificationServiceServicer_to_server(TransactionVerificationService(), server)
    port = os.getenv("VERIF_SERVICE_PORT", "50052")
    server.add_insecure_port(f"[::]:" + port)
    logging.info(f"Verification Service listening on {port}")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()