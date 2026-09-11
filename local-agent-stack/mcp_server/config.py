"""Shared configuration for MCP server modules."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# Global state for database path configuration - use a mutable container
# so that imports across modules share the same reference
_current_db_path_holder: list[Optional[Path]] = [None]


def set_db_path(db_path: Path) -> None:
    """Configure the active database path for the server."""
    _current_db_path_holder[0] = db_path.resolve()


def get_db_path() -> Optional[Path]:
    """Get the currently configured database path."""
    return _current_db_path_holder[0]


def reset_db_path() -> None:
    """Reset the database path to None (for testing)."""
    _current_db_path_holder[0] = None


# Backward compatibility: expose as a property-like object
# that reads/writes to the holder
class _DBPathProxy:
    def __get__(self, obj, objtype=None):
        return _current_db_path_holder[0]

    def __set__(self, obj, value):
        _current_db_path_holder[0] = value.resolve() if value is not None else None


# Module-level instance for backward compatibility
_current_db_path = _DBPathProxy()


__all__ = ["set_db_path", "get_db_path", "reset_db_path", "_current_db_path"]
