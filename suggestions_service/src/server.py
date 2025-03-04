import os
import logging
import grpc
from concurrent import futures
import random

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
    def GetSuggestions(self, request, context):
        """
        Return some recommended books. Basic approach: random picks from a hardcoded list.
        Could be extended with real ML or collaborative filtering.
        """
        logging.info(f"Received suggestions request for order_id={request.order_id}, total={request.total_price}")

        all_books = [
            pb.SuggestedBook(book_id="101", title="Learn Python", author="Guido"),
            pb.SuggestedBook(book_id="102", title="Microservices Patterns", author="Richardson"),
            pb.SuggestedBook(book_id="103", title="Clean Code", author="Robert C. Martin"),
            pb.SuggestedBook(book_id="104", title="Effective DevOps", author="Jones"),
            pb.SuggestedBook(book_id="105", title="AI for Beginners", author="Smith"),
        ]
        # pick 2 random suggestions
        suggestions = random.sample(all_books, 2)

        logging.info(f"Returning {len(suggestions)} suggestions")
        return pb.SuggestionsResponse(suggestions=suggestions)

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb_grpc.add_SuggestionsServiceServicer_to_server(SuggestionsService(), server)
    port = os.getenv("SUGGESTIONS_SERVICE_PORT", "50053")
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    logging.info(f"Suggestions Service is listening on port {port}")
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
