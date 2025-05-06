import os
import sys
import time
import logging
import threading
import grpc
import random
import gc

import sys
FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/queue'))
sys.path.insert(0, PROTO_DIR)


try:
    import queue_pb2 as qp
    import queue_pb2_grpc as qp_grpc
    import election_pb2 as ep
    import election_pb2_grpc as ep_grpc
except ImportError as e:
    logging.error(f"Failed to import protobuf modules: {e}")
    sys.exit(1)

import queue_pb2 as qp
import queue_pb2_grpc as qp_grpc

import election_pb2 as ep
import election_pb2_grpc as ep_grpc

from concurrent import futures

# Logging configuration
logging.basicConfig(
         level=logging.INFO,
         format='[Executor %(executor_id)s] %(asctime)s %(levelname)s: %(message)s',
         handlers=[logging.StreamHandler(sys.stdout)]
     )


class ElectionService(ep_grpc.ElectionServicer):
    def __init__(self, executor):
        self.executor = executor

    def ElectionMessage(self, request, context):
        message = list(request.ids)
        leader_id = request.leader_id
        if leader_id:  # Leadership announcement
            self.executor.handle_leader_announcement(leader_id)
        elif message:  # Election message
            self.executor.handle_election_message(message)
        # Empty ids = heartbeat, no action needed
        return ep.Empty()


