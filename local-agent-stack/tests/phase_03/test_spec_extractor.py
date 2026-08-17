"""Tests for Phase 3 Task 3.2 - OpenAPI & CLI Spec Extractor."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
import pytest

from agent_forge.spec_extractor import OpenAPIExtractor, CLIExtractor, extract_and_ingest_openapi, extract_and_ingest_cli_spec
from agent_forge.db.docs import init_docs_db, get_docs_db, query_symbols_fts


SAMPLE_OPENAPI_V3 = {
    "openapi": "3.0.3",
    "info": {
        "title": "Test API",
        "version": "1.0.0",
        "description": "A test API for unit testing"
    },
    "servers": [{"url": "https://api.example.com/v1"}],
    "paths": {
        "/users": {
            "get": {
                "summary": "List users",
                "description": "Retrieve a paginated list of users",
                "tags": ["users"],
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}, "description": "Page number"},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 10}, "description": "Items per page"}
                ],
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "users": {"type": "array", "items": {"$ref": "#/components/schemas/User"}},
                                        "total": {"type": "integer"}
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "post": {
                "summary": "Create user",
                "description": "Create a new user account",
                "tags": ["users"],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/UserCreate"}
                        }
                    }
                },
                "responses": {
                    "201": {
                        "description": "User created",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/User"}}}
                    },
                    "400": {"description": "Invalid input"}
                }
            }
        },
        "/users/{user_id}": {
            "get": {
                "summary": "Get user",
                "description": "Retrieve a single user by ID",
                "tags": ["users"],
                "parameters": [
                    {"name": "user_id", "in": "path", "required": True, "schema": {"type": "string"}, "description": "User ID"}
                ],
                "responses": {
                    "200": {"description": "User found", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/User"}}}},
                    "404": {"description": "User not found"}
                }
            },
            "delete": {
                "summary": "Delete user",
                "description": "Permanently delete a user account",
                "tags": ["users"],
                "parameters": [
                    {"name": "user_id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {
                    "204": {"description": "User deleted"},
                    "404": {"description": "User not found"}
                }
            }
        }
    },
    "components": {
        "schemas": {
            "User": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "email": {"type": "string", "format": "email"},
                    "created_at": {"type": "string", "format": "date-time"}
                },
                "required": ["id", "name", "email"]
            },
            "UserCreate": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string", "format": "email"}
                },
                "required": ["name", "email"]
            }
        }
    }
}

SAMPLE_CLI_HELP = """Usage: mytool [OPTIONS] COMMAND [ARGS]...

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  create     Create a new resource
  delete     Delete a resource
  list       List all resources
  update     Update an existing resource
