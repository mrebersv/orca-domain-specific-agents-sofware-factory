# TASK BRIEF: Task 3.2 - Path B OpenAPI & CLI `--help` Spec Extractor

---

## 1. Context References
- Read `specs/ARCHITECTURE.md` (Section 2.2: `docs.db` Relational Topology).
- Read `specs/phases/phase-01-scaffolding-storage/tasks/task-1.4-docs-db-fts5-schema.md`.

---

## 2. Objective
Implement `agent_forge/spec_extractor.py` to ingest external interface definitions from OpenAPI v3 schemas (JSON/YAML) and CLI command hierarchies (via `--help` output or Click/Argparse introspection) into `docs.db`.

---

## 3. Scope & Detailed Requirements

### 3.1 OpenAPI Specification Parser (`OpenAPIExtractor`)
1. **Schema Parsing (JSON / YAML):**
   - Support OpenAPI 3.0.x and 3.1.x schema formats.
   - Resolve internal component references (`$ref: '#/components/schemas/...'`).
2. **Endpoint Mapping to `symbols` Table:**
   - `symbol_id`: `{HTTP_METHOD} {path}` (e.g., `POST /api/v1/deployments`).
   - `symbol_type`: `endpoint`.
   - `parent_scope`: Tag name, route prefix, or API version.
   - `signature`: `{METHOD} {path} -> {200/201 Response Schema Name}`.
   - `return_type`: Target JSON response schema or content type.
   - `docstring_raw`: Endpoint `summary` and `description`.
   - `is_destructive`: `True` for `DELETE`, `PATCH`, `POST`, `PUT`.
3. **Parameter & Body Extraction:**
   - Path, query, and header parameters mapped to `parameters` table (`name`, `param_type`, `is_required`, `description`, `default_value`).
   - JSON Request Body properties unpacked and inserted as parameters prefixed with `body.{field}`.
4. **Error Response Codes:**
   - Map 4xx and 5xx response specifications into `error_codes` table (`code = "HTTP 404"`, `meaning = description`, `recovery_action = "Verify identifier exists"`).

### 3.2 CLI Specification Parser (`CLIExtractor`)
1. **Command Line Introspection:**
   - Ingest Click `Group`/`Command` structures or parse formatted `--help` text streams.
   - Map subcommands to `symbol_type = 'cli_command'` with `parent_scope = root_command`.
   - Map flags/options (`--verbose`, `--output <path>`) into `parameters` table.

### 3.3 Persistence API:
- `async def extract_and_ingest_openapi(spec_path: Path, db_path: Path) -> int`
- `async def extract_and_ingest_cli_spec(command_name: str, help_text: str, db_path: Path) -> int`

---

## 4. Deliverables
- `agent_forge/spec_extractor.py`
- `tests/phase_03/test_spec_extractor.py`

---

## 5. Verification Command
```bash
python3 -c "from agent_forge.spec_extractor import OpenAPIExtractor; print('OpenAPIExtractor loaded successfully')"
```
- **Exit Condition:** Extractor imports cleanly and passes unit tests in `tests/phase_03/test_spec_extractor.py`.
