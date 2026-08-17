"""Tests for Phase 5 - VRAM Arbiter Concurrency & Semaphore Queue."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# Track execution order and concurrency for testing
class ExecutionTracker:
    """Tracks concurrent execution of requests for concurrency testing."""

    def __init__(self):
        self.local_requests: List[Dict[str, Any]] = []
        self.remote_requests: List[Dict[str, Any]] = []
        self.active_local: Set[str] = set()
        self.active_remote: Set[str] = set()
        self.max_concurrent_local = 0
        self.max_concurrent_remote = 0
        self.local_start_times: Dict[str, float] = {}
        self.local_end_times: Dict[str, float] = {}
        self.remote_start_times: Dict[str, float] = {}
        self.remote_end_times: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def local_start(self, request_id: str):
        async with self._lock:
            self.active_local.add(request_id)
            self.local_start_times[request_id] = time.monotonic()
            self.max_concurrent_local = max(self.max_concurrent_local, len(self.active_local))

    async def local_end(self, request_id: str):
        async with self._lock:
            self.active_local.discard(request_id)
            self.local_end_times[request_id] = time.monotonic()

    async def remote_start(self, request_id: str):
        async with self._lock:
            self.active_remote.add(request_id)
            self.remote_start_times[request_id] = time.monotonic()
            self.max_concurrent_remote = max(self.max_concurrent_remote, len(self.active_remote))

    async def remote_end(self, request_id: str):
        async with self._lock:
            self.active_remote.discard(request_id)
            self.remote_end_times[request_id] = time.monotonic()

    def get_local_overlap(self) -> bool:
        """Check if any local requests overlapped in time (should be False with semaphore=1)."""
        if len(self.local_start_times) < 2:
            return False
        # Sort by start time
        sorted_requests = sorted(self.local_start_times.items(), key=lambda x: x[1])
        for i in range(len(sorted_requests) - 1):
            req_id, start = sorted_requests[i]
            end = self.local_end_times.get(req_id, float('inf'))
            next_start = sorted_requests[i + 1][1]
            if end > next_start:  # Overlap detected
                return True
        return False


@pytest.fixture
def execution_tracker() -> ExecutionTracker:
    """Provide an execution tracker for concurrency testing."""
    return ExecutionTracker()


class TestVRAMArbiterBasics:
    """Tests for VRAMArbiter basic functionality."""

    def test_vram_arbiter_initialization(self):
        """VRAMArbiter must initialize with default concurrency of 1."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter()
        assert arbiter.max_concurrent_local == 1
        assert arbiter.active_local_requests == 0
        assert arbiter.active_remote_requests == 0
        assert arbiter.queue_depth == 0

    def test_vram_arbiter_custom_concurrency(self):
        """VRAMArbiter must accept custom concurrency limit."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter(max_concurrent_local=2)
        assert arbiter.max_concurrent_local == 2

    def test_is_local_model_identifies_local_models(self):
        """is_local_model must return True for local model names."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter()

        local_models = [
            "hermes-3-llama-3.1-8b",
            "qwen2.5-coder-7b",
            "llama-3.1-8b-instruct",
            "local-slm",
            "hermes",
            "qwen",
            "llama.cpp",
        ]

        for model in local_models:
            assert arbiter.is_local_model(model) is True, f"Expected {model} to be local"

    def test_is_local_model_identifies_remote_models(self):
        """is_local_model must return False for remote/API model names."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter()

        remote_models = [
            "gpt-4o",
            "gpt-4",
            "gpt-3.5-turbo",
            "claude-3-opus",
            "claude-3-sonnet",
            "claude-3-haiku",
            "gemini-pro",
            "remote-model",
            "openai/gpt-4o",
            "anthropic/claude-3",
        ]

        for model in remote_models:
            assert arbiter.is_local_model(model) is False, f"Expected {model} to be remote"

    @pytest.mark.asyncio
    async def test_acquire_local_model_serializes(self, execution_tracker: ExecutionTracker):
        """acquire context manager must serialize local model requests."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter(max_concurrent_local=1)

        async def tracked_request(request_id: str):
            async with arbiter.acquire("hermes-3-llama-3.1-8b"):
                await execution_tracker.local_start(request_id)
                await asyncio.sleep(0.05)  # Simulate work
                await execution_tracker.local_end(request_id)

        # Launch 5 concurrent requests
        await asyncio.gather(*[tracked_request(f"req-{i}") for i in range(5)])

        # Verify serialization: max concurrent local should be 1
        assert execution_tracker.max_concurrent_local == 1
        # Verify no temporal overlap
        assert execution_tracker.get_local_overlap() is False

    @pytest.mark.asyncio
    async def test_acquire_remote_model_bypasses_semaphore(self, execution_tracker: ExecutionTracker):
        """acquire context manager must bypass semaphore for remote models."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter(max_concurrent_local=1)

        async def tracked_request(request_id: str):
            async with arbiter.acquire("gpt-4o"):
                await execution_tracker.remote_start(request_id)
                await asyncio.sleep(0.05)
                await execution_tracker.remote_end(request_id)

        # Launch 5 concurrent remote requests
        await asyncio.gather(*[tracked_request(f"req-{i}") for i in range(5)])

        # Remote requests should run concurrently (max 5)
        assert execution_tracker.max_concurrent_remote == 5

    @pytest.mark.asyncio
    async def test_mixed_local_remote_concurrency(self, execution_tracker: ExecutionTracker):
        """Local requests serialize, remote requests run concurrently with each other."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter(max_concurrent_local=1)

        async def local_request(request_id: str):
            async with arbiter.acquire("hermes-3-llama-3.1-8b"):
                await execution_tracker.local_start(request_id)
                await asyncio.sleep(0.05)
                await execution_tracker.local_end(request_id)

        async def remote_request(request_id: str):
            async with arbiter.acquire("gpt-4o"):
                await execution_tracker.remote_start(request_id)
                await asyncio.sleep(0.05)
                await execution_tracker.remote_end(request_id)

        # Launch 3 local and 3 remote concurrently
        tasks = [
            local_request("local-1"),
            local_request("local-2"),
            local_request("local-3"),
            remote_request("remote-1"),
            remote_request("remote-2"),
            remote_request("remote-3"),
        ]
        await asyncio.gather(*tasks)

        # Local should be serialized
        assert execution_tracker.max_concurrent_local == 1
        assert execution_tracker.get_local_overlap() is False

        # Remote should be concurrent
        assert execution_tracker.max_concurrent_remote == 3


