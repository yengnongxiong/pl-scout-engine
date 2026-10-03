from fastapi import APIRouter
from fastapi.testclient import TestClient

from scout import __version__
from scout.api.main import create_app
from scout.errors import NotFoundError


def test_health() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__, "warehouse_version": None}


def test_scout_errors_use_the_error_schema() -> None:
    app = create_app()
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise NotFoundError("no such player", details={"player_id": 7})

    app.include_router(router)
    resp = TestClient(app).get("/boom")
    assert resp.status_code == 404
    assert resp.json() == {
        "error": {"code": "not_found", "message": "no such player", "details": {"player_id": 7}}
    }


def test_cors_allows_only_vite_dev_origin() -> None:
    client = TestClient(create_app())
    ok = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_openapi_docs_render() -> None:
    client = TestClient(create_app())
    assert client.get("/docs").status_code == 200
    schema = client.get("/openapi.json").json()
    assert "/health" in schema["paths"]
    assert "ErrorResponse" in schema["components"]["schemas"]
