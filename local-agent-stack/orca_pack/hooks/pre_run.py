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
            response = await client.get(health_url)
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
    status_code = getattr(response, "status_code", None)

    if status_code != 200:
        print(
            f"[ERROR] Proxy health endpoint returned {status_code}",
            file=sys.stderr
        )
        return 1

    if hasattr(response, "json"):
        try:
            data = response.json()
        except Exception:
            data = {}
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
