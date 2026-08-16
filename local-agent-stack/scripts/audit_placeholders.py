#!/usr/bin/env python3
"""Project Placeholder & Implementation Audit Tool.

Scans the local-agent-stack repository to identify zero-byte files, whitespace-only
files, and semantic stubs (e.g., files with only shebangs, 'pass', or comments).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple

# Directories and files to exclude from analysis
IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".idea",
    ".vscode",
}

IGNORE_FILES = {
    ".DS_Store",
}

# ANSI color codes for terminal formatting
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


class FileStatus(NamedTuple):
    path: Path
    category: str  # 'READY', 'EMPTY', 'WHITESPACE', 'STUB', 'EMPTY_STRUCT', 'EMPTY_INIT'
    size_bytes: int
    line_count: int
    detail: str


def is_python_stub(content: str) -> bool:
    """Checks if Python content contains only comments, docstrings, pass, or ellipsis."""
    # Strip line comments
    lines = [re.sub(r"#.*$", "", line).strip() for line in content.splitlines()]
    # Remove empty lines
    non_empty = [l for l in lines if l]
    if not non_empty:
        return True

    code_body = " ".join(non_empty)
    # Check for trivial stub patterns
    stub_patterns = {
        "pass",
        "...",
        "raise NotImplementedError",
        "raise NotImplementedError()",
    }
    return code_body in stub_patterns


def is_markdown_stub(content: str) -> bool:
    """Checks if Markdown content is just a single heading or empty comment."""
    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("<!--")
    ]
    if not lines:
        return True
    # If it's just 1 line starting with # and nothing else
    if len(lines) == 1 and lines[0].startswith("#"):
        return True
    return False


def is_shell_stub(content: str) -> bool:
    """Checks if Shell script has only a shebang or set directives."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    substantive = [
        l
        for l in lines
        if not l.startswith("#")
        and not l.startswith("set -")
        and l not in {"set -e", "set -euo pipefail"}
    ]
    return len(substantive) == 0


def analyze_file(file_path: Path) -> FileStatus:
    size = file_path.stat().st_size
    if size == 0:
        if file_path.name == "__init__.py":
            return FileStatus(
                file_path, "EMPTY_INIT", 0, 0, "Empty package marker"
            )
        return FileStatus(file_path, "EMPTY", 0, 0, "0 bytes")

    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return FileStatus(file_path, "ERROR", size, 0, f"Read error: {e}")

    lines = content.splitlines()
    line_count = len(lines)
    stripped = content.strip()

    if not stripped:
        return FileStatus(
            file_path, "WHITESPACE", size, line_count, "Whitespace only"
        )

    suffix = file_path.suffix.lower()

    # JSON / YAML empty structures
    if suffix == ".json" and stripped in {"{}", "[]", '""'}:
        return FileStatus(
            file_path, "EMPTY_STRUCT", size, line_count, "Empty JSON object/list"
        )
    if suffix in {".yaml", ".yml"} and stripped in {"---", "{}"}:
        return FileStatus(
            file_path, "EMPTY_STRUCT", size, line_count, "Empty YAML document"
        )

    # Shell script stub check
    if suffix in {".sh", ".bash"} and is_shell_stub(content):
        return FileStatus(
            file_path, "STUB", size, line_count, "Shebang/boilerplate only"
        )

    # Python module stub check
    if suffix == ".py":
        if file_path.name == "__init__.py" and (
            not stripped or is_python_stub(content)
        ):
            return FileStatus(
                file_path, "EMPTY_INIT", size, line_count, "Empty package marker"
            )
        if is_python_stub(content):
            return FileStatus(
                file_path, "STUB", size, line_count, "Pass/stub statements only"
            )

    # Markdown stub check
    if suffix == ".md" and is_markdown_stub(content):
        return FileStatus(
            file_path, "STUB", size, line_count, "Header/boilerplate only"
        )

    # Substantive content present
    return FileStatus(
        file_path, "READY", size, line_count, f"{line_count} lines"
    )


