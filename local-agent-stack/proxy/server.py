"""
FastAPI OpenAI-Compatible Reverse Proxy for Local Model Inference.

This module implements a reverse proxy that forwards OpenAI-compatible requests
to local inference backends (llama.cpp, Ollama, vLLM) or remote providers.
Supports Server-Sent Events (SSE) streaming and upstream error handling.
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# ============================================================================
# Configuration & Constants
# ============================================================================

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
PROXY_VERSION = "0.1.0"

# Default upstream URLs for local inference backends
DEFAULT_LLAMA_CPP_URL = "http://127.0.0.1:8080/v1"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/v1"


def get_upstream_url() -> str:
    """Get the upstream inference backend URL from environment."""
    return os.environ.get("LOCAL_INFERENCE_URL", DEFAULT_LLAMA_CPP_URL)


def is_remote_passthrough_enabled() -> bool:
    """Check if remote provider passthrough is enabled."""
    return os.environ.get("REMOTE_PASSTHROUGH_ENABLED", "true").lower() == "true"


# ============================================================================
# HTTP Client Singleton
# ============================================================================

_upstream_client: Optional[httpx.AsyncClient] = None


def get_upstream_client() -> httpx.AsyncClient:
    """Get or create the singleton httpx.AsyncClient with configured timeouts."""
    global _upstream_client
    if _upstream_client is None:
        timeout = httpx.Timeout(
            connect=5.0,
            read=300.0,
            write=10.0,
            pool=10.0
        )
        _upstream_client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
        )
    return _upstream_client


async def close_upstream_client() -> None:
    """Close the upstream HTTP client."""
    global _upstream_client
    if _upstream_client is not None:
        await _upstream_client.aclose()
        _upstream_client = None


# ============================================================================
# VRAM Arbiter Integration
# ============================================================================

_vram_arbiter: Optional["VRAMArbiter"] = None


def get_vram_arbiter() -> "VRAMArbiter":
    """Get or create the VRAMArbiter singleton."""
    global _vram_arbiter
    if _vram_arbiter is None:
        # Import here to avoid circular imports
        from proxy.vram_arbiter import VRAMArbiter
        _vram_arbiter = VRAMArbiter()
    return _vram_arbiter


# ============================================================================
# Request/Response Models
# ============================================================================

class ChatMessage(BaseModel):
    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    stop: Optional[list[str]] = None
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0
    stream: Optional[bool] = False
    n: Optional[int] = 1
    user: Optional[str] = None


class CompletionRequest(BaseModel):
    model: str
    prompt: str
    temperature: Optional[float] = 1.0
    top_p: Optional[float] = 1.0
    max_tokens: Optional[int] = None
    stop: Optional[list[str]] = None
    presence_penalty: Optional[float] = 0.0
    frequency_penalty: Optional[float] = 0.0
    stream: Optional[bool] = False
    n: Optional[int] = 1
    user: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "healthy"
    proxy_version: str = PROXY_VERSION
    upstream_reachable: bool = True
    active_requests: int = 0


# ============================================================================
# Model Detection
# ============================================================================

LOCAL_MODEL_PREFIXES = (
    "hermes",
    "qwen",
    "llama",
    "local-",
    "phi",
    "mistral",
    "gemma",
    "deepseek-coder",
    "starcoder",
    "codellama",
    "wizardcoder",
    "codeqwen",
)


def is_local_model(model_name: str) -> bool:
    """Determine if a model name refers to a local model."""
    model_lower = model_name.lower()
    return any(model_lower.startswith(prefix) for prefix in LOCAL_MODEL_PREFIXES)


# ============================================================================
# Upstream Request Forwarding
# ============================================================================

async def forward_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    payload: Optional[dict] = None,
    headers: Optional[dict] = None,
    stream: bool = False,
) -> httpx.Response:
    """Forward a request to the upstream backend."""
    upstream_url = get_upstream_url()
    url = f"{upstream_url.rstrip('/')}{path}"

    request_headers = dict(headers) if headers else {}
    request_headers.setdefault("Content-Type", "application/json")

    try:
        if stream:
            # For streaming, we need to use stream=True in the request
            request = client.build_request(
                method, url, json=payload, headers=request_headers
            )
            response = await client.send(request, stream=True)
            return response
        else:
            response = await client.request(
                method, url, json=payload, headers=request_headers
            )
            return response
    except httpx.ConnectError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "message": f"Upstream local inference backend unreachable at {upstream_url}",
                    "type": "upstream_connection_error",
                    "code": 502,
                }
            },
        ) from e
    except httpx.TimeoutException as e:
        raise HTTPException(
            status_code=504,
            detail={
                "error": {
                    "message": f"Upstream request timed out after 300s at {upstream_url}",
                    "type": "upstream_connection_error",
                    "code": 504,
                }
            },
        ) from e


async def forward_streaming_response(
    upstream_response: httpx.Response,
) -> AsyncGenerator[bytes, None]:
    """Forward streaming response chunks from upstream to client."""
    async for chunk in upstream_response.aiter_raw():
        yield chunk


# ============================================================================
# FastAPI Application
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown."""
    # Startup: client is created lazily via get_upstream_client()
    yield
    # Shutdown: close the HTTP client
    await close_upstream_client()


app = FastAPI(
    title="Local Model Arbiter Proxy",
    description="OpenAI-compatible reverse proxy for local LLM inference with VRAM arbitration",
    version=PROXY_VERSION,
    lifespan=lifespan,
)


