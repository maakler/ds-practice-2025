import os
import sys
import time
import logging
import threading
import grpc

import sys
FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/queue'))
sys.path.insert(0, PROTO_DIR)

import queue_pb2 as qp
import queue_pb2_grpc as qp_grpc

logging.basicConfig(
    level=logging.INFO,
    format='[Executor %(executor_id)s] %(asctime)s %(levelname)s: %(message)s'
)

class ExecutorService:
    def __init__(self, executor_id, known_ids, queue_stub):
        self.executor_id = executor_id
        self.known_ids = known_ids  # e.g., [1,2,3]
        self.queue_stub = queue_stub
        self.is_leader = False

    def start_leader_election(self):
        # Simple approach: pick the minimum ID as the leader.
        # If you want something more robust (Bully, RAFT, etc.), implement here.
        leader_id = min(self.known_ids)
        self.is_leader = (self.executor_id == leader_id)
        logging.info(
            f"Leader is {leader_id}. I am {'the leader' if self.is_leader else 'not leader'}",
            extra={'executor_id': self.executor_id}
        )

    def run_main_loop(self):
        # If I'm the leader, poll the queue, else just wait.
        while True:
            if self.is_leader:
                # Dequeue next order (if any)
                try:
                    resp = self.queue_stub.Dequeue(qp.DequeueRequest(), timeout=5)
                    if resp.found:
                        logging.info(f"Executing order {resp.order_id}", extra={'executor_id': self.executor_id})
                        # Simulate execution
                        time.sleep(2)
                    else:
                        logging.info("No orders found, waiting...", extra={'executor_id': self.executor_id})
                        time.sleep(3)
                except grpc.RpcError as e:
                    logging.error(f"Dequeue error: {e}", extra={'executor_id': self.executor_id})
                    time.sleep(5)
            else:
                # Not leader. Possibly watch for changes in leadership or do nothing.
                time.sleep(5)

def launch_executor(executor_id, known_ids):
    queue_host = os.getenv("ORDER_QUEUE_HOST", "order_queue:6000")
    channel = grpc.insecure_channel(queue_host)
    queue_stub = qp_grpc.OrderQueueStub(channel)

    executor = ExecutorService(executor_id, known_ids, queue_stub)
    executor.start_leader_election()
    executor.run_main_loop()

if __name__ == '__main__':
    executor_id = int(os.getenv("EXECUTOR_ID", "1"))
    known_ids_str = os.getenv("KNOWN_EXECUTOR_IDS", "1,2")
    known_ids = list(map(int, known_ids_str.split(',')))

    launch_executor(executor_id, known_ids)
