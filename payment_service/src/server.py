import os, sys, grpc, logging
from concurrent import futures

FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/DB'))
sys.path.insert(0, PROTO_DIR)

import payment_pb2 as pb
import payment_pb2_grpc as pb_grpc

logging.basicConfig(level=logging.INFO, format='[Payment] %(asctime)s %(levelname)s: %(message)s')

class PaymentServ(pb_grpc.PaymentServicer):
    def __init__(self):
        self.prepared=set()

    def Prepare(self, req, ctx):
        logging.info("Prepare for order %s amount %.2f", req.order_id, req.amount)
        self.prepared.add(req.order_id)
        return pb.PrepareResp(ready=True)

    def Commit(self, req, ctx):
        if req.order_id in self.prepared:
            logging.info("Commit order %s (charge card)", req.order_id)
            self.prepared.remove(req.order_id)
        return pb.CommitResp(success=True)

    def Abort(self, req, ctx):
        logging.info("Abort order %s (rollback)", req.order_id)
        self.prepared.discard(req.order_id)
        return pb.AbortResp(aborted=True)

def serve():
    port=os.getenv("PAY_PORT","7100")
    server=grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    pb_grpc.add_PaymentServicer_to_server(PaymentServ(), server)
    server.add_insecure_port(f"[::]:{port}")
    server.start(); server.wait_for_termination()

if __name__ == '__main__': serve()