# ============================================================================
# Health Endpoint
# ============================================================================

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint with upstream connectivity status."""
    arbiter = get_vram_arbiter()
    client = get_upstream_client()
    upstream_reachable = False

    try:
        # Quick health check against upstream
        response = await client.get(f"{get_upstream_url()}/models", timeout=5.0)
        upstream_reachable = response.status_code == 200
    except Exception:
        upstream_reachable = False

    status = "healthy" if upstream_reachable else "unhealthy"

    return HealthResponse(
        status=status,
        proxy_version=PROXY_VERSION,
        upstream_reachable=upstream_reachable,
        active_requests=arbiter.active_local_requests + arbiter.active_remote_requests,
    )


# ============================================================================
# Models Endpoint
# ============================================================================

@app.get("/v1/models")
async def list_models() -> Response:
    """List available models from upstream."""
    client = get_upstream_client()

    try:
        response = await forward_request(client, "GET", "/v1/models")
        if response.status_code != 200:
            return JSONResponse(
                status_code=response.status_code,
                content={
                    "error": {
                        "message": f"Upstream returned {response.status_code}",
                        "type": "upstream_connection_error",
                        "code": response.status_code,
                    }
                },
            )
        return Response(
            content=response.content,
            media_type="application/json",
            headers=dict(response.headers),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "message": f"Upstream model catalog unreachable: {str(e)}",
                    "type": "upstream_connection_error",
                    "code": 502,
                }
            },
        ) from e


# ============================================================================
# Chat Completions Endpoint
# ============================================================================

@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    raw_request: Request,
    authorization: Optional[str] = Header(None),
) -> Response:
    """Handle chat completions with optional streaming."""
    client = get_upstream_client()
    arbiter = get_vram_arbiter()

    # Prepare headers to forward
    forward_headers = {}
    if authorization:
        forward_headers["Authorization"] = authorization

    # Check if this is a local model (requires semaphore)
    model_is_local = is_local_model(request.model)

    # Determine if we should use the arbiter
    use_arbiter = model_is_local and is_remote_passthrough_enabled()

    async def handle_request() -> Response:
        payload = request.model_dump(exclude_none=True, exclude={"stream"})
        stream = request.stream

        if stream:
            # Streaming response
            upstream_response = await forward_request(
                client,
                "POST",
                "/v1/chat/completions",
                payload=payload,
                headers=forward_headers,
                stream=True,
            )

            if upstream_response.status_code != 200:
                # Consume the error response
                error_content = await upstream_response.aread()
                return JSONResponse(
                    status_code=upstream_response.status_code,
                    content=json.loads(error_content) if error_content else {"error": "Upstream error"},
                )

            return StreamingResponse(
                forward_streaming_response(upstream_response),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        else:
            # Non-streaming response
            upstream_response = await forward_request(
                client,
                "POST",
                "/v1/chat/completions",
                payload=payload,
                headers=forward_headers,
                stream=False,
            )

            if upstream_response.status_code != 200:
                return JSONResponse(
                    status_code=upstream_response.status_code,
                    content=upstream_response.json(),
                )

            return Response(
                content=upstream_response.content,
                media_type="application/json",
                headers=dict(upstream_response.headers),
            )

    if use_arbiter:
        async with arbiter.acquire(request.model):
            return await handle_request()
    else:
        return await handle_request()


# ============================================================================
# Completions Endpoint (Legacy)
# ============================================================================

@app.post("/v1/completions")
async def completions(
    request: CompletionRequest,
    raw_request: Request,
    authorization: Optional[str] = Header(None),
) -> Response:
    """Handle legacy completions with optional streaming."""
    client = get_upstream_client()
    arbiter = get_vram_arbiter()

    # Prepare headers to forward
    forward_headers = {}
    if authorization:
        forward_headers["Authorization"] = authorization

    # Check if this is a local model (requires semaphore)
    model_is_local = is_local_model(request.model)

    # Determine if we should use the arbiter
    use_arbiter = model_is_local and is_remote_passthrough_enabled()

    async def handle_request() -> Response:
        payload = request.model_dump(exclude_none=True, exclude={"stream"})
        stream = request.stream

        if stream:
            # Streaming response
            upstream_response = await forward_request(
                client,
                "POST",
                "/v1/completions",
                payload=payload,
                headers=forward_headers,
                stream=True,
            )

            if upstream_response.status_code != 200:
                error_content = await upstream_response.aread()
                return JSONResponse(
                    status_code=upstream_response.status_code,
                    content=json.loads(error_content) if error_content else {"error": "Upstream error"},
                )

            return StreamingResponse(
                forward_streaming_response(upstream_response),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        else:
            # Non-streaming response
            upstream_response = await forward_request(
                client,
                "POST",
                "/v1/completions",
                payload=payload,
                headers=forward_headers,
                stream=False,
            )

            if upstream_response.status_code != 200:
                return JSONResponse(
                    status_code=upstream_response.status_code,
                    content=upstream_response.json(),
                )

            return Response(
                content=upstream_response.content,
                media_type="application/json",
                headers=dict(upstream_response.headers),
            )

    if use_arbiter:
        async with arbiter.acquire(request.model):
            return await handle_request()
    else:
        return await handle_request()


# ============================================================================
# Module Exports
# ============================================================================

__all__ = [
    "app",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "PROXY_VERSION",
    "get_upstream_url",
    "is_remote_passthrough_enabled",
    "get_upstream_client",
    "get_vram_arbiter",
    "is_local_model",
    "HealthResponse",
    "ChatCompletionRequest",
    "CompletionRequest",
]