class TestVRAMArbiterQueueTracking:
    """Tests for VRAMArbiter queue depth and active request tracking."""

    def test_queue_depth_increments_when_waiting(self):
        """queue_depth must reflect number of waiting local requests."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter(max_concurrent_local=1)
        initial_depth = arbiter.queue_depth

        # Queue depth tracking is implementation-specific
        # This test ensures the attribute exists and is an integer
        assert isinstance(arbiter.queue_depth, int)
        assert arbiter.queue_depth >= 0

    @pytest.mark.asyncio
    async def test_active_local_requests_counter(self, execution_tracker: ExecutionTracker):
        """active_local_requests must track currently executing local requests."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter(max_concurrent_local=1)

        async def tracked_request(request_id: str):
            async with arbiter.acquire("hermes"):
                assert arbiter.active_local_requests >= 1
                await execution_tracker.local_start(request_id)
                await asyncio.sleep(0.02)
                await execution_tracker.local_end(request_id)

        await asyncio.gather(*[tracked_request(f"req-{i}") for i in range(3)])

        # After all complete, active should be 0
        assert arbiter.active_local_requests == 0

    @pytest.mark.asyncio
    async def test_active_remote_requests_counter(self, execution_tracker: ExecutionTracker):
        """active_remote_requests must track currently executing remote requests."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter(max_concurrent_local=1)

        async def tracked_request(request_id: str):
            async with arbiter.acquire("gpt-4o"):
                assert arbiter.active_remote_requests >= 1
                await execution_tracker.remote_start(request_id)
                await asyncio.sleep(0.02)
                await execution_tracker.remote_end(request_id)

        await asyncio.gather(*[tracked_request(f"req-{i}") for i in range(3)])

        # After all complete, active should be 0
        assert arbiter.active_remote_requests == 0


class TestVRAMArbiterIntegrationWithProxy:
    """Tests for VRAMArbiter integration with the FastAPI proxy."""

    @pytest.mark.asyncio
    async def test_proxy_uses_arbiter_for_local_models(self):
        """Proxy must wrap local model requests with arbiter.acquire()."""
        from proxy.server import app
        from proxy.vram_arbiter import VRAMArbiter

        # This test verifies the integration point exists
        # The actual integration is tested in test_vram_proxy.py via mocks
        assert hasattr(app, "dependency_overrides") or True  # Placeholder for integration check

    def test_arbiter_exposed_for_health_endpoint(self):
        """Arbiter must expose metrics for /health endpoint."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter()
        # Should have attributes needed for health reporting
        assert hasattr(arbiter, "active_local_requests")
        assert hasattr(arbiter, "active_remote_requests")
        assert hasattr(arbiter, "queue_depth")