class Executor:
    def __init__(self, executor_id, known_ids, queue_stub):
        self.executor_id = executor_id
        self.known_ids = sorted(known_ids)
        self.queue_stub = queue_stub
        self.is_leader = False
        self.leader_id = None
        self.running = True
        self.channels = {}  # gRPC channel pool
        self.election_lock = threading.Lock()  # Prevent concurrent elections
        self.channel_refresh_count = {}  # Track channel refresh frequency

        logging.info(f"Starting executor {executor_id}", extra={'executor_id': executor_id})

        self.address_map = {
            i: f"executor_{i}:500{i}" for i in self.known_ids
        }

        # Initialize gRPC channel pool
        for target_id in self.known_ids:
            if target_id != executor_id:
                self.channels[target_id] = grpc.insecure_channel(self.address_map[target_id])
                self.channel_refresh_count[target_id] = 0

        try:
            server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
            ep_grpc.add_ElectionServicer_to_server(ElectionService(self), server)
            server.add_insecure_port(f'[::]:500{executor_id}')
            server.start()
            logging.info(f"gRPC server started on port 500{executor_id}", extra={'executor_id': executor_id})
            self.server = server
        except Exception as e:
            logging.error(f"Failed to start gRPC server: {e}", extra={'executor_id': executor_id})
            raise

        try:
            threading.Thread(target=self.start_leader_election, daemon=True).start()
            threading.Thread(target=self.run_main_loop, daemon=True).start()
            logging.info(f"Started election and main loop threads", extra={'executor_id': executor_id})
        except Exception as e:
            logging.error(f"Failed to start threads: {e}", extra={'executor_id': executor_id})
            raise

    def send_election_message(self, ids=None, leader_id=None, target_id=None):
        for attempt in range(2):  # Retry up to 2 times
            try:
                stub = ep_grpc.ElectionStub(self.channels[target_id])
                request = ep.ElectionRequest(ids=ids or [], leader_id=leader_id or 0)
                stub.ElectionMessage(request, timeout=1.5)  # Reduced timeout
                return True
            except grpc.RpcError as e:
                logging.debug(f"Attempt {attempt + 1} failed for target {target_id}: {e}",
                              extra={'executor_id': self.executor_id})
                if attempt < 1:
                    time.sleep(0.2)  # Reduced retry delay
                continue
        return False

    def initiate_election(self):
        with self.election_lock:
            if self.leader_id is not None and self.leader_id > self.executor_id:
                return  # Higher-ID leader exists, abort
            logging.info("Initiating election", extra={'executor_id': self.executor_id})
            higher_ids = [i for i in self.known_ids if i > self.executor_id]
            if not higher_ids:
                # No higher IDs, become leader
                self.leader_id = self.executor_id
                self.is_leader = True
                logging.info(f"Election complete. Leader is {self.executor_id}",
                             extra={'executor_id': self.executor_id})
                # Announce leadership to all (three times for reliability)
                for _ in range(3):
                    for target_id in self.known_ids:
                        if target_id != self.executor_id:
                            self.send_election_message(leader_id=self.executor_id, target_id=target_id)
                    time.sleep(0.3)
                return

            # Send election message to higher IDs
            responded = False
            for target_id in higher_ids:
                if self.send_election_message(ids=[self.executor_id], target_id=target_id):
                    responded = True

            # Wait for higher-ID responses
            time.sleep(7)  # Extended wait for reliability
            if not responded and self.leader_id is None:
                # No higher IDs responded, become leader
                self.leader_id = self.executor_id
                self.is_leader = True
                logging.info(f"Election complete. Leader is {self.executor_id}",
                             extra={'executor_id': self.executor_id})
                # Announce leadership to all (three times for reliability)
                for _ in range(3):
                    for target_id in self.known_ids:
                        if target_id != self.executor_id:
                            self.send_election_message(leader_id=self.executor_id, target_id=target_id)
                    time.sleep(0.3)

    def handle_election_message(self, message):
        sender_id = message[0]
        with self.election_lock:
            if self.leader_id is not None and self.leader_id > sender_id:
                return  # Ignore lower-ID messages if higher-ID leader known
            if sender_id > self.executor_id:
                # Higher ID initiated election, wait for announcement
                return
            elif sender_id < self.executor_id:
                # Lower ID initiated, start own election
                self.initiate_election()

    def handle_leader_announcement(self, leader_id):
        with self.election_lock:
            if self.leader_id is None or leader_id > self.leader_id:
                self.leader_id = leader_id
                self.is_leader = (self.executor_id == leader_id)
                logging.info(f"Election complete. Leader is {leader_id}", extra={'executor_id': self.executor_id})

    def start_leader_election(self):
        logging.info(f"Starting leader election thread", extra={'executor_id': self.executor_id})
        try:
            # Delay: ID 3: 3-6s, ID 2: 6-9s, ID 1: 9-12s
            time.sleep(random.uniform(3 + (3 - self.executor_id) * 3, 6 + (3 - self.executor_id) * 3))
            if self.leader_id is None:
                self.initiate_election()
        except Exception as e:
            logging.error(f"Error in leader election: {e}", extra={'executor_id': self.executor_id})

    def check_leader(self):
        if not self.is_leader and self.leader_id is not None:
            try:
                stub = ep_grpc.ElectionStub(self.channels[self.leader_id])
                stub.ElectionMessage(ep.ElectionRequest(ids=[]), timeout=1.5)  # Reduced timeout
                self.channel_refresh_count[self.leader_id] = self.channel_refresh_count.get(self.leader_id, 0) + 1
                if self.channel_refresh_count[self.leader_id] % 10 == 0:
                    self.channels[self.leader_id].close()
                    self.channels[self.leader_id] = grpc.insecure_channel(self.address_map[self.leader_id])
                    self.channel_refresh_count[self.leader_id] = 0
            except grpc.RpcError as e:
                # Refresh channel on failure
                self.channels[self.leader_id].close()
                self.channels[self.leader_id] = grpc.insecure_channel(self.address_map[self.leader_id])
                self.channel_refresh_count[self.leader_id] = 0
                # Double-check leader
                try:
                    stub = ep_grpc.ElectionStub(self.channels[self.leader_id])
                    stub.ElectionMessage(ep.ElectionRequest(ids=[]), timeout=1.5)
                except grpc.RpcError:
                    # Stagger election initiation
                    time.sleep(random.uniform(0, 1))
                    logging.info(f"Leader {self.leader_id} failed, initiating election",
                                 extra={'executor_id': self.executor_id})
                    self.leader_id = None
                    self.initiate_election()

    def run_main_loop(self):
        while self.running:
            if self.leader_id is None:
                time.sleep(1)
                continue
            if self.is_leader:
                logging.info(f"I am the leader", extra={'executor_id': self.executor_id})
                try:
                    resp = self.queue_stub.Dequeue(qp.DequeueRequest(), timeout=1.5)  # Reduced timeout
                    if resp.found:
                        logging.info(f"Executing order {resp.order_id}", extra={'executor_id': self.executor_id})
                        time.sleep(2)
                    else:
                        time.sleep(3)
                except grpc.RpcError as e:
                    logging.error(f"Dequeue error: {e}", extra={'executor_id': self.executor_id})
                    time.sleep(5)
            else:
                self.check_leader()
                time.sleep(1)
            gc.collect()

    def shutdown(self):
        self.running = False
        for channel in self.channels.values():
            channel.close()
        self.server.stop(0)


def launch_executor(executor_id, known_ids):
    queue_host = os.getenv("ORDER_QUEUE_HOST", "order_queue:6000")
    logging.info(f"Connecting to order queue at {queue_host}", extra={'executor_id': executor_id})
    try:
        channel = grpc.insecure_channel(queue_host)
        queue_stub = qp_grpc.OrderQueueStub(channel)
        executor = Executor(executor_id, known_ids, queue_stub)
        while True:
            time.sleep(1)
    except Exception as e:
        logging.error(f"Failed to initialize executor: {e}", extra={'executor_id': executor_id})
        raise
    finally:
        executor.shutdown()


if __name__ == '__main__':
    try:
        executor_id = int(os.getenv("EXECUTOR_ID", "1"))
        known_ids_str = os.getenv("KNOWN_EXECUTOR_IDS", "1,2,3")
        known_ids = list(map(int, known_ids_str.split(',')))
        logging.info(f"Launching executor with ID {executor_id}", extra={'executor_id': executor_id})
        launch_executor(executor_id, known_ids)
    except Exception as e:
        logging.error(f"Main thread error: {e}", extra={'executor_id': executor_id})
        sys.exit(1)

import gc; gc.set_threshold(50)