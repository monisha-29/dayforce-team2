"""Schemathesis API contract verification tests."""

import schemathesis

from app.main import app


def test_schemathesis_openapi_contract_validity() -> None:
    """Verify that the FastAPI OpenAPI schema is fully compliant with OpenAPI specification."""
    schema = schemathesis.openapi.from_dict(app.openapi())
    # Validate OpenAPI 3.x schema structure
    schema.validate()

    paths = schema.raw_schema.get("paths", {})
    required_paths = [
        "/api/v1/exceptions",
        "/api/v1/exceptions/{id}",
        "/api/v1/exceptions/{id}/proposal",
        "/api/v1/exceptions/{id}/escalate",
        "/api/v1/exceptions/{id}/audit",
        "/api/v1/proposals/{id}/decision",
        "/api/v1/audit",
        "/health",
    ]

    for p in required_paths:
        assert p in paths, f"Path '{p}' missing from OpenAPI contract"


def test_schemathesis_operations_registered() -> None:
    """Verify all operations are registered with correct HTTP methods."""
    schema = schemathesis.openapi.from_dict(app.openapi())
    ops = list(schema.get_all_operations())
    assert len(ops) >= 8

    method_path_pairs = {(op.ok().method.upper(), op.ok().path) for op in ops}
    expected = {
        ("GET", "/health"),
        ("GET", "/api/v1/exceptions"),
        ("GET", "/api/v1/exceptions/{id}"),
        ("POST", "/api/v1/exceptions/{id}/proposal"),
        ("POST", "/api/v1/exceptions/{id}/escalate"),
        ("GET", "/api/v1/exceptions/{id}/audit"),
        ("POST", "/api/v1/proposals/{id}/decision"),
        ("GET", "/api/v1/audit"),
    }
    for item in expected:
        assert item in method_path_pairs, f"Operation {item} not found in registered operations"