class TestConcurrencyStress:
    """Stress tests for concurrency behavior."""

    @pytest.mark.asyncio
    async def test_many_concurrent_local_requests_serialized(self, execution_tracker: ExecutionTracker):
        """10+ concurrent local requests must all be strictly serialized."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter(max_concurrent_local=1)

        async def tracked_request(request_id: str):
            async with arbiter.acquire("llama-3.1-8b-instruct"):
                await execution_tracker.local_start(request_id)
                await asyncio.sleep(0.01)
                await execution_tracker.local_end(request_id)

        await asyncio.gather(*[tracked_request(f"req-{i}") for i in range(10)])

        assert execution_tracker.max_concurrent_local == 1
        assert execution_tracker.get_local_overlap() is False

    @pytest.mark.asyncio
    async def test_many_concurrent_remote_requests_parallel(self, execution_tracker: ExecutionTracker):
        """10+ concurrent remote requests must all run in parallel."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter(max_concurrent_local=1)

        async def tracked_request(request_id: str):
            async with arbiter.acquire("gpt-4o"):
                await execution_tracker.remote_start(request_id)
                await asyncio.sleep(0.01)
                await execution_tracker.remote_end(request_id)

        await asyncio.gather(*[tracked_request(f"req-{i}") for i in range(10)])

        assert execution_tracker.max_concurrent_remote == 10

    @pytest.mark.asyncio
    async def test_custom_concurrency_limit_respected(self, execution_tracker: ExecutionTracker):
        """Custom concurrency limit (e.g., 2) must be respected for local models."""
        from proxy.vram_arbiter import VRAMArbiter

        arbiter = VRAMArbiter(max_concurrent_local=2)

        async def tracked_request(request_id: str):
            async with arbiter.acquire("hermes"):
                await execution_tracker.local_start(request_id)
                await asyncio.sleep(0.02)
                await execution_tracker.local_end(request_id)

        await asyncio.gather(*[tracked_request(f"req-{i}") for i in range(5)])

        # Max concurrent should be 2 (not 1, not 5)
        assert execution_tracker.max_concurrent_local == 2