def scan_tree(root: Path) -> list[FileStatus]:
    results: list[FileStatus] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # In-place directory filtering
        dirnames[:] = [
            d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")
        ]

        for fname in sorted(filenames):
            if fname in IGNORE_FILES or fname.startswith("."):
                continue
            fpath = Path(dirpath) / fname
            if fpath.is_file() and not fpath.is_symlink():
                results.append(analyze_file(fpath))
    return sorted(results, key=lambda x: str(x.path))


def print_report(
    results: list[FileStatus], show_all: bool = False, root: Path = Path(".")
):
    grouped: dict[str, list[FileStatus]] = defaultdict(list)
    for r in results:
        # Group by top-level directory or root
        rel_path = r.path.relative_to(root)
        top_group = rel_path.parts[0] if len(rel_path.parts) > 1 else "."
        grouped[top_group].append(r)

    total_files = len(results)
    ready_files = sum(1 for r in results if r.category == "READY")
    init_files = sum(1 for r in results if r.category == "EMPTY_INIT")
    placeholder_files = total_files - ready_files - init_files

    badge_map = {
        "READY": f"{GREEN}[READY]{RESET}",
        "EMPTY": f"{RED}[EMPTY]{RESET}",
        "WHITESPACE": f"{RED}[BLANK]{RESET}",
        "STUB": f"{YELLOW}[ STUB]{RESET}",
        "EMPTY_STRUCT": f"{YELLOW}[EMPTY]{RESET}",
        "EMPTY_INIT": f"{CYAN}[ INIT]{RESET}",
    }

    print(
        f"\n{BOLD}{BLUE}==================================================================={RESET}"
    )
    print(f"{BOLD}  LOCAL AGENT STACK — IMPLEMENTATION & PLACEHOLDER AUDIT{RESET}")
    print(
        f"{BOLD}{BLUE}==================================================================={RESET}\n"
    )

    for group, items in sorted(grouped.items()):
        group_placeholders = [
            i for i in items if i.category not in {"READY", "EMPTY_INIT"}
        ]
        if not show_all and not group_placeholders:
            continue

        print(f"{BOLD}{CYAN}📁 {group}/{RESET}")
        for item in items:
            rel = item.path.relative_to(root)
            is_placeholder = item.category not in {"READY", "EMPTY_INIT"}

            if not show_all and not is_placeholder:
                continue

            badge = badge_map.get(item.category, f"[{item.category}]")
            size_str = f"{item.size_bytes:>6} B"
            print(f"  {badge}  {size_str}  {str(rel):<55} ({item.detail})")
        print()

    # Summary Dashboard
    pct_ready = (ready_files / total_files * 100) if total_files else 0
    print(
        f"{BOLD}{BLUE}-------------------------------------------------------------------{RESET}"
    )
    print(f"{BOLD}📊 REPOSITORY PROGRESS SUMMARY{RESET}")
    print(
        f"{BOLD}{BLUE}-------------------------------------------------------------------{RESET}"
    )
    print(f"  • Total Tracked Files:     {BOLD}{total_files}{RESET}")
    print(
        f"  • Fully Implemented:       {GREEN}{ready_files} ({pct_ready:.1f}%){RESET}"
    )
    print(f"  • Valid Empty Markers:     {CYAN}{init_files}{RESET} (__init__.py)")
    print(f"  • Placeholders / Stubs:    {RED}{placeholder_files}{RESET}")
    print(
        f"{BOLD}{BLUE}-------------------------------------------------------------------{RESET}\n"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Audit placeholder and implementation status of local-agent-stack files."
    )
    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Show all files including fully implemented files",
    )
    parser.add_argument(
        "--root",
        "-r",
        type=Path,
        default=Path("."),
        help="Root directory of repository (default: current directory)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero code if any placeholders remain (for CI/CD gates)",
    )
    args = parser.parse_args()

    results = scan_tree(args.root)
    print_report(results, show_all=args.all, root=args.root)

    if args.strict:
        placeholders = [
            r for r in results if r.category not in {"READY", "EMPTY_INIT"}
        ]
        if placeholders:
            sys.exit(1)


if __name__ == "__main__":
    main()
