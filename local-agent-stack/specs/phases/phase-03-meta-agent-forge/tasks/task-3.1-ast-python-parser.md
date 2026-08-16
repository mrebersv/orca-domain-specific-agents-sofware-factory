# TASK BRIEF: Task 3.1 - Path A Deterministic AST & Docstring Extractor

---

## 1. Context References
- Read `specs/ARCHITECTURE.md` (Section 2.2: `docs.db` Relational Topology & Symbols Schema).
- Read `specs/phases/phase-01-scaffolding-storage/tasks/task-1.4-docs-db-fts5-schema.md`.

---

## 2. Objective
Implement `agent_forge/ast_extractor.py` to deterministically parse Python source trees using Python's standard `ast` module and `docstring-parser`. The extractor extracts functions, classes, methods, type annotations, default parameters, docstrings, code examples, and raised exceptions, persisting all records directly into `docs.db`.

---

## 3. Scope & Detailed Requirements

### 3.1 AST Ingestion Engine (`agent_forge/ast_extractor.py`)
1. **Module Visitor (`PythonASTExtractor`):**
   - Recursively traverse directory paths or parse individual `.py` files.
   - Ignore standard noise directories (`.git`, `.venv`, `__pycache__`, `tests`, `build`, `dist`).
   - Parse code using `ast.parse(source_code, filename=file_path)`.
2. **Symbol Extraction Logic:**
   - **Functions & Methods:**
     - Extract `symbol_id`: `{module_path}.{class_name}.{function_name}` or `{module_path}.{function_name}`.
     - Extract `symbol_type`: `function` or `method`.
     - Extract `parent_scope`: Module name or Class name.
     - Extract `signature`: Full typed string representation (e.g., `async def get_unit(unit_id: str, timeout: float = 5.0) -> UnitModel:`).
     - Extract `return_type`: Return annotation string or `None`.
     - Extract `is_destructive`: Flag `True` if name starts with or contains mutating keywords (`delete`, `remove`, `drop`, `purge`, `destroy`, `update`, `set`, `write`).
   - **Classes:**
     - Extract `symbol_id`: `{module_path}.{class_name}`.
     - Extract `symbol_type`: `class`.
     - Extract docstring and base classes.
3. **Parameter Schema Extraction:**
   - Extract every positional, keyword-only, and default parameter into `parameters` table.
   - Map AST type annotations (e.g., `ast.unparse(arg.annotation)`) to `param_type`.
   - Map AST default values to string representation in `default_value`.
   - Set `is_required = True` if parameter has no default value and is not `*args`/`**kwargs`.
4. **Docstring & Example Parsing:**
   - Parse docstrings using `docstring_parser.parse(ast.get_docstring(node))`.
   - Extract parameter descriptions to populate `parameters.description`.
   - Extract code blocks / doctests from docstrings and insert into `examples` table with `source_origin = 'extracted_docstring'`.
   - Extract raised exceptions (`docstring.raises`) and insert into `error_codes` table with `code = exception.type_name` and `meaning = exception.description`.
5. **Database Persistence:**
   - `async def extract_and_ingest_python_tree(source_root: Path, db_path: Path) -> int`:
     - Inserts all extracted records inside an async transaction using `agent_forge.db.docs.get_docs_db`.
     - Returns total count of ingested symbols.

---

## 4. Deliverables
- `agent_forge/ast_extractor.py`
- `tests/phase_03/test_ast_extractor.py`

---

## 5. Verification Command
```bash
python3 -c "import asyncio; from agent_forge.ast_extractor import PythonASTExtractor; from pathlib import Path; extractor = PythonASTExtractor(); symbols = extractor.parse_file(Path('agent_forge/db/docs.py')); print(f'Parsed {len(symbols)} symbols from docs.py')"
```
- **Exit Condition:** Successfully parses `agent_forge/db/docs.py` and returns extracted symbol count without raising exceptions.
