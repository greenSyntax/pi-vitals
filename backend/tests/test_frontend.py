from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)


def test_index_is_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "Pi-Vitals" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_assets_are_served_with_sane_types():
    assert client.get("/icons/sprite.svg").headers["content-type"].startswith("image/svg+xml")
    assert client.get("/fonts/google-sans-latin.woff2").headers["content-type"] == "font/woff2"
    assert "javascript" in client.get("/js/app.js").headers["content-type"]
    assert client.get("/vendor/uplot/uPlot.iife.min.js").status_code == 200


def test_api_routes_are_not_shadowed_by_static_mount():
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/does-not-exist").status_code == 404

