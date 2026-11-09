"""Test OpenAPI schema generation and path completeness."""

import json
from pathlib import Path

from app.main import app


def test_openapi_generation() -> None:
    """Verify that app generates a valid OpenAPI schema matching contracts."""
    schema = app.openapi()
    assert schema["openapi"].startswith("3.")
    assert schema["info"]["title"] == "Timecard Exception Agent API"

    paths = schema["paths"]
    assert "/health" in paths
    assert "/api/v1/exceptions" in paths
    assert "/api/v1/exceptions/{id}" in paths
    assert "/api/v1/exceptions/{id}/proposal" in paths
    assert "/api/v1/exceptions/{id}/escalate" in paths
    assert "/api/v1/exceptions/{id}/audit" in paths
    assert "/api/v1/proposals/{id}/decision" in paths
    assert "/api/v1/audit" in paths

    components = schema["components"]["schemas"]
    assert "AttendanceException" in components
    assert "Proposal" in components
    assert "DecisionRequest" in components
    assert "DecisionResponse" in components
    assert "AuditEvent" in components


def test_openapi_file_exists_and_matches() -> None:
    """Verify backend/openapi.json exists on disk and is valid JSON."""
    openapi_file = Path(__file__).resolve().parent.parent / "openapi.json"
    assert openapi_file.exists(), "backend/openapi.json must exist"

    with openapi_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert data["info"]["title"] == "Timecard Exception Agent API"
    assert "/api/v1/exceptions" in data["paths"]
