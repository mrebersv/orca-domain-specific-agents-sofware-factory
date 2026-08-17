"""Python AST & Docstring Extractor for Agent Forge (Path A)."""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path
from typing import Any, Optional
import docstring_parser
from docstring_parser import Docstring, DocstringParam, DocstringRaises
from docstring_parser.common import DocstringExample

from agent_forge.db.docs import get_docs_db, insert_symbol_bundle


DESTRUCTIVE_KEYWORDS = frozenset({
    "delete", "remove", "drop", "purge", "destroy",
    "update", "set", "write", "create", "insert", "add",
    "modify", "change", "alter", "truncate", "clear",
    "reset", "flush", "invalidate", "revoke", "disable",
})

IGNORE_DIRS = frozenset({
    ".git", ".venv", "__pycache__", "tests", "build", "dist",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules",
    ".tox", "venv", "env", ".env", "htmlcov", ".coverage",
})


class PythonASTExtractor:
    """Deterministic Python AST and docstring extractor."""

    def __init__(self) -> None:
        self.symbols_extracted: list[dict[str, Any]] = []

    def _is_destructive(self, name: str) -> bool:
        """Check if a function/method name suggests destructive behavior."""
        name_lower = name.lower()
        return any(kw in name_lower for kw in DESTRUCTIVE_KEYWORDS)

    def _get_type_annotation(self, annotation: Optional[ast.AST]) -> Optional[str]:
        """Extract type annotation as string from AST node."""
        if annotation is None:
            return None
        try:
            return ast.unparse(annotation)
        except Exception:
            return None

    def _get_default_value(self, default: Optional[ast.AST]) -> Optional[str]:
        """Extract default value as string from AST node."""
        if default is None:
            return None
        try:
            return ast.unparse(default)
        except Exception:
            return None

    def _fix_docstring_indentation(self, docstring: str) -> str:
        """Fix indentation of docstring section headers (Args:, Returns:, etc.)."""
        lines = docstring.split('\n')
        if not lines:
            return docstring

        result = [lines[0]]  # Keep first line as is

        for line in lines[1:]:
            if not line.strip():
                result.append(line)
                continue
            # Check if this line is a section header
            stripped = line.lstrip()
            if re.match(r'^(Args|Returns|Raises|Example|Examples|Parameters|Yields|Attributes|Note|Notes|Warning|Warnings|See Also|References):', stripped):
                # Section header - remove all leading whitespace
                result.append(stripped)
            else:
                result.append(line)

        return '\n'.join(result)

    def _parse_docstring(self, node: ast.AST) -> Optional[Docstring]:
        """Parse docstring from AST node using docstring-parser."""
        docstring = ast.get_docstring(node)
        if docstring:
            # Fix indentation of section headers
            fixed = self._fix_docstring_indentation(docstring)
            try:
                return docstring_parser.parse(fixed)
            except Exception:
                return None
        return None

    def _extract_parameters(
        self,
        args: ast.arguments,
        docstring: Optional[Docstring],
    ) -> list[dict[str, Any]]:
        """Extract parameter information from function arguments and docstring."""
        params = []

        # Build docstring param descriptions map
        param_descriptions = {}
        if docstring and docstring.params:
            for dp in docstring.params:
                param_descriptions[dp.arg_name] = dp.description

        # Positional-only args (Python 3.8+)
        for arg in args.posonlyargs:
            param_name = arg.arg
            desc = param_descriptions.get(param_name)
            params.append({
                "name": param_name,
                "param_type": self._get_type_annotation(arg.annotation),
                "default_value": None,
                "is_required": True,
                "description": desc if desc is not None else "",
            })

        # Regular positional args
        num_defaults = len(args.defaults)
        num_args = len(args.args)
        first_default_idx = num_args - num_defaults

        for i, arg in enumerate(args.args):
            param_name = arg.arg
            has_default = i >= first_default_idx
            default_idx = i - first_default_idx if has_default else None
            desc = param_descriptions.get(param_name)
            params.append({
                "name": param_name,
                "param_type": self._get_type_annotation(arg.annotation),
                "default_value": self._get_default_value(args.defaults[default_idx]) if has_default else None,
                "is_required": not has_default,
                "description": desc if desc is not None else "",
            })

        # *args
        if args.vararg:
            desc = param_descriptions.get(args.vararg.arg)
            params.append({
                "name": f"*{args.vararg.arg}",
                "param_type": self._get_type_annotation(args.vararg.annotation),
                "default_value": None,
                "is_required": False,
                "description": desc if desc is not None else "",
            })

        # Keyword-only args
        for i, arg in enumerate(args.kwonlyargs):
            param_name = arg.arg
            has_default = i < len(args.kw_defaults) and args.kw_defaults[i] is not None
            desc = param_descriptions.get(param_name)
            params.append({
                "name": param_name,
                "param_type": self._get_type_annotation(arg.annotation),
                "default_value": self._get_default_value(args.kw_defaults[i]) if has_default else None,
                "is_required": not has_default,
                "description": desc if desc is not None else "",
            })

        # **kwargs
        if args.kwarg:
            desc = param_descriptions.get(args.kwarg.arg)
            params.append({
                "name": f"**{args.kwarg.arg}",
                "param_type": self._get_type_annotation(args.kwarg.annotation),
                "default_value": None,
                "is_required": False,
                "description": desc if desc is not None else "",
            })

        return params

    def _extract_examples(self, docstring_raw: str) -> list[dict[str, Any]]:
        """Extract code examples from raw docstring."""
        return self._extract_examples_from_raw_docstring(docstring_raw)

    def _extract_examples_from_raw_docstring(self, docstring: str) -> list[dict[str, Any]]:
        """Extract code examples from raw docstring text."""
        examples = []

        # First fix the indentation of section headers
        lines = docstring.split('\n')
        if not lines:
            return examples

        fixed_lines = [lines[0]]
        for line in lines[1:]:
            if not line.strip():
                fixed_lines.append(line)
                continue
            stripped = line.lstrip()
            if re.match(r'^(Args|Returns|Raises|Example|Examples|Parameters|Yields|Attributes|Note|Notes|Warning|Warnings|See Also|References):', stripped):
                fixed_lines.append(stripped)
            else:
                fixed_lines.append(line)

        fixed = '\n'.join(fixed_lines)

        # Find Example/Examples sections and their content
        section_pattern = re.compile(
            r'^(Example|Examples):\s*\n(.*?)(?=\n(?:Args|Returns|Raises|Example|Examples|Parameters|Yields|Attributes|Note|Notes|Warning|Warnings|See Also|References):|\Z)',
            re.MULTILINE | re.DOTALL
        )

        for match in section_pattern.finditer(fixed):
            content = match.group(2).strip()
            if content:
                examples.append({
                    "title": "Example",
                    "code_snippet": content,
                    "source_origin": "extracted_docstring",
                })

        return examples

    def _extract_error_codes(self, docstring: Optional[Docstring]) -> list[dict[str, Any]]:
        """Extract raised exceptions from docstring."""
        error_codes = []
        if docstring and docstring.raises:
            for raises in docstring.raises:
                if isinstance(raises, DocstringRaises):
                    error_codes.append({
                        "code": raises.type_name or "Exception",
                        "meaning": raises.description or "No description provided",
                        "recovery_action": "Handle exception appropriately",
                    })
        return error_codes

    def _build_signature(
        self,
        name: str,
        args: ast.arguments,
        returns: Optional[ast.AST],
        is_async: bool = False,
    ) -> str:
        """Build full signature string from AST."""
        parts = []
        if is_async:
            parts.append("async def")
        else:
            parts.append("def")
        parts.append(name)

        # Build parameter list
        param_parts = []

        # Positional-only
        for arg in args.posonlyargs:
            param = arg.arg
            if arg.annotation:
                param += f": {self._get_type_annotation(arg.annotation)}"
            param_parts.append(param)
        if args.posonlyargs and (args.args or args.vararg or args.kwonlyargs):
            param_parts.append("/")

        # Regular positional
        num_defaults = len(args.defaults)
        num_args = len(args.args)
        first_default_idx = num_args - num_defaults

        for i, arg in enumerate(args.args):
            param = arg.arg
            if arg.annotation:
                param += f": {self._get_type_annotation(arg.annotation)}"
            if i >= first_default_idx:
                default_idx = i - first_default_idx
                param += f" = {self._get_default_value(args.defaults[default_idx])}"
            param_parts.append(param)

        # *args
        if args.vararg:
            param = f"*{args.vararg.arg}"
            if args.vararg.annotation:
                param += f": {self._get_type_annotation(args.vararg.annotation)}"
            param_parts.append(param)

        # Keyword-only separator
        if args.kwonlyargs and not args.vararg:
            param_parts.append("*")

        # Keyword-only
        for i, arg in enumerate(args.kwonlyargs):
            param = arg.arg
            if arg.annotation:
                param += f": {self._get_type_annotation(arg.annotation)}"
            if i < len(args.kw_defaults) and args.kw_defaults[i] is not None:
                param += f" = {self._get_default_value(args.kw_defaults[i])}"
            param_parts.append(param)

        # **kwargs
        if args.kwarg:
            param = f"**{args.kwarg.arg}"
            if args.kwarg.annotation:
                param += f": {self._get_type_annotation(args.kwarg.annotation)}"
            param_parts.append(param)

        parts.append(f"({', '.join(param_parts)})")

        # Return type
        if returns:
            parts.append(f" -> {self._get_type_annotation(returns)}")

        parts.append(":")
        return " ".join(parts)

    def _extract_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        parent_scope: str,
        module_path: str,
        source_file: str,
    ) -> dict[str, Any]:
        """Extract a function or method symbol."""
        is_async = isinstance(node, ast.AsyncFunctionDef)
        signature = self._build_signature(node.name, node.args, node.returns, is_async)
        return_type = self._get_type_annotation(node.returns)

        docstring_raw = ast.get_docstring(node) or ""
        docstring = self._parse_docstring(node)

        parameters = self._extract_parameters(node.args, docstring)
        examples = self._extract_examples(docstring_raw)
        error_codes = self._extract_error_codes(docstring)

        symbol_id = f"{module_path}.{parent_scope}.{node.name}" if parent_scope != module_path else f"{module_path}.{node.name}"

        return {
            "symbol_id": symbol_id,
            "symbol_type": "method" if parent_scope != module_path else "function",
            "parent_scope": parent_scope,
            "signature": signature,
            "return_type": return_type,
            "docstring_raw": docstring_raw,
            "source_file": source_file,
            "is_destructive": self._is_destructive(node.name),
            "parameters": parameters,
            "examples": examples,
            "error_codes": error_codes,
        }

    def _extract_class(
        self,
        node: ast.ClassDef,
        module_path: str,
        source_file: str,
    ) -> dict[str, Any]:
        """Extract a class symbol and its methods."""
        docstring_raw = ast.get_docstring(node) or ""
        docstring = self._parse_docstring(node)

        symbol_id = f"{module_path}.{node.name}"

        class_symbol = {
            "symbol_id": symbol_id,
            "symbol_type": "class",
            "parent_scope": module_path,
            "signature": f"class {node.name}:",
            "return_type": None,
            "docstring_raw": docstring_raw,
            "source_file": source_file,
            "is_destructive": False,
            "parameters": [],
            "examples": self._extract_examples(docstring_raw),
            "error_codes": [],
        }

        # Extract methods
        method_symbols = []
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_symbol = self._extract_function(item, node.name, module_path, source_file)
                method_symbols.append(method_symbol)

        return {
            "class": class_symbol,
            "methods": method_symbols,
        }

    def _extract_module_symbols(
        self,
        tree: ast.Module,
        module_path: str,
        source_file: str,
    ) -> list[dict[str, Any]]:
        """Extract all symbols from a module AST."""
        symbols = []

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(self._extract_function(node, module_path, module_path, source_file))
            elif isinstance(node, ast.ClassDef):
                class_result = self._extract_class(node, module_path, source_file)
                symbols.append(class_result["class"])
                symbols.extend(class_result["methods"])
                # Also extract nested classes
                symbols.extend(self._extract_nested_classes(node, module_path, source_file))

        return symbols

    def _extract_nested_classes(
        self,
        class_node: ast.ClassDef,
        parent_scope: str,
        source_file: str,
    ) -> list[dict[str, Any]]:
        """Extract nested classes and their methods."""
        symbols = []
        for node in class_node.body:
            if isinstance(node, ast.ClassDef):
                # Extract the nested class
                nested_result = self._extract_class(node, parent_scope, source_file)
                symbols.append(nested_result["class"])
                symbols.extend(nested_result["methods"])
                # Recurse for deeper nesting
                symbols.extend(self._extract_nested_classes(node, parent_scope, source_file))
        return symbols

    def parse_file(self, file_path: Path) -> list[dict[str, Any]]:
        """Parse a single Python file and extract symbols."""
        source = file_path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError as e:
            raise ValueError(f"Syntax error in {file_path}: {e}")

        # Derive module path from file path
        module_path = str(file_path.with_suffix("")).replace("/", ".").replace("\\", ".")
        # Clean up common prefixes
        module_path = re.sub(r"^\.+", "", module_path)

        return self._extract_module_symbols(tree, module_path, str(file_path))

    def parse_directory(self, dir_path: Path) -> list[dict[str, Any]]:
        """Recursively parse all Python files in a directory."""
        all_symbols = []

        for py_file in dir_path.rglob("*.py"):
            # Skip ignored directories
            if any(part in IGNORE_DIRS for part in py_file.parts):
                continue
            try:
                symbols = self.parse_file(py_file)
                all_symbols.extend(symbols)
            except Exception as e:
                print(f"Warning: Failed to parse {py_file}: {e}")

        return all_symbols

    async def extract_and_ingest_python_tree(
        self,
        source_root: Path,
        db_path: Path,
    ) -> int:
        """Extract symbols from Python source tree and ingest into docs.db."""
        if source_root.is_file():
            symbols = self.parse_file(source_root)
        else:
            symbols = self.parse_directory(source_root)

        total_ingested = 0
        async with get_docs_db(db_path, read_only=False) as db:
            for symbol in symbols:
                # Separate the main symbol data from related data
                symbol_data = {k: v for k, v in symbol.items() if k not in ("parameters", "examples", "error_codes")}
                params = symbol.get("parameters", [])
                examples = symbol.get("examples", [])
                errors = symbol.get("error_codes", [])

                await insert_symbol_bundle(db, symbol_data, params, examples, errors)
                total_ingested += 1

        return total_ingested


# Convenience function for direct usage
async def extract_and_ingest_python_tree(
    source_root: Path,
    db_path: Path,
) -> int:
    """Convenience function to extract and ingest Python symbols."""
    extractor = PythonASTExtractor()
    return await extractor.extract_and_ingest_python_tree(source_root, db_path)
