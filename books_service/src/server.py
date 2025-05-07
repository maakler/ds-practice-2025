import os, sys, grpc, logging, threading
from concurrent import futures
FILE = __file__
PROTO_DIR = os.path.abspath(os.path.join(FILE, '../../../utils/pb/DB'))
sys.path.insert(0, PROTO_DIR)

import books_pb2 as pb
import books_pb2_grpc as pb_grpc

logging.basicConfig(level=logging.INFO,
    format='[Books-%(role)s-%(port)s] %(asctime)s %(levelname)s: %(message)s')

class Common(pb_grpc.BooksDBServicer):
    def __init__(self):
        self.store  = {}                   # title -> stock
        self.staged = {}                   # order_id -> list[WriteReq]
        self.lock   = threading.Lock()

    # ---------- Read ----------
    def Read(self, req, ctx):
        with self.lock:
            stock = self.store.get(req.title, 0)
        return pb.ReadResp(stock = stock)

    # ---------- Write (only handled by primary) ----------
    def Write(self, req, ctx):
        ctx.set_code(grpc.StatusCode.UNIMPLEMENTED)
        ctx.set_details("Write only allowed on primary")
        return pb.WriteResp(success=False)

    # ---------- 2‑PC PARTICIPANT ----------
    def Prepare(self, req, ctx):
        with self.lock:
            self.staged[req.order_id] = req.staged        # buffer
        return pb.PrepareResp(ready = True)

    def Commit(self, req, ctx):
        with self.lock:
            for w in self.staged.pop(req.order_id, []):
                self.store[w.title] = w.new_stock
        return pb.CommitResp(success = True)

    def Abort(self, req, ctx):
        with self.lock:
            self.staged.pop(req.order_id, None)
        return pb.AbortResp(aborted = True)

# ------------ Primary wrapper ------------
class Primary(Common):
    def __init__(self, backup_hosts):
        super().__init__()
        self.backup_stubs = [pb_grpc.BooksDBStub(grpc.insecure_channel(h))
                             for h in backup_hosts]

    def Write(self, req, ctx):
        # 1) local write
        with self.lock:
            self.store[req.title] = req.new_stock
        # 2) replicate synchronously
        for stub in self.backup_stubs:
            try:
                stub.Write(req, timeout=2)
            except grpc.RpcError as e:
                logging.error(f"backup replication failed: {e}")
                ctx.set_code(grpc.StatusCode.UNAVAILABLE)
                return pb.WriteResp(success=False)
        return pb.WriteResp(success=True)

def serve():
    port   = os.environ.get("BOOKS_PORT", "7000")
    role   = os.environ.get("ROLE", "backup")        # primary | backup
    backups= os.environ.get("BACKUPS", "").split(",") if role=="primary" else []

    servicer = Primary(backups) if role=="primary" else Common()
    server   = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_BooksDBServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    logging.info("Books DB %s on %s", role, port, extra={"role":role,"port":port})
    server.start(); server.wait_for_termination()

if __name__ == '__main__':
    serve()