"""

class TestOpenAPIExtractor:
    """Tests for OpenAPIExtractor class."""

    def test_load_json_spec(self):
        """Test loading OpenAPI spec from JSON file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_OPENAPI_V3, f)
            temp_path = Path(f.name)

        try:
            extractor = OpenAPIExtractor()
            spec = extractor._load_spec(temp_path)
            assert spec["info"]["title"] == "Test API"
            assert "paths" in spec
        finally:
            temp_path.unlink()

    def test_load_yaml_spec(self):
        """Test loading OpenAPI spec from YAML file."""
        import yaml
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(SAMPLE_OPENAPI_V3, f)
            temp_path = Path(f.name)

        try:
            extractor = OpenAPIExtractor()
            spec = extractor._load_spec(temp_path)
            assert spec["info"]["title"] == "Test API"
        finally:
            temp_path.unlink()

    def test_extract_endpoints(self):
        """Test endpoint extraction from OpenAPI spec."""
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(SAMPLE_OPENAPI_V3)

        # Should extract 5 endpoints: GET/POST /users, GET/DELETE /users/{user_id}
        assert len(symbols) == 4

        # Check symbol structure
        for sym in symbols:
            assert sym["symbol_type"] == "endpoint"
            assert "symbol_id" in sym
            assert "signature" in sym
            assert "parent_scope" in sym
            assert "parameters" in sym
            assert "error_codes" in sym

    def test_endpoint_symbol_ids(self):
        """Test that endpoint symbol IDs follow HTTP_METHOD PATH format."""
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(SAMPLE_OPENAPI_V3)

        symbol_ids = {s["symbol_id"] for s in symbols}
        assert "GET /users" in symbol_ids
        assert "POST /users" in symbol_ids
        assert "GET /users/{user_id}" in symbol_ids
        assert "DELETE /users/{user_id}" in symbol_ids

    def test_path_parameters(self):
        """Test path parameter extraction."""
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(SAMPLE_OPENAPI_V3)

        # Find GET /users/{user_id}
        get_user = next(s for s in symbols if s["symbol_id"] == "GET /users/{user_id}")
        params = get_user["parameters"]

        param_names = {p["name"] for p in params}
        assert "user_id" in param_names

        user_id_param = next(p for p in params if p["name"] == "user_id")
        assert user_id_param["is_required"] is True
        assert user_id_param["param_type"] == "string"

    def test_query_parameters(self):
        """Test query parameter extraction with defaults."""
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(SAMPLE_OPENAPI_V3)

        list_users = next(s for s in symbols if s["symbol_id"] == "GET /users")
        params = list_users["parameters"]

        param_names = {p["name"] for p in params}
        assert "page" in param_names
        assert "limit" in param_names

        page_param = next(p for p in params if p["name"] == "page")
        assert page_param["is_required"] is False
        assert page_param["default_value"] == "1"

    def test_request_body_parameters(self):
        """Test request body property extraction."""
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(SAMPLE_OPENAPI_V3)

        create_user = next(s for s in symbols if s["symbol_id"] == "POST /users")
        params = create_user["parameters"]

        # Should have body.name and body.email
        param_names = {p["name"] for p in params}
        assert "body.name" in param_names
        assert "body.email" in param_names

        name_param = next(p for p in params if p["name"] == "body.name")
        assert name_param["is_required"] is True

    def test_error_codes_extraction(self):
        """Test HTTP error code extraction."""
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(SAMPLE_OPENAPI_V3)

        get_user = next(s for s in symbols if s["symbol_id"] == "GET /users/{user_id}")
        errors = get_user["error_codes"]

        error_codes = {e["code"] for e in errors}
        assert "HTTP 404" in error_codes

        # Check error structure
        error_404 = next(e for e in errors if e["code"] == "HTTP 404")
        assert "not found" in error_404["meaning"].lower()
        assert error_404["recovery_action"] is not None

    def test_destructive_flag(self):
        """Test destructive flag for mutating HTTP methods."""
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(SAMPLE_OPENAPI_V3)

        # GET should not be destructive
        get_user = next(s for s in symbols if s["symbol_id"] == "GET /users/{user_id}")
        assert get_user["is_destructive"] is False

        # POST, DELETE should be destructive
        post_users = next(s for s in symbols if s["symbol_id"] == "POST /users")
        assert post_users["is_destructive"] is True

        delete_user = next(s for s in symbols if s["symbol_id"] == "DELETE /users/{user_id}")
        assert delete_user["is_destructive"] is True

    def test_parent_scope_from_tags(self):
        """Test parent_scope extraction from operation tags."""
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(SAMPLE_OPENAPI_V3)

        for sym in symbols:
            assert sym["parent_scope"] == "users"

    def test_resolve_refs(self):
        """Test internal $ref resolution."""
        extractor = OpenAPIExtractor()

        # Test direct ref
        ref_schema = {"$ref": "#/components/schemas/User"}
        resolved = extractor._resolve_ref(SAMPLE_OPENAPI_V3, ref_schema["$ref"])
        assert resolved["type"] == "object"
        assert "id" in resolved["properties"]

    def test_schema_type_extraction(self):
        """Test JSON schema type extraction."""
        extractor = OpenAPIExtractor()

        # Simple type
        assert extractor._get_schema_type({"type": "string"}) == "string"
        assert extractor._get_schema_type({"type": "integer"}) == "integer"

        # Array type
        assert extractor._get_schema_type({"type": "array", "items": {"type": "string"}}) == "array[string]"

        # Ref type
        assert extractor._get_schema_type({"$ref": "#/components/schemas/User"}) == "User"

        # anyOf
        any_of = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        assert "string" in extractor._get_schema_type(any_of)


