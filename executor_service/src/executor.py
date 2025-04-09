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

# Logging configuration (unchanged)
logging.basicConfig(
    level=logging.INFO,
    format='[Executor %(executor_id)s] %(asctime)s %(levelname)s: %(message)s'
)

class ExecutorService:
    def __init__(self, executor_id, known_ids, queue_stub):
        self.executor_id = executor_id
        self.known_ids = sorted(known_ids)
        self.queue_stub = queue_stub
        self.is_leader = False
        self.leader_id = None
        self.running = True
        self.next_executor = self.get_next_in_ring()
        self.start_leader_election()  # Run synchronously
        threading.Thread(target=self.run_main_loop, daemon=True).start()

    def get_next_in_ring(self):
        idx = self.known_ids.index(self.executor_id)
        next_idx = (idx + 1) % len(self.known_ids)
        return self.known_ids[next_idx]

    def receive_message(self, message):
        try:
            logging.info(f"Received message {message}", extra={'executor_id': self.executor_id})
            if message[0] == self.executor_id:
                self.leader_id = max(message[1:])
                self.is_leader = (self.executor_id == self.leader_id)
                logging.info(f"Leader elected: {self.leader_id}", extra={'executor_id': self.executor_id})

            elif self.executor_id > max(message[1:]):
                message.append(self.executor_id)

        except Exception as e:
            logging.error(f"Error in receive_message: {e}", extra={'executor_id': self.executor_id})
            raise

    def initiate_election(self):
        try:
            message = [self.executor_id, self.executor_id]
            logging.info(f"Starting election with message {message}", extra={'executor_id': self.executor_id})
            #self.send_message(self.next_executor, message)
            current_idx = self.known_ids.index(self.next_executor)
            while self.known_ids[current_idx] != self.executor_id:
                current_id = self.known_ids[current_idx]
                logging.info(f"Simulating traversal to {current_id}, current message {message}", extra={'executor_id': self.executor_id})
                if current_id > max(message[1:]):
                    message.append(current_id)
                current_idx = (current_idx + 1) % len(self.known_ids)
            #logging.info(f"Traversal complete, final message {message}", extra={'executor_id': self.executor_id})
            time.sleep(1)
            self.receive_message(message)
        except Exception as e:
            logging.error(f"Error in initiate_election: {e}", extra={'executor_id': self.executor_id})
            raise

    def start_leader_election(self):
        while self.running:
            if not self.is_leader and self.leader_id is None:
                logging.info("No leader, starting ring election", extra={'executor_id': self.executor_id})
                self.initiate_election()
                break
            time.sleep(5)

    def run_main_loop(self):
        while self.running:
            if self.leader_id is None:
                logging.info("Waiting for leader election to complete", extra={'executor_id': self.executor_id})
                time.sleep(1)
                continue
            if self.is_leader:
                logging.info("I am the leader", extra={'executor_id': self.executor_id})
                try:
                    resp = self.queue_stub.Dequeue(qp.DequeueRequest(), timeout=5)
                    if resp.found:
                        logging.info(f"Executing order {resp.order_id}", extra={'executor_id': self.executor_id})
                        time.sleep(2)
                    else:
                        time.sleep(3)
                except grpc.RpcError as e:
                    logging.error(f"Dequeue error: {e}", extra={'executor_id': self.executor_id})
                    time.sleep(5)
            else:
                logging.info(f"Leader is {self.leader_id}, I am not the leader", extra={'executor_id': self.executor_id})
                time.sleep(5)

def launch_executor(executor_id, known_ids):
    queue_host = os.getenv("ORDER_QUEUE_HOST", "order_queue:6000")
    channel = grpc.insecure_channel(queue_host)
    queue_stub = qp_grpc.OrderQueueStub(channel)
    executor = ExecutorService(executor_id, known_ids, queue_stub)

if __name__ == '__main__':
    executor_id = int(os.getenv("EXECUTOR_ID", "1"))
    known_ids_str = os.getenv("KNOWN_EXECUTOR_IDS", "1,2")
    known_ids = list(map(int, known_ids_str.split(',')))
    launch_executor(executor_id, known_ids)
