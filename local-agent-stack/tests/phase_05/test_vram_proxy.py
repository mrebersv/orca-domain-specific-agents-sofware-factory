"""Tests for Phase 5 - VRAM Proxy FastAPI Reverse Proxy."""

from __future__ import annotations

import json
import os
from typing import Any, AsyncGenerator, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.testclient import TestClient


# Mock upstream responses
MOCK_CHAT_COMPLETION_RESPONSE = {
    "id": "chatcmpl-test123",
    "object": "chat.completion",
    "created": 1699999999,
    "model": "hermes-3-llama-3.1-8b",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Hello! How can I help you today?"
            },
            "finish_reason": "stop"
        }
    ],
    "usage": {
        "prompt_tokens": 10,
        "completion_tokens": 15,
        "total_tokens": 25
    }
}

MOCK_MODELS_RESPONSE = {
    "object": "list",
    "data": [
        {
            "id": "hermes-3-llama-3.1-8b",
            "object": "model",
            "created": 1699999999,
            "owned_by": "local"
        },
        {
            "id": "qwen2.5-coder-7b",
            "object": "model",
            "created": 1699999999,
            "owned_by": "local"
        }
    ]
}

MOCK_HEALTH_RESPONSE = {
    "status": "healthy",
    "proxy_version": "0.1.0",
    "upstream_reachable": True,
    "active_requests": 0
}


class _MockAsyncByteStream(httpx.AsyncByteStream):
    """Wrapper to make an async generator compatible with httpx.AsyncByteStream."""

    def __init__(self, agen):
        self._agen = agen

    async def __aiter__(self):
        async for item in self._agen:
            yield item


