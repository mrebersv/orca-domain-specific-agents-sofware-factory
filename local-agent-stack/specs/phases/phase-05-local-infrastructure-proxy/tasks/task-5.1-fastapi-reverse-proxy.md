# TASK BRIEF: Task 5.1 - FastAPI OpenAI-Compatible Reverse Proxy

---

## 1. Context References
- Read `specs/PRD.md` (Section 4.5: Local Model Arbiter & Concurrency Proxy).
- Read `specs/ARCHITECTURE.md` (Section 5: Local Model Arbiter & Concurrency Proxy).

---

## 2. Objective
Implement `proxy/server.py` using FastAPI and `httpx.AsyncClient`. The server acts as an OpenAI-compatible reverse proxy listening on `http://127.0.0.1:8000`, handling `/v1/chat/completions`, `/v1/completions`, `/v1/models`, and `/health` with complete Server-Sent Events (SSE) streaming support and upstream error handling.

---

## 3. Scope & Detailed Requirements

### 3.1 Proxy Server Implementation (`proxy/server.py`)
1. **Application Configuration:**
   - Default host: `127.0.0.1`, Default port: `8000`.
   - Read default upstream targets from environment variables:
     - `LOCAL_INFERENCE_URL` (default: `http://127.0.0.1:8080/v1` for `llama.cpp` or `http://127.0.0.1:11434/v1` for Ollama).
     - `REMOTE_PASSTHROUGH_ENABLED` (default: `true`).
2. **Endpoint Implementations:**
   - **`POST /v1/chat/completions` & `POST /v1/completions`:**
     - Ingest standard OpenAI payload schema.
     - Inspect `model` parameter to determine target routing (local backend vs. remote provider).
     - If `stream=True`: Return `fastapi.responses.StreamingResponse` forwarding incoming bytes/chunks with `media_type="text/event-stream"`.
     - If `stream=False`: Await full upstream response and return JSON payload.
   - **`GET /v1/models`:**
     - Query upstream model catalog and return OpenAI-compliant model list JSON.
   - **`GET /health`:**
     - Return JSON status check:
       ```json
       {
         "status": "healthy",
         "proxy_version": "0.1.0",
         "upstream_reachable": true,
         "active_requests": 0
       }
       ```
3. **HTTP Client & Connection Pool:**
   - Use a singleton `httpx.AsyncClient` with custom timeout defaults:
     - `timeout = httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=10.0)`
   - Graceful connection cleanup on FastAPI app lifespan shutdown.
4. **Header & Error Handling:**
   - Forward `Authorization` bearer tokens when present.
   - Catch `httpx.ConnectError` and `httpx.TimeoutException`, returning HTTP 502/504 with structured error:
     ```json
     {
       "error": {
         "message": "Upstream local inference backend unreachable at [http://127.0.0.1:8080](http://127.0.0.1:8080)",
         "type": "upstream_connection_error",
         "code": 502
       }
     }
     ```

---

## 4. Deliverables
- `proxy/server.py`

---

## 5. Verification Command
```bash
python3 -c "from proxy.server import app; print('FastAPI proxy app initialized:', app.title)"
```
- **Exit Condition:** FastAPI application imports and initializes without syntax or dependency errors.
