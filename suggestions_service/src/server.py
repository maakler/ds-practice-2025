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
    format='[SuggestionsService] %(asctime)s %(levelname)s: %(message)s'
)

class SuggestionsService(pb_grpc.SuggestionsServiceServicer):
    def __init__(self, svc_idx=2, total_svcs=3):
        self.svc_idx = svc_idx
        self.total_svcs = total_svcs
        self.orders = {}
        self.lock = threading.Lock()

    def merge_and_increment(self, local_vc, incoming_vc):
        for i in range(self.total_svcs):
            local_vc[i] = max(local_vc[i], incoming_vc[i])
        local_vc[self.svc_idx] += 1

    def InitOrder(self, request, context):
        with self.lock:
            logging.info(f"InitOrder for {request.order_id}")
            self.orders[request.order_id] = {
                "data": request.data,
                "vc": [0]*self.total_svcs
            }
            vc_snapshot = self.orders[request.order_id]["vc"]
        return pb.OrderInitResponse(success=True, vc=vc_snapshot, message="Init OK")

    def GenerateSuggestions(self, request, context):
        with self.lock:
            entry = self.orders.get(request.order_id)
            if not entry:
                return pb.OrderEventResponse(fail=True, vc=[], message="Order not found")

            self.merge_and_increment(entry["vc"], request.vc)
            logging.info(f"GenerateSuggestions for {request.order_id}, VC: {entry['vc']}")
            # Dummy suggestions
            suggestions = [
                pb.SuggestedBook(book_id="201", title="Advanced Python", author="Expert"),
                pb.SuggestedBook(book_id="202", title="Distributed Systems", author="Lamport")
            ]
            return pb.OrderEventResponse(
                fail=False,
                message="Suggestions generated",
                vc=entry["vc"],
                suggestions=suggestions
            )

    def ClearOrder(self, request, context):
        with self.lock:
            entry = self.orders.get(request.order_id)
            if not entry:
                return pb.OrderClearResponse(success=False, message="Not found")

            local_vc = entry["vc"]
            final_vc = request.final_vc
            if all(local_vc[i] <= final_vc[i] for i in range(self.total_svcs)):
                del self.orders[request.order_id]
                logging.info(f"Cleared order {request.order_id}")
                return pb.OrderClearResponse(success=True, message="Cleared")
            else:
                return pb.OrderClearResponse(success=False, message="Vector clock mismatch")

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_SuggestionsServiceServicer_to_server(SuggestionsService(), server)
    port = os.getenv("SUGGESTIONS_SERVICE_PORT", "50053")
    server.add_insecure_port(f"[::]:" + port)
    logging.info(f"Suggestions Service listening on {port}")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()