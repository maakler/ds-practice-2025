import os
import logging
import threading
import heapq
import grpc
from concurrent import futures

import sys
FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/queue'))
sys.path.insert(0, PROTO_DIR)

import queue_pb2 as qp
import queue_pb2_grpc as qp_grpc

logging.basicConfig(
    level=logging.INFO,
    format='[OrderQueue] %(asctime)s %(levelname)s: %(message)s'
)

class OrderQueueService(qp_grpc.OrderQueueServicer):
    def __init__(self):
        self.lock = threading.Lock()
        # We’ll store queue items as ( -priority, order_id, order_data )
        # so that a higher priority => smaller negative => pop first
        self.queue = []

    def Enqueue(self, request, context):
        with self.lock:
            # interpret bigger priority as more urgent => use negative
            priority = -request.priority
            heapq.heappush(self.queue, (priority, request.order_id, request.order_data))
            logging.info(f"Enqueued order {request.order_id} with priority={request.priority}")
        return qp.EnqueueResponse(success=True, message="Order enqueued")

    def Dequeue(self, request, context):
        with self.lock:
            if not self.queue:
                return qp.DequeueResponse(found=False)
            priority, order_id, order_data = heapq.heappop(self.queue)
            logging.info(f"Dequeued order {order_id} with priority={-priority}")
            return qp.DequeueResponse(found=True, order_id=order_id, order_data=order_data)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    qp_grpc.add_OrderQueueServicer_to_server(OrderQueueService(), server)
    port = os.getenv("ORDER_QUEUE_PORT", "6000")
    server.add_insecure_port(f"[::]:" + port)
    logging.info(f"OrderQueueService listening on port {port}")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
