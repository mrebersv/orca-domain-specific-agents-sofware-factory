"""Tests for Phase 3 Task 3.1 - Python AST & Docstring Extractor."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
import pytest

from agent_forge.ast_extractor import PythonASTExtractor, extract_and_ingest_python_tree
from agent_forge.db.docs import init_docs_db, get_docs_db, query_symbols_fts


SAMPLE_PYTHON_CODE = """
\"\"\"Module docstring.\"\"\"

from typing import Optional, List

class SampleClass:
    \"\"\"A sample class for testing.\"\"\"

    def __init__(self, name: str, value: int = 42) -> None:
        \"\"\"Initialize the class.

        Args:
            name: The name of the instance.
            value: An optional value.
        \"\"\"
        self.name = name
        self.value = value

    def compute(self, multiplier: float = 2.0) -> float:
        \"\"\"Compute a value.

        Args:
            multiplier: The multiplier to apply.

        Returns:
            The computed result.

        Raises:
            ValueError: If multiplier is negative.

        Example:
obj = SampleClass(\"test\")
obj.compute(3.0)
            126.0
        \"\"\"
        if multiplier < 0:
            raise ValueError(\"Multiplier must be positive\")
        return self.value * multiplier

    def delete_item(self, item_id: str) -> bool:
        \"\"\"Delete an item.

        Args:
            item_id: ID of item to delete.

        Returns:
            True if deleted.
        \"\"\"
        return True

async def async_function(param: str, timeout: float = 5.0) -> dict:
    \"\"\"An async function.

    Args:
        param: Input parameter.
        timeout: Timeout in seconds.

    Returns:
        Result dictionary.
    \"\"\"
    return {\"param\": param, \"timeout\": timeout}

def standalone_function(x: int, y: Optional[str] = None) -> List[int]:
    \"\"\"A standalone function.

    Args:
        x: An integer.
        y: Optional string.

    Returns:
        List of integers.
    \"\"\"
    return [x, len(y) if y else 0]
"""

SAMPLE_DOCSTRING_CODE = """
\"\"\"Module with various docstring formats.\"\"\"

def google_style(param1: int, param2: str = \"default\") -> bool:
    \"\"\"Google style docstring.

    Args:
        param1: First parameter description.
        param2: Second parameter description.

    Returns:
        Boolean result.

    Raises:
        TypeError: If param1 is not an integer.
    \"\"\"
    return True

def numpy_style(param1, param2):
    \"\"\"NumPy style docstring.

    Parameters
    ----------
    param1 : int
        First parameter.
    param2 : str
        Second parameter.

    Returns
    -------
    bool
        Result.
    \"\"\"
    return True
"""

class TestPythonASTExtractor:
    """Tests for PythonASTExtractor class."""

    def test_parse_file_basic(self):
        """Test parsing a basic Python file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            symbols = extractor.parse_file(temp_path)

            assert len(symbols) >= 6

            class_symbols = [s for s in symbols if s["symbol_type"] == "class"]
            assert len(class_symbols) == 1
            assert class_symbols[0]["symbol_id"].endswith(".SampleClass")

            method_symbols = [s for s in symbols if s["symbol_type"] == "method"]
            assert len(method_symbols) >= 3

            function_symbols = [s for s in symbols if s["symbol_type"] == "function"]
            assert len(function_symbols) >= 2

        finally:
            temp_path.unlink()

    def test_extract_function_signature(self):
        """Test function signature extraction with types and defaults."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            symbols = extractor.parse_file(temp_path)

            compute = next(s for s in symbols if s["symbol_id"].endswith(".compute"))
            assert "multiplier: float = 2.0" in compute["signature"]
            assert "-> float" in compute["signature"]
            assert compute["return_type"] == "float"

            standalone = next(s for s in symbols if s["symbol_id"].endswith(".standalone_function"))
            assert "x: int" in standalone["signature"]
            assert "y: Optional[str] = None" in standalone["signature"]
            assert "-> List[int]" in standalone["signature"]

        finally:
            temp_path.unlink()

    def test_extract_parameters(self):
        """Test parameter extraction with types, defaults, and descriptions."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            symbols = extractor.parse_file(temp_path)

            compute = next(s for s in symbols if s["symbol_id"].endswith(".compute"))
            params = compute.get("parameters", [])

            param_names = [p["name"] for p in params]
            assert "self" in param_names
            assert "multiplier" in param_names

            multiplier_param = next(p for p in params if p["name"] == "multiplier")
            assert multiplier_param["param_type"] == "float"
            assert multiplier_param["default_value"] == "2.0"
            assert multiplier_param["is_required"] is False
            assert "multiplier" in multiplier_param.get("description", "").lower()

        finally:
            temp_path.unlink()

    def test_extract_docstring_examples(self):
        """Test extraction of code examples from docstrings."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            symbols = extractor.parse_file(temp_path)

            compute = next(s for s in symbols if s["symbol_id"].endswith(".compute"))
            examples = compute.get("examples", [])

            assert len(examples) >= 1
            example = examples[0]
            assert "code_snippet" in example
            assert "SampleClass" in example["code_snippet"]
            assert example["source_origin"] == "extracted_docstring"

        finally:
            temp_path.unlink()

    def test_extract_error_codes(self):
        """Test extraction of raised exceptions from docstrings."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            symbols = extractor.parse_file(temp_path)

            compute = next(s for s in symbols if s["symbol_id"].endswith(".compute"))
            errors = compute.get("error_codes", [])

            assert len(errors) >= 1
            error = errors[0]
            assert error["code"] == "ValueError"
            assert "negative" in error["meaning"].lower()

        finally:
            temp_path.unlink()

    def test_destructive_flag(self):
        """Test destructive flag detection."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            symbols = extractor.parse_file(temp_path)

            delete_method = next(s for s in symbols if s["symbol_id"].endswith(".delete_item"))
            assert delete_method["is_destructive"] is True

            compute = next(s for s in symbols if s["symbol_id"].endswith(".compute"))
            assert compute["is_destructive"] is False

        finally:
            temp_path.unlink()

    def test_async_function(self):
        """Test async function extraction."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            symbols = extractor.parse_file(temp_path)

            async_func = next(s for s in symbols if s["symbol_id"].endswith(".async_function"))
            assert "async def" in async_func["signature"]
            assert async_func["symbol_type"] == "function"

        finally:
            temp_path.unlink()

    def test_parse_directory(self):
        """Test parsing a directory of Python files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            (tmp_path / "module1.py").write_text("def func1(): pass")
            (tmp_path / "module2.py").write_text("def func2(): pass")

            ignored = tmp_path / "tests"
            ignored.mkdir()
            (ignored / "test_module.py").write_text("def test_func(): pass")

            extractor = PythonASTExtractor()
            symbols = extractor.parse_directory(tmp_path)

            assert len(symbols) == 2
            symbol_ids = [s["symbol_id"] for s in symbols]
            assert any("module1.func1" in sid for sid in symbol_ids)
            assert any("module2.func2" in sid for sid in symbol_ids)

    def test_ignore_directories(self):
        """Test that standard noise directories are ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            (tmp_path / "main.py").write_text("def main(): pass")
            (tmp_path / "__pycache__").mkdir()
            (tmp_path / "__pycache__" / "cached.py").write_text("def cached(): pass")
            (tmp_path / ".git").mkdir()
            (tmp_path / ".git" / "config").write_text("")

            extractor = PythonASTExtractor()
            symbols = extractor.parse_directory(tmp_path)

            assert len(symbols) == 1
            assert symbols[0]["symbol_id"].endswith(".main")


class TestASTExtractorIntegration:
    """Integration tests with docs.db."""

    @pytest.mark.asyncio
    async def test_extract_and_ingest_python_tree(self):
        """Test full extraction and ingestion pipeline."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(SAMPLE_PYTHON_CODE)
            temp_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        try:
            await init_docs_db(db_path)
            count = await extract_and_ingest_python_tree(temp_path, db_path)

            assert count >= 6

            async with get_docs_db(db_path, read_only=True) as db:
                async with db.execute("SELECT COUNT(*) FROM symbols") as cursor:
                    row = await cursor.fetchone()
                    assert row[0] >= 6

                async with db.execute("SELECT COUNT(*) FROM parameters") as cursor:
                    row = await cursor.fetchone()
                    assert row[0] > 0

                async with db.execute("SELECT COUNT(*) FROM examples") as cursor:
                    row = await cursor.fetchone()
                    assert row[0] > 0

                async with db.execute("SELECT COUNT(*) FROM error_codes") as cursor:
                    row = await cursor.fetchone()
                    assert row[0] > 0

                results = await query_symbols_fts(db, "compute")
                assert len(results) >= 1
                assert any("compute" in r["symbol_id"] for r in results)

        finally:
            temp_path.unlink()
            db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_fts5_triggers(self):
        """Test that FTS5 triggers auto-sync on insert/update/delete."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write("def test_func(): pass")
            temp_path = Path(tf.name)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_f:
            db_path = Path(db_f.name)

        try:
            await init_docs_db(db_path)
            await extract_and_ingest_python_tree(temp_path, db_path)

            async with get_docs_db(db_path, read_only=True) as db:
                results = await query_symbols_fts(db, "test_func")
                assert len(results) == 1

                async with db.execute("SELECT COUNT(*) FROM symbols_fts") as cursor:
                    row = await cursor.fetchone()
                    assert row[0] >= 1

        finally:
            temp_path.unlink()
            db_path.unlink(missing_ok=True)


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_syntax_error_handling(self):
        """Test handling of syntax errors in source files."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write("def invalid_syntax(:\n    pass")
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            with pytest.raises(ValueError, match="Syntax error"):
                extractor.parse_file(temp_path)
        finally:
            temp_path.unlink()

    def test_empty_file(self):
        """Test parsing an empty file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write("")
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            symbols = extractor.parse_file(temp_path)
            assert len(symbols) == 0
        finally:
            temp_path.unlink()

    def test_class_with_no_methods(self):
        """Test class with no methods."""
        code = "class EmptyClass: pass"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(code)
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            symbols = extractor.parse_file(temp_path)

            class_symbols = [s for s in symbols if s["symbol_type"] == "class"]
            assert len(class_symbols) == 1
            assert class_symbols[0]["symbol_id"].endswith(".EmptyClass")
        finally:
            temp_path.unlink()

    def test_nested_classes(self):
        """Test nested class extraction."""
        code = """
class Outer:
    class Inner:
        def method(self): pass
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(code)
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            symbols = extractor.parse_file(temp_path)

            class_symbols = [s for s in symbols if s["symbol_type"] == "class"]
            assert len(class_symbols) == 2
        finally:
            temp_path.unlink()

    def test_complex_type_annotations(self):
        """Test complex type annotations."""
        code = (
            "from typing import Dict, List, Optional, Union, Callable\n"
            "\n"
            "def complex_func(\n"
            "    data: Dict[str, List[int]], "
            "callback: Callable[[int], str],\n"
            "    optional: Optional[Union[int, float]] = None\n"
            ") -> List[str]:\n"
            "    pass\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tf:
            tf.write(code)
            temp_path = Path(tf.name)

        try:
            extractor = PythonASTExtractor()
            symbols = extractor.parse_file(temp_path)

            func = symbols[0]
            assert "Dict[str, List[int]]" in func["signature"]
            assert "Callable[[int], str]" in func["signature"]
            assert "Optional[Union[int, float]]" in func["signature"]
            assert func["return_type"] == "List[str]"
        finally:
            temp_path.unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
