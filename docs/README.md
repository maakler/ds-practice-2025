# Documentation

1. **Frontend** sends a `POST /checkout` request with order details to the Orchestrator.  
2. **Orchestrator** spawns threads, calling each microservice over **gRPC**.  
3. **Microservices** perform checks (fraud, payment validity, suggestions) and return results.  
4. Orchestrator aggregates these results and responds to the Frontend with **Approved** or **Rejected** + suggestions.

### Distributed Systems View
- **Communication Model**: REST for external requests, gRPC internally. Network reliability is assumed via standard TCP.  
- **Concurrency**: The Orchestrator uses **multithreading** to call all backend services **in parallel**, reducing overall latency.  
- **Failure Model**: Crash-stop is assumed (if a service is down, the system logs an error or rejects the order).  
- **Timing Model**: Partial synchronous. Calls have timeouts so the Orchestrator won’t block indefinitely if a microservice is slow/unreachable.

## Quick Start (Docker Compose)

1. **Clone** this repo:
   ```bash
   git clone <your_repo_url>
   cd distributed-checkout
   ```
2. **Build & Run** everything:
   ```bash
   docker-compose up --build
   ```
3. Once up, **test** the Orchestrator’s endpoint:
   ```bash
   curl -X POST http://localhost:8081/checkout \
        -H "Content-Type: application/json" \
        -d '{"items":[{"name":"Book A","quantity":1,"price":10.0}],
             "user":{"name":"Alice","contact":"alice@example.com"},
             "creditCard":{"number":"4111111111111111","expirationDate":"12/25","cvv":"123"}}'
   ```
   You should receive a JSON response indicating **Approved** or **Rejected** along with optional suggestions.

## Key Endpoints

- **Orchestrator REST**: `POST /checkout` (Port `8081`)  
- **Fraud Service**: gRPC on Port `50051`  
- **Verification Service**: gRPC on Port `50052`  
- **Suggestions Service**: gRPC on Port `50053`

## Extensibility

- **Fraud**: Replace dummy threshold checks with advanced ML or external APIs.  
- **Verification**: Add deeper card checks, inventory checks, etc.  
- **Suggestions**: Integrate real recommendation engines.  
- **Resilience**: Add retries, distributed tracing, load balancing, or orchestration with Kubernetes.
