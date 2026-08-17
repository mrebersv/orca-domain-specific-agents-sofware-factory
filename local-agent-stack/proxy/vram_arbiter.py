"""
VRAM Arbiter - GPU Semaphore Concurrency Controller.

Manages asyncio.Semaphore locks per GPU device/local backend to serialize
local inference requests while allowing remote API requests to pass through.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional


class VRAMArbiter:
    """
    Concurrency arbiter for local GPU inference requests.

    Uses asyncio.Semaphore to serialize requests to local models while
    allowing remote model requests to bypass the lock and run concurrently.
    """

    def __init__(self, max_concurrent_local: int = 1):
        """
        Initialize the VRAM arbiter.

        Args:
            max_concurrent_local: Maximum concurrent requests for local models.
                                  Defaults to 1 to prevent GPU OOM.
        """
        self.max_concurrent_local = max_concurrent_local
        self.semaphore = asyncio.Semaphore(max_concurrent_local)
        self.active_local_requests = 0
        self.active_remote_requests = 0
        self.queue_depth = 0
        self._local_model_patterns = [
            "hermes",
            "qwen",
            "llama",
            "local-slm",
            "llama.cpp",
            "ollama",
        ]

    def is_local_model(self, model_name: str) -> bool:
        """
        Determine if a model name targets a local backend.

        Args:
            model_name: The model identifier from the request.

        Returns:
            True if the model should be routed to local backend, False for remote APIs.
        """
        if not model_name:
            return False

        model_lower = model_name.lower()

        # Check for known remote provider prefixes
        remote_prefixes = [
            "gpt-",
            "claude-",
            "gemini-",
            "openai/",
            "anthropic/",
            "google/",
            "mistral/",
            "cohere/",
        ]
        for prefix in remote_prefixes:
            if model_lower.startswith(prefix):
                return False

        # Check for remote indicators in model name
        remote_indicators = ["remote-", "remote_", "api-", "cloud-"]
        for indicator in remote_indicators:
            if indicator in model_lower:
                return False

        # Check for known local model patterns
        for pattern in self._local_model_patterns:
            if pattern in model_lower:
                return True

        # Default: treat unknown models as local (safer for GPU)
        return True

    @asynccontextmanager
    async def acquire(self, model_name: str):
        """
        Acquire semaphore lock for local models, bypass for remote models.

        Args:
            model_name: The model identifier to check.

        Yields:
            None when lock is acquired (for local) or immediately (for remote).
        """
        is_local = self.is_local_model(model_name)

        if is_local:
            # Track queue depth before acquiring
            self.queue_depth += 1
            try:
                await self.semaphore.acquire()
                self.queue_depth -= 1
                self.active_local_requests += 1
                try:
                    yield
                finally:
                    self.active_local_requests -= 1
                    self.semaphore.release()
            except Exception:
                self.queue_depth -= 1
                raise
        else:
            # Remote model - bypass semaphore, just track
            self.active_remote_requests += 1
            try:
                yield
            finally:
                self.active_remote_requests -= 1


# Singleton instance for module-level access
_arbiter_instance: Optional[VRAMArbiter] = None


def get_vram_arbiter() -> VRAMArbiter:
    """Get or create the global VRAMArbiter instance."""
    global _arbiter_instance
    if _arbiter_instance is None:
        concurrency = int(os.environ.get("LOCAL_CONCURRENCY", "1"))
        _arbiter_instance = VRAMArbiter(max_concurrent_local=concurrency)
    return _arbiter_instance


def create_app(
    host: str = "127.0.0.1",
    port: int = 8000,
    upstream: str = "http://127.0.0.1:8080/v1",
    concurrency: int = 1
):
    """
    Create and configure the FastAPI application with VRAM arbiter.

    This function is called by the CLI entrypoint to set up the app
    with custom configuration before running with uvicorn.
    """
    # Set environment variables for the server module
    os.environ["LOCAL_INFERENCE_URL"] = upstream
    os.environ["LOCAL_CONCURRENCY"] = str(concurrency)

    # Import here to pick up env vars
    from proxy.server import app
    return app


def main():
    """
    CLI entrypoint for vram-proxy command.

    Parses command line arguments and starts the uvicorn server.
    """
    parser = argparse.ArgumentParser(
        description="VRAM Proxy - Local Model Inference Reverse Proxy with GPU Semaphore"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to bind to (default: 8000)"
    )
    parser.add_argument(
        "--upstream",
        default="http://127.0.0.1:8080/v1",
        help="Upstream inference server URL (default: http://127.0.0.1:8080/v1)"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max concurrent local model requests (default: 1)"
    )

    args = parser.parse_args()

    # Set environment variables for the server
    os.environ["LOCAL_INFERENCE_URL"] = args.upstream
    os.environ["LOCAL_CONCURRENCY"] = str(args.concurrency)

    # Import and run uvicorn
    import uvicorn

    uvicorn.run(
        "proxy.server:app",
        host=args.host,
        port=args.port,
        log_level="info",
        reload=False
    )


if __name__ == "__main__":
    main()