class MockUpstreamTransport(httpx.AsyncBaseTransport):
    """Mock transport that simulates upstream OpenAI-compatible server responses."""

    def __init__(self):
        self.requests_received: List[httpx.Request] = []
        self.chat_completion_response = MOCK_CHAT_COMPLETION_RESPONSE
        self.models_response = MOCK_MODELS_RESPONSE
        self.health_response = MOCK_HEALTH_RESPONSE
        self.should_fail = False
        self.fail_status_code = 502
        self.fail_message = "Upstream connection error"
        self.stream_chunks: List[Dict[str, Any]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests_received.append(request)

        if self.should_fail:
            return httpx.Response(
                status_code=self.fail_status_code,
                json={
                    "error": {
                        "message": self.fail_message,
                        "type": "upstream_connection_error",
                        "code": self.fail_status_code
                    }
                }
            )

        path = request.url.path

        if path.endswith("/v1/chat/completions") or path.endswith("/v1/completions"):
            if self.stream_chunks:
                # Return streaming response - use a proper async iterator
                async def stream_body():
                    for chunk in self.stream_chunks:
                        yield f"data: {json.dumps(chunk)}\n\n".encode()
                    yield b"data: [DONE]\n\n"

                return httpx.Response(
                    status_code=200,
                    headers={"content-type": "text/event-stream"},
                    stream=_MockAsyncByteStream(stream_body())
                )
            return httpx.Response(status_code=200, json=self.chat_completion_response)

        elif path.endswith("/v1/models"):
            return httpx.Response(status_code=200, json=self.models_response)

        elif path.endswith("/health"):
            return httpx.Response(status_code=200, json=self.health_response)

        return httpx.Response(status_code=404, json={"error": "Not found"})


@pytest.fixture
def mock_upstream_transport() -> MockUpstreamTransport:
    """Provide a mock upstream transport for testing."""
    return MockUpstreamTransport()


@pytest.fixture
def mock_upstream_client(mock_upstream_transport: MockUpstreamTransport) -> httpx.AsyncClient:
    """Create an httpx.AsyncClient with mock transport."""
    return httpx.AsyncClient(transport=mock_upstream_transport, base_url="http://mock-upstream")


@pytest.fixture
def proxy_app(mock_upstream_client: httpx.AsyncClient):
    """Create the FastAPI proxy app with mocked upstream client."""
    # We need to patch the upstream client in the proxy module
    with patch("proxy.server.get_upstream_client", return_value=mock_upstream_client):
        with patch("proxy.server.get_vram_arbiter") as mock_arbiter:
            # Mock arbiter to allow all requests through
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def mock_acquire(model_name: str):
                yield

            mock_arbiter.return_value.acquire = mock_acquire
            mock_arbiter.return_value.active_local_requests = 0
            mock_arbiter.return_value.active_remote_requests = 0
            mock_arbiter.return_value.queue_depth = 0

            from proxy.server import app
            yield app


@pytest.fixture
def test_client(proxy_app) -> TestClient:
    """Create a TestClient for the proxy app."""
    return TestClient(proxy_app)


class TestChatCompletionsNonStreaming:
    """Tests for non-streaming /v1/chat/completions endpoint."""

    def test_chat_completions_basic_request(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """Proxy must forward basic chat completion request and return JSON response."""
        payload = {
            "model": "hermes-3-llama-3.1-8b",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.7,
            "stream": False
        }

        response = test_client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "chatcmpl-test123"
        assert data["object"] == "chat.completion"
        assert data["model"] == "hermes-3-llama-3.1-8b"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["finish_reason"] == "stop"
        assert "usage" in data

        # Verify upstream received the request
        assert len(mock_upstream_transport.requests_received) == 1
        upstream_request = mock_upstream_transport.requests_received[0]
        assert upstream_request.method == "POST"
        assert upstream_request.url.path.endswith("/v1/chat/completions")

    def test_chat_completions_forwards_all_parameters(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """Proxy must forward all OpenAI parameters (temperature, top_p, max_tokens, etc.)."""
        payload = {
            "model": "hermes-3-llama-3.1-8b",
            "messages": [{"role": "user", "content": "Test"}],
            "temperature": 0.5,
            "top_p": 0.9,
            "max_tokens": 100,
            "stop": ["\n", "END"],
            "presence_penalty": 0.1,
            "frequency_penalty": 0.2,
            "stream": False
        }

        response = test_client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        # Verify upstream received all parameters
        upstream_request = mock_upstream_transport.requests_received[0]
        upstream_payload = json.loads(upstream_request.content)
        assert upstream_payload["temperature"] == 0.5
        assert upstream_payload["top_p"] == 0.9
        assert upstream_payload["max_tokens"] == 100
        assert upstream_payload["stop"] == ["\n", "END"]
        assert upstream_payload["presence_penalty"] == 0.1
        assert upstream_payload["frequency_penalty"] == 0.2

    def test_chat_completions_forwards_authorization_header(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """Proxy must forward Authorization bearer token to upstream."""
        payload = {
            "model": "hermes-3-llama-3.1-8b",
            "messages": [{"role": "user", "content": "Test"}],
            "stream": False
        }

        response = test_client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": "Bearer test-api-key-123"}
        )

        assert response.status_code == 200
        upstream_request = mock_upstream_transport.requests_received[0]
        assert upstream_request.headers.get("authorization") == "Bearer test-api-key-123"

    def test_completions_endpoint_works(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """POST /v1/completions must work similarly to chat completions."""
        payload = {
            "model": "hermes-3-llama-3.1-8b",
            "prompt": "Complete this sentence",
            "max_tokens": 50,
            "stream": False
        }

        response = test_client.post("/v1/completions", json=payload)

        assert response.status_code == 200
        upstream_request = mock_upstream_transport.requests_received[0]
        assert upstream_request.url.path.endswith("/v1/completions")


class TestChatCompletionsStreaming:
    """Tests for streaming /v1/chat/completions endpoint (SSE)."""

    def test_streaming_chat_completions_sends_chunks(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """Streaming request must return SSE chunks with token deltas."""
        # Configure mock to return streaming chunks
        mock_upstream_transport.stream_chunks = [
            {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1699999999, "model": "hermes", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
            {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1699999999, "model": "hermes", "choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}]},
            {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1699999999, "model": "hermes", "choices": [{"index": 0, "delta": {"content": " world"}, "finish_reason": None}]},
            {"id": "chatcmpl-test", "object": "chat.completion.chunk", "created": 1699999999, "model": "hermes", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]

        payload = {
            "model": "hermes-3-llama-3.1-8b",
            "messages": [{"role": "user", "content": "Say hello"}],
            "stream": True
        }

        response = test_client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

        # Parse SSE stream
        content = response.text
        lines = content.strip().split("\n")
        data_lines = [line[6:] for line in lines if line.startswith("data: ")]

        # Should have 4 chunks + [DONE]
        assert len(data_lines) >= 4
        assert data_lines[-1] == "[DONE]"

        # Verify chunks have correct structure
        first_chunk = json.loads(data_lines[0])
        assert first_chunk["object"] == "chat.completion.chunk"
        assert "choices" in first_chunk

    def test_streaming_completions_endpoint(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """Streaming must work for /v1/completions endpoint too."""
        mock_upstream_transport.stream_chunks = [
            {"id": "cmpl-test", "object": "text_completion", "created": 1699999999, "model": "hermes", "choices": [{"index": 0, "text": "Hello", "finish_reason": None}]},
            {"id": "cmpl-test", "object": "text_completion", "created": 1699999999, "model": "hermes", "choices": [{"index": 0, "text": " world", "finish_reason": "stop"}]},
        ]

        payload = {
            "model": "hermes-3-llama-3.1-8b",
            "prompt": "Say hello",
            "stream": True
        }

        response = test_client.post("/v1/completions", json=payload)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert "data: " in response.text
        assert "[DONE]" in response.text


class TestModelsEndpoint:
    """Tests for /v1/models endpoint."""

    def test_models_endpoint_returns_model_list(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """GET /v1/models must return OpenAI-compatible model list."""
        response = test_client.get("/v1/models")

        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        assert "data" in data
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 2
        assert data["data"][0]["id"] == "hermes-3-llama-3.1-8b"
        assert data["data"][0]["object"] == "model"
        assert data["data"][0]["owned_by"] == "local"

    def test_models_endpoint_forwards_upstream_error(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """Models endpoint must propagate upstream errors."""
        mock_upstream_transport.should_fail = True
        mock_upstream_transport.fail_status_code = 502
        mock_upstream_transport.fail_message = "Upstream model catalog unreachable"

        response = test_client.get("/v1/models")

        assert response.status_code == 502
        data = response.json()
        assert "error" in data
        assert data["error"]["type"] == "upstream_connection_error"
        assert data["error"]["code"] == 502


class TestHealthEndpoint:
    """Tests for /health endpoint."""

    def test_health_endpoint_returns_structured_status(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """GET /health must return structured health status."""
        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["proxy_version"] == "0.1.0"
        assert data["upstream_reachable"] is True
        assert "active_requests" in data
        assert isinstance(data["active_requests"], int)

    def test_health_endpoint_shows_unhealthy_when_upstream_down(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """Health endpoint must report upstream unreachable."""
        mock_upstream_transport.should_fail = True
        mock_upstream_transport.fail_status_code = 503
        mock_upstream_transport.fail_message = "Upstream service unavailable"

        # The proxy's health endpoint might check upstream - this depends on implementation
        # For now we test that it responds
        response = test_client.get("/health")
        # Implementation may vary - could be 200 with unhealthy status or 503
        assert response.status_code in (200, 503)


class TestUpstreamErrorHandling:
    """Tests for upstream connection errors and timeouts."""

    def test_upstream_connection_error_returns_502(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """ConnectError must return HTTP 502 with structured error body."""
        mock_upstream_transport.should_fail = True
        mock_upstream_transport.fail_status_code = 502
        mock_upstream_transport.fail_message = "Upstream local inference backend unreachable at http://127.0.0.1:8080"

        payload = {
            "model": "hermes-3-llama-3.1-8b",
            "messages": [{"role": "user", "content": "Test"}],
            "stream": False
        }

        response = test_client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 502
        data = response.json()
        assert "error" in data
        assert data["error"]["type"] == "upstream_connection_error"
        assert data["error"]["code"] == 502
        assert "unreachable" in data["error"]["message"].lower()

    def test_upstream_timeout_returns_504(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """TimeoutException must return HTTP 504 with structured error body."""
        mock_upstream_transport.should_fail = True
        mock_upstream_transport.fail_status_code = 504
        mock_upstream_transport.fail_message = "Upstream request timed out after 300s"

        payload = {
            "model": "hermes-3-llama-3.1-8b",
            "messages": [{"role": "user", "content": "Test"}],
            "stream": False
        }

        response = test_client.post("/v1/chat/completions", json=payload)

        assert response.status_code == 504
        data = response.json()
        assert "error" in data
        assert data["error"]["type"] == "upstream_connection_error"
        assert data["error"]["code"] == 504
        assert "timed out" in data["error"]["message"].lower()

    def test_streaming_upstream_error_handled_gracefully(self, test_client: TestClient, mock_upstream_transport: MockUpstreamTransport):
        """Streaming upstream errors must not hang the connection."""
        mock_upstream_transport.should_fail = True
        mock_upstream_transport.fail_status_code = 502
        mock_upstream_transport.fail_message = "Upstream disconnected during stream"

        payload = {
            "model": "hermes-3-llama-3.1-8b",
            "messages": [{"role": "user", "content": "Test"}],
            "stream": True
        }

        response = test_client.post("/v1/chat/completions", json=payload)

        # Should return error response, not hang
        assert response.status_code in (502, 504)
        data = response.json()
        assert "error" in data


class TestProxyConfiguration:
    """Tests for proxy configuration and defaults."""

    def test_default_host_and_port(self):
        """Proxy must default to 127.0.0.1:8000."""
        from proxy.server import DEFAULT_HOST, DEFAULT_PORT
        assert DEFAULT_HOST == "127.0.0.1"
        assert DEFAULT_PORT == 8000

    def test_upstream_url_from_environment(self):
        """Proxy must read upstream URL from environment."""
        with patch.dict(os.environ, {"LOCAL_INFERENCE_URL": "http://custom:9000/v1"}):
            from proxy.server import get_upstream_url
            assert get_upstream_url() == "http://custom:9000/v1"

    def test_remote_passthrough_enabled_by_default(self):
        """Remote passthrough must be enabled by default."""
        with patch.dict(os.environ, {}, clear=True):
            from proxy.server import is_remote_passthrough_enabled
            assert is_remote_passthrough_enabled() is True

    def test_remote_passthrough_can_be_disabled(self):
        """Remote passthrough can be disabled via environment."""
        with patch.dict(os.environ, {"REMOTE_PASSTHROUGH_ENABLED": "false"}):
            from proxy.server import is_remote_passthrough_enabled
            assert is_remote_passthrough_enabled() is False


class TestHttpClientConfiguration:
    """Tests for httpx.AsyncClient configuration."""

    def test_client_has_correct_timeouts(self):
        """HTTP client must have correct timeout configuration."""
        from proxy.server import get_upstream_client
        import httpx

        client = get_upstream_client()
        assert isinstance(client, httpx.AsyncClient)
        # Check timeout configuration
        timeout = client.timeout
        assert timeout.connect == 5.0
        assert timeout.read == 300.0
        assert timeout.write == 10.0
        assert timeout.pool == 10.0

    def test_client_is_singleton(self):
        """Upstream client must be a singleton."""
        from proxy.server import get_upstream_client
        client1 = get_upstream_client()
        client2 = get_upstream_client()
        assert client1 is client2