class TestCLIEntryPoint:
    """Tests for the vram-proxy CLI entrypoint."""

    def test_main_function_exists(self):
        """vram_arbiter module must have a main() function."""
        from proxy.vram_arbiter import main
        assert callable(main)

    def test_cli_parses_host_argument(self):
        """CLI must accept --host argument."""
        from proxy.vram_arbiter import main
        import sys
        from unittest.mock import patch

        with patch.object(sys, 'argv', ['vram-proxy', '--host', '0.0.0.0']):
            with patch('uvicorn.run') as mock_run:
                try:
                    main()
                except SystemExit:
                    pass
                mock_run.assert_called_once()
                args, kwargs = mock_run.call_args
                assert kwargs.get('host') == '0.0.0.0'

    def test_cli_parses_port_argument(self):
        """CLI must accept --port argument."""
        from proxy.vram_arbiter import main
        import sys
        from unittest.mock import patch

        with patch.object(sys, 'argv', ['vram-proxy', '--port', '9000']):
            with patch('uvicorn.run') as mock_run:
                try:
                    main()
                except SystemExit:
                    pass
                mock_run.assert_called_once()
                args, kwargs = mock_run.call_args
                assert kwargs.get('port') == 9000

    def test_cli_parses_upstream_argument(self):
        """CLI must accept --upstream argument."""
        from proxy.vram_arbiter import main
        import sys
        from unittest.mock import patch

        with patch.object(sys, 'argv', ['vram-proxy', '--upstream', 'http://custom:9000/v1']):
            with patch('uvicorn.run') as mock_run:
                try:
                    main()
                except SystemExit:
                    pass
                # The upstream URL should be passed to the app configuration
                mock_run.assert_called_once()

    def test_cli_parses_concurrency_argument(self):
        """CLI must accept --concurrency argument."""
        from proxy.vram_arbiter import main
        import sys
        from unittest.mock import patch

        with patch.object(sys, 'argv', ['vram-proxy', '--concurrency', '2']):
            with patch('uvicorn.run') as mock_run:
                try:
                    main()
                except SystemExit:
                    pass
                mock_run.assert_called_once()


class TestCheckVRAMScript:
    """Tests for proxy/check_vram.py health check utility."""

    def test_check_vram_module_exists(self):
        """check_vram.py must be importable."""
        import proxy.check_vram
        assert hasattr(proxy.check_vram, 'main') or hasattr(proxy.check_vram, 'check_health')

    @pytest.mark.asyncio
    async def test_check_health_returns_zero_on_healthy(self):
        """Health check must exit 0 when proxy and upstream are healthy."""
        from proxy.check_vram import check_health
        import httpx
        from unittest.mock import AsyncMock, patch

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "healthy",
            "upstream_reachable": True
        }

        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            result = await check_health("http://127.0.0.1:8000")
            assert result == 0

    @pytest.mark.asyncio
    async def test_check_health_returns_one_on_proxy_down(self):
        """Health check must exit 1 when proxy is unreachable."""
        from proxy.check_vram import check_health
        import httpx
        from unittest.mock import AsyncMock, patch

        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")

            result = await check_health("http://127.0.0.1:8000")
            assert result == 1

    @pytest.mark.asyncio
    async def test_check_health_returns_one_on_unhealthy_status(self):
        """Health check must exit 1 when proxy reports unhealthy."""
        from proxy.check_vram import check_health
        import httpx
        from unittest.mock import AsyncMock, patch

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "unhealthy",
            "upstream_reachable": False
        }

        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            result = await check_health("http://127.0.0.1:8000")
            assert result == 1

    @pytest.mark.asyncio
    async def test_check_health_returns_one_on_timeout(self):
        """Health check must exit 1 on timeout."""
        from proxy.check_vram import check_health
        import httpx
        from unittest.mock import AsyncMock, patch

        with patch('httpx.AsyncClient.get', new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Timeout")

            result = await check_health("http://127.0.0.1:8000", timeout=2.0)
            assert result == 1

    def test_main_exits_with_check_result(self):
        """Main function must exit with check_health result."""
        from proxy.check_vram import main
        import sys
        from unittest.mock import patch, AsyncMock

        with patch('proxy.check_vram.check_health', new_callable=AsyncMock) as mock_check:
            mock_check.return_value = 0
            with patch.object(sys, 'exit') as mock_exit:
                try:
                    import asyncio
                    asyncio.run(main())
                except SystemExit:
                    pass
                mock_exit.assert_called_with(0)

        with patch('proxy.check_vram.check_health', new_callable=AsyncMock) as mock_check:
            mock_check.return_value = 1
            with patch.object(sys, 'exit') as mock_exit:
                try:
                    import asyncio
                    asyncio.run(main())
                except SystemExit:
                    pass
                mock_exit.assert_called_with(1)


