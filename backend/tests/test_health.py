"""Test health check endpoint."""

from app.main import app, health_check


def test_health_check_function() -> None:
    """Verify health_check function returns status ok."""
    result = health_check()
    assert result == {"status": "ok"}


def test_health_route_registered() -> None:
    """Verify /health route is registered on application."""
    routes = [getattr(route, "path", None) for route in app.routes]
    assert "/health" in routes
