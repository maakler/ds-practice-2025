import os, sys, grpc, logging, threading
from concurrent import futures

FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/DB'))
sys.path.insert(0, PROTO_DIR)

import books_pb2 as pb
import books_pb2_grpc as pb_grpc

logging.basicConfig(
    level=logging.INFO,
    format='[Books-%(role)s] %(asctime)s %(levelname)s: %(message)s'
)

# ────────────────────────────────────────────────────────────
# Common (backup) replica
# ────────────────────────────────────────────────────────────
class Common(pb_grpc.BooksDBServicer):
    def __init__(self, role):
        self.role   = role                # "primary" | "backup‑N"
        self.store  = {}                  # title → stock
        self.staged = {}                  # order_id → staged list
        self.lock   = threading.Lock()

    # -------- READ ----------
    def Read(self, req, ctx):
        with self.lock:
            stock = self.store.get(req.title, 0)
        logging.info('READ   title=%r  stock=%s', req.title, stock, extra={'role':self.role})
        return pb.ReadResp(stock=stock)

    # -------- WRITE (only primary implements) ----------
    def Write(self, req, ctx):
        ctx.set_code(grpc.StatusCode.UNIMPLEMENTED)
        ctx.set_details("Write only allowed on primary")
        return pb.WriteResp(success=False)

    # -------- 2‑PC participant ----------
    def Prepare(self, req, ctx):
        with self.lock:
            self.staged[req.order_id] = req.staged
        logging.info('PREPARE buffered order=%s  %s mutations',
                     req.order_id, len(req.staged), extra={'role':self.role})
        return pb.PrepareResp(ready=True)

    def Commit(self, req, ctx):
        with self.lock:
            for w in self.staged.pop(req.order_id, []):
                self.store[w.title] = w.new_stock
                logging.info('COMMIT  order=%s  title=%r  stock=%s',
                             req.order_id, w.title, w.new_stock, extra={'role':self.role})
        return pb.CommitResp(success=True)

    def Abort(self, req, ctx):
        self.staged.pop(req.order_id, None)
        logging.info('ABORT  order=%s', req.order_id, extra={'role':self.role})
        return pb.AbortResp(aborted=True)

# ────────────────────────────────────────────────────────────
# Primary – extends Common with real Write + replication
# ────────────────────────────────────────────────────────────
class Primary(Common):
    def __init__(self, backup_hosts):
        super().__init__('primary')
        self.backup_stubs = [
            pb_grpc.BooksDBStub(grpc.insecure_channel(h)) for h in backup_hosts if h
        ]

    def Write(self, req, ctx):
        with self.lock:
            delta = req.new_stock - self.store.get(req.title, 0)
            self.store[req.title] = req.new_stock
        logging.info('WRITE  title=%r  Δ=%+d  new=%s', req.title, delta, req.new_stock,
                     extra={'role':'primary'})

        # sync replication
        for stub in self.backup_stubs:
            try:
                stub.Write(req, timeout=2)
            except grpc.RpcError as e:
                # a backup uses Common, so UNIMPLEMENTED is normal
                if e.code() != grpc.StatusCode.UNIMPLEMENTED:
                    logging.error('replication to %s failed: %s', stub._channel.target(), e)
        return pb.WriteResp(success=True)

# ────────────────────────────────────────────────────────────
def serve():
    port = os.getenv('BOOKS_PORT', '7000')
    role = os.getenv('ROLE', 'backup')          # "primary" or "backup"
    backups = os.getenv('BACKUPS', '').split(',') if role == 'primary' else []

    servicer = Primary(backups) if role == 'primary' else Common(role)
    server   = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_BooksDBServicer_to_server(servicer, server)
    server.add_insecure_port(f'[::]:{port}')
    logging.info('Books‑DB %s listening on %s', role, port, extra={'role':role})
    server.start(); server.wait_for_termination()

if __name__ == '__main__':
    serve()
