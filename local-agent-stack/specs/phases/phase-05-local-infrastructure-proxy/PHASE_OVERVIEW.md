# PHASE 5 OVERVIEW: Local Infrastructure & VRAM Arbiter Proxy

---

## 1. Phase Objective
Implement a local OpenAI-compatible reverse proxy and hardware-aware inference arbitration engine (`proxy/`). This service runs locally at `http://127.0.0.1:8000/v1`, exposing standard `/v1/chat/completions`, `/v1/completions`, `/v1/models`, and `/health` endpoints. It intercepts incoming inference requests from parallel sub-agents, serializes requests destined for local GPU backends (`llama.cpp`, Ollama, vLLM) via `asyncio.Semaphore(1)` per device to eliminate Out-of-Memory (OOM) collisions, and passes remote API requests through without lock contention.

---

## 2. Task Breakdown & Execution Strategy

| Task ID | Task Title | Execution Mode | Dependencies | Primary Deliverables |
|---|---|---|---|---|
| **Task 5.1** | FastAPI OpenAI-Compatible Reverse Proxy | Sequential (First) | Phase 1 & 4 Complete | `proxy/server.py` |
| **Task 5.2** | Asyncio GPU Semaphore Arbiter & Request Queue | Sequential (Last) | Task 5.1 | `proxy/vram_arbiter.py`, `proxy/check_vram.py`, `tests/phase_05/` |

### Dependency & Concurrency Graph
```
        ┌─────────────────────────────────────────────────────────┐
        │  Phase 1 & Phase 4 Complete (Storage & Adapters Ready)  │
        └────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │  [Task 5.1: FastAPI Reverse Proxy Engine]               │
        │  (proxy/server.py: Routes, Streaming, Upstream Forward) │
        └────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
        ┌─────────────────────────────────────────────────────────┐
        │  [Task 5.2: Asyncio Semaphore Arbiter & Queue Manager]  │
        │  • proxy/vram_arbiter.py (Per-GPU locks & CLI entry)    │
        │  • proxy/check_vram.py (Pre-run health check script)    │
        │  • tests/phase_05/ (Concurrency & streaming tests)      │
        └────────────────────────────┬────────────────────────────┘
                                     │
                                     ▼
                      [Phase 5 Gatekeeper Execution]
                       pytest tests/phase_05/ -v
```

---

## 3. Inter-Task Data Flow
1. **Task 5.1** builds the core FastAPI application (`proxy/server.py`) using `httpx.AsyncClient`. It translates incoming client requests to upstream endpoints (`LLAMA_CPP_URL`, `OLLAMA_URL`, or remote endpoints), streams chunked SSE tokens back to the client in real time, and exposes `/health` with latency metrics.
2. **Task 5.2** implements the `VRAMArbiter` concurrency controller (`proxy/vram_arbiter.py`). It manages an array of `asyncio.Semaphore(1)` locks mapped to configured physical GPUs or local backend URLs. When multiple sub-agents execute parallel turns against local SLMs, requests are queued FIFO. If a request targets a remote model (e.g., Anthropic Claude, OpenAI GPT-4o), it bypasses the GPU semaphore. It also delivers the standalone pre-run hook check script (`proxy/check_vram.py`) and the full Phase 5 integration test suite.

---

## 4. Phase Exit Gate Criteria

Before unlocking Phase 6, the Test Runner / Gatekeeper executes:

```bash
pytest tests/phase_05/ -v
```

### Mandatory Pass Invariants:
1. Proxy correctly parses and forwards OpenAI-compatible JSON payloads (`model`, `messages`, `temperature`, `stream`) to target upstream endpoints.
2. Server-Sent Events (`stream=True`) stream token chunks with minimal latency and close connections cleanly.
3. Concurrent requests targeting local GPU models are strictly serialized via `asyncio.Semaphore(1)`, ensuring peak concurrency on the local backend is exactly 1.
4. Requests targeting remote model endpoints execute concurrently without waiting on local GPU semaphores.
5. Upstream disconnections or timeouts return formatted HTTP 502 / 504 JSON error bodies rather than hanging indefinitely.
6. `proxy/check_vram.py` exits with `0` when upstream is accessible and `1` with a diagnostic message when upstream is down.
