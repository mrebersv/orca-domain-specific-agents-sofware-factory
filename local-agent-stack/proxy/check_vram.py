"""
VRAM Proxy Health Check Utility.

Standalone script invoked by Orca lifecycle hooks before launching sub-agent nodes.
Checks if the VRAM proxy is online and upstream is reachable.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

import httpx


DEFAULT_PROXY_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 2.0


async def check_health(
    proxy_url: str = DEFAULT_PROXY_URL,
    timeout: float = DEFAULT_TIMEOUT
) -> int:
    """
    Check health of VRAM proxy and upstream.

    Args:
        proxy_url: Base URL of the VRAM proxy (default: http://127.0.0.1:8000)
        timeout: Request timeout in seconds (default: 2.0)

    Returns:
        0 if proxy and upstream are healthy, 1 otherwise.
    """
    health_url = f"{proxy_url.rstrip('/')}/health"

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(health_url)

            if response.status_code != 200:
                print(
                    f"[ERROR] Proxy health endpoint returned {response.status_code}",
                    file=sys.stderr
                )
                return 1

            data = response.json()

            # Check proxy status
            status = data.get("status", "unknown")
            upstream_reachable = data.get("upstream_reachable", False)

            if status == "healthy" and upstream_reachable:
                print("[OK] Local VRAM proxy online")
                return 0
            else:
                print(
                    f"[ERROR] Proxy unhealthy: status={status}, upstream_reachable={upstream_reachable}",
                    file=sys.stderr
                )
                _print_remediation()
                return 1

    except httpx.ConnectError:
        print(
            f"[ERROR] Cannot connect to VRAM proxy at {proxy_url}",
            file=sys.stderr
        )
        _print_remediation()
        return 1

    except httpx.TimeoutException:
        print(
            f"[ERROR] VRAM proxy health check timed out after {timeout}s",
            file=sys.stderr
        )
        _print_remediation()
        return 1

    except Exception as e:
        print(
            f"[ERROR] Unexpected error during health check: {e}",
            file=sys.stderr
        )
        _print_remediation()
        return 1


def _print_remediation() -> None:
    """Print remediation steps for common issues."""
    print("", file=sys.stderr)
    print("Remediation steps:", file=sys.stderr)
    print("  1. Start the VRAM proxy:  vram-proxy &", file=sys.stderr)
    print("  2. Or specify custom host/port:  vram-proxy --host 0.0.0.0 --port 8000", file=sys.stderr)
    print("  3. Ensure local inference backend is running (llama.cpp, Ollama, etc.)", file=sys.stderr)
    print("  4. Check LOCAL_INFERENCE_URL environment variable points to correct upstream", file=sys.stderr)
    print("  5. Verify upstream health: curl http://127.0.0.1:8080/health", file=sys.stderr)


async def main() -> None:
    """
    Main entrypoint for check_vram script.

    Reads proxy URL from environment or uses default.
    Exits with 0 on success, 1 on failure.
    """
    import os

    proxy_url = os.environ.get("VRAM_PROXY_URL", DEFAULT_PROXY_URL)
    timeout_str = os.environ.get("VRAM_PROXY_TIMEOUT", str(DEFAULT_TIMEOUT))

    try:
        timeout = float(timeout_str)
    except ValueError:
        timeout = DEFAULT_TIMEOUT

    exit_code = await check_health(proxy_url, timeout)
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
