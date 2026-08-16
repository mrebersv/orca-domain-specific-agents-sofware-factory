# TASK BRIEF: Task 5.2 - Asyncio GPU Semaphore Arbiter & Request Queue

---

## 1. Context References
- Read `specs/ARCHITECTURE.md` (Section 5: Local Model Arbiter & Concurrency Proxy).
- Read `specs/phases/phase-05-local-infrastructure-proxy/tasks/task-5.1-fastapi-reverse-proxy.md`.

---

## 2. Objective
Implement `proxy/vram_arbiter.py` to manage `asyncio.Semaphore(1)` locks per GPU device/local backend, provide the executable CLI entrypoint (`vram-proxy`), build the pre-run health verification utility (`proxy/check_vram.py`), and write the comprehensive Phase 5 test suite (`tests/phase_05/`).

---

## 3. Scope & Detailed Requirements

### 3.1 VRAM Arbiter Concurrency Engine (`proxy/vram_arbiter.py`)
1. **Arbiter Class (`VRAMArbiter`):**
   ```python
   class VRAMArbiter:
       def __init__(self, max_concurrent_local: int = 1):
           self.semaphore = asyncio.Semaphore(max_concurrent_local)
           self.active_local_requests = 0
           self.active_remote_requests = 0
           self.queue_depth = 0

       def is_local_model(self, model_name: str) -> bool:
           """Returns True if model targets local backend (e.g., hermes, qwen, llama, local-slm)."""
           pass

       @asynccontextmanager
       async def acquire(self, model_name: str):
           """Acquires hardware semaphore if local model, otherwise bypasses lock."""
           pass
   ```
2. **FastAPI Middleware / Dependency Integration:**
   - Wrap completion routes in `proxy/server.py` with `arbiter.acquire(request.model)` context manager.
   - Track queue latency and update active request counters for `/health` reporting.
3. **CLI Runner & Entrypoint:**
   - Implement `def main()` in `proxy/vram_arbiter.py` using `uvicorn.run`.
   - Support CLI arguments:
     - `--host` (default: `127.0.0.1`)
     - `--port` (default: `8000`)
     - `--upstream` (default: `http://127.0.0.1:8080/v1`)
     - `--concurrency` (default: `1`)

### 3.2 Pre-Run Health Check Utility (`proxy/check_vram.py`)
1. **Standalone Health Checker:**
   - Script invoked by Orca lifecycle hooks before launching sub-agent nodes.
   - Sends HTTP `GET http://127.0.0.1:8000/health` with a 2-second timeout.
   - If proxy is reachable and upstream is healthy: Print `[OK] Local VRAM proxy online` and exit code `0`.
   - If proxy is offline or upstream fails: Print diagnostic error message with remediation steps (e.g. `Run 'vram-proxy &' or start local llama.cpp server`) and exit code `1`.

### 3.3 Phase 5 Test Suite (`tests/phase_05/`)
1. **`tests/phase_05/test_vram_proxy.py`:**
   - Mock upstream server simulating OpenAI chat completion responses and SSE streams.
   - Test non-streaming `/v1/chat/completions` request/response flow.
   - Test streaming `/v1/chat/completions` chunks.
   - Test `/health` endpoint response structure.
   - Test upstream failure response (HTTP 502/504).
2. **`tests/phase_05/test_semaphore_queue.py`:**
   - Dispatch 5 concurrent requests against local model endpoint.
   - Verify that upstream receives exactly 1 request at a time sequentially.
   - Dispatch concurrent requests against remote model endpoint and assert they execute concurrently without waiting on local queue.

---

## 4. Deliverables
- `proxy/vram_arbiter.py`
- `proxy/check_vram.py`
- `tests/phase_05/test_vram_proxy.py`
- `tests/phase_05/test_semaphore_queue.py`

---

## 5. Verification Command
```bash
pytest tests/phase_05/ -v
```
- **Exit Condition:** All Phase 5 proxy, streaming, and concurrency queue tests pass with exit code `0`.