class TestCLIExtractor:
    """Tests for CLIExtractor class."""

    def test_parse_help_text(self):
        """Test parsing CLI help text."""
        extractor = CLIExtractor()
        symbols = extractor._parse_help_text(SAMPLE_CLI_HELP, "mytool")

        # Should extract 4 commands
        assert len(symbols) == 4

        for sym in symbols:
            assert sym["symbol_type"] == "cli_command"
            assert sym["parent_scope"] == "mytool"
            assert sym["symbol_id"].startswith("cli.mytool.")

    def test_command_symbol_ids(self):
        """Test CLI command symbol IDs."""
        extractor = CLIExtractor()
        symbols = extractor._parse_help_text(SAMPLE_CLI_HELP, "mytool")

        symbol_ids = {s["symbol_id"] for s in symbols}
        assert "cli.mytool.create" in symbol_ids
        assert "cli.mytool.delete" in symbol_ids
        assert "cli.mytool.list" in symbol_ids
        assert "cli.mytool.update" in symbol_ids

    def test_signature_extraction(self):
        """Test command signature extraction."""
        extractor = CLIExtractor()
        symbols = extractor._parse_help_text(SAMPLE_CLI_HELP, "mytool")

        create_cmd = next(s for s in symbols if s["symbol_id"] == "cli.mytool.create")
        assert "mytool create" in create_cmd["signature"]

    def test_flag_extraction(self):
        """Test flag/option extraction from usage."""
        help_with_flags = """Usage: mytool [OPTIONS] COMMAND

Options:
  --verbose  Enable verbose output
  --output FILE  Output file path
  --count INTEGER  Number of items
"""
        extractor = CLIExtractor()
        symbols = extractor._parse_help_text(help_with_flags, "mytool")

        # Should have at least one command with flags
        for sym in symbols:
            params = sym["parameters"]
            param_names = {p["name"] for p in params}
            # Flags should be extracted
            assert any(name.startswith("--") for name in param_names)

    def test_destructive_cli_commands(self):
        """Test destructive flag for CLI commands."""
        extractor = CLIExtractor()
        symbols = extractor._parse_help_text(SAMPLE_CLI_HELP, "mytool")

        delete_cmd = next(s for s in symbols if s["symbol_id"] == "cli.mytool.delete")
        assert delete_cmd["is_destructive"] is True

        create_cmd = next(s for s in symbols if s["symbol_id"] == "cli.mytool.create")
        assert create_cmd["is_destructive"] is False


class TestSpecExtractorIntegration:
    """Integration tests with docs.db."""

    @pytest.mark.asyncio
    async def test_extract_and_ingest_openapi(self):
        """Test full OpenAPI extraction and ingestion pipeline."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(SAMPLE_OPENAPI_V3, f)
            spec_path = Path(f.name)

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as db_f:
            db_path = Path(db_f.name)

        try:
            await init_docs_db(db_path)
            count = await extract_and_ingest_openapi(spec_path, db_path)

            assert count == 4  # 4 endpoints

            # Verify in database
            async with get_docs_db(db_path, read_only=True) as db:
                async with db.execute("SELECT COUNT(*) FROM symbols WHERE symbol_type = 'endpoint'") as cursor:
                    row = await cursor.fetchone()
                    assert row[0] == 4

                # Check parameters
                async with db.execute("SELECT COUNT(*) FROM parameters") as cursor:
                    row = await cursor.fetchone()
                    assert row[0] > 0

                # Check error codes
                async with db.execute("SELECT COUNT(*) FROM error_codes") as cursor:
                    row = await cursor.fetchone()
                    assert row[0] > 0

                # Test FTS search
                results = await query_symbols_fts(db, "user")
                assert len(results) >= 1

        finally:
            spec_path.unlink()
            db_path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_extract_and_ingest_cli_spec(self):
        """Test CLI spec extraction and ingestion."""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as db_f:
            db_path = Path(db_f.name)

        try:
            await init_docs_db(db_path)
            count = await extract_and_ingest_cli_spec("mytool", SAMPLE_CLI_HELP, db_path)

            assert count >= 1

            async with get_docs_db(db_path, read_only=True) as db:
                async with db.execute("SELECT COUNT(*) FROM symbols WHERE symbol_type = 'cli_command'") as cursor:
                    row = await cursor.fetchone()
                    assert row[0] >= 1

        finally:
            db_path.unlink(missing_ok=True)


class TestOpenAPIEdgeCases:
    """Tests for OpenAPI edge cases."""

    def test_openapi_without_components(self):
        """Test OpenAPI spec without components section."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/simple": {
                    "get": {
                        "summary": "Simple endpoint",
                        "responses": {"200": {"description": "OK"}}
                    }
                }
            }
        }
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(spec)
        assert len(symbols) == 1

    def test_openapi_with_ref_in_parameters(self):
        """Test parameter with $ref."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "parameters": [{"$ref": "#/components/parameters/PageParam"}],
                        "responses": {"200": {"description": "OK"}}
                    }
                }
            },
            "components": {
                "parameters": {
                    "PageParam": {"name": "page", "in": "query", "schema": {"type": "integer"}}
                }
            }
        }
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(spec)
        assert len(symbols) == 1
        params = symbols[0]["parameters"]
        assert any(p["name"] == "page" for p in params)

    def test_openapi_multiple_tags(self):
        """Test operation with multiple tags."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "tags": ["tag1", "tag2"],
                        "responses": {"200": {"description": "OK"}}
                    }
                }
            }
        }
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(spec)
        assert symbols[0]["parent_scope"] == "tag1"  # First tag used

    def test_openapi_no_tags(self):
        """Test operation without tags."""
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/test": {
                    "get": {
                        "responses": {"200": {"description": "OK"}}
                    }
                }
            }
        }
        extractor = OpenAPIExtractor()
        symbols = extractor.extract_from_spec(spec)
        assert symbols[0]["parent_scope"] == "default"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
