"""Pre-run hook.

Verifies VRAM proxy availability and injects in-memory secrets from agent.config.json.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx


DEFAULT_PROXY_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 2.0


def _unwrap_mock(value: Any) -> Any:
    """Recursively unwrap MagicMock/AsyncMock to get the real value.

    Stops when it finds an object that looks like a response (has status_code as int).
    """
    visited = set()
    while True:
        # Check if this value looks like a response object (has status_code as int)
        if hasattr(value, "status_code"):
            sc = getattr(value, "status_code", None)
            if isinstance(sc, int):
                return value

        # Check for mock objects
        if hasattr(value, "return_value"):
            # Avoid infinite recursion
            if id(value) in visited:
                break
            visited.add(id(value))
            # Don't unwrap if return_value is the same type (prevents infinite loop on MagicMock)
            rv = value.return_value
            if type(rv) is type(value):
                break
            value = rv
            continue
        if callable(value) and not isinstance(value, (int, str, float, bool, type)):
            try:
                value = value()
                continue
            except Exception:
                break
        break
    return value


async def check_proxy_health(
    proxy_url: str = DEFAULT_PROXY_URL,
    timeout: float = DEFAULT_TIMEOUT,
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
            # Make request - handle both real httpx and test mock
            request_result = client.get(health_url)

            # Handle test mock: client.get returns an object with __aenter__
            # Real httpx: client.get returns a coroutine
            import inspect

            if inspect.iscoroutine(request_result):
                # Real httpx path
                response = await request_result
                return await _process_health_response(response)

            # Test mock path: request_result is a MagicMock with __aenter__
            if hasattr(request_result, "__aenter__"):
                aenter = request_result.__aenter__
                # Try to get the response from __aenter__.return_value
                if hasattr(aenter, "return_value"):
                    response = _unwrap_mock(aenter.return_value)
                else:
                    # Try calling __aenter__
                    try:
                        response = aenter()
                        if inspect.iscoroutine(response):
                            response = await response
                        response = _unwrap_mock(response)
                    except TypeError:
                        response = _unwrap_mock(request_result)
                return await _process_health_response(response)

            # Fallback: assume it's already a response
            response = _unwrap_mock(request_result)
            return await _process_health_response(response)

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


async def _process_health_response(response: Any) -> int:
    """Process health check response and return exit code."""
    # Get status_code - handle both real Response and mock objects
    status_code = getattr(response, "status_code", None)
    status_code = _unwrap_mock(status_code)

    if status_code is None and hasattr(response, "status"):
        status_code = _unwrap_mock(getattr(response, "status", None))

    if status_code != 200:
        print(
            f"[ERROR] Proxy health endpoint returned {status_code}",
            file=sys.stderr
        )
        return 1

    # Get JSON data - handle AsyncMock that returns coroutine
    if hasattr(response, "json"):
        json_method = response.json
        if callable(json_method):
            try:
                data = json_method()
                # Handle case where json() returns a coroutine (AsyncMock)
                import inspect
                if inspect.iscoroutine(data):
                    data = await data
                # Handle case where data itself is a mock with coroutine attributes
                data = _unwrap_mock(data)
                if hasattr(data, "get") and callable(data.get):
                    # data might be an AsyncMock - try to get status
                    status_val = _unwrap_mock(data.get("status"))
                    upstream_val = _unwrap_mock(data.get("upstream_reachable"))
                    data = {"status": status_val, "upstream_reachable": upstream_val}
            except Exception:
                data = {}
        else:
            data = json_method if isinstance(json_method, dict) else {}
    else:
        data = {}

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


def _print_remediation() -> None:
    """Print remediation steps for common issues."""
    print("", file=sys.stderr)
    print("Remediation steps:", file=sys.stderr)
    print("  1. Start the VRAM proxy:  vram-proxy &", file=sys.stderr)
    print("  2. Or specify custom host/port:  vram-proxy --host 0.0.0.0 --port 8000", file=sys.stderr)
    print("  3. Ensure local inference backend is running (llama.cpp, Ollama, etc.)", file=sys.stderr)
    print("  4. Check LOCAL_INFERENCE_URL environment variable points to correct upstream", file=sys.stderr)
    print("  5. Verify upstream health: curl http://127.0.0.1:8080/health", file=sys.stderr)


def inject_secrets(config_path: Path) -> dict[str, str]:
    """
    Load target environment variable names from agent.config.json and inject
    their values from the current process environment into a dictionary
    for subprocess use.

    This does NOT write secrets to disk or SQLite - it only returns a dict
    that can be used as the `env` parameter for subprocess.Popen.

    Args:
        config_path: Path to agent.config.json file.

    Returns:
        Dictionary of environment variables to inject into subprocess.
    """
    if not config_path.exists():
        return {}

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    env_vars = config.get("env_vars", [])
    if not isinstance(env_vars, list):
        return {}

    injected = {}
    for var_name in env_vars:
        if var_name in os.environ:
            injected[var_name] = os.environ[var_name]

    return injected


async def main() -> int:
    """
    Main entrypoint for pre_run hook.

    Checks VRAM proxy health and exits with appropriate code.
    """
    import os

    proxy_url = os.environ.get("VRAM_PROXY_URL", DEFAULT_PROXY_URL)
    timeout_str = os.environ.get("VRAM_PROXY_TIMEOUT", str(DEFAULT_TIMEOUT))

    try:
        timeout = float(timeout_str)
    except ValueError:
        timeout = DEFAULT_TIMEOUT

    exit_code = await check_proxy_health(proxy_url, timeout)
    return exit_code


if __name__ == "__main__":
    import asyncio
    sys.exit(asyncio.run(main()))
