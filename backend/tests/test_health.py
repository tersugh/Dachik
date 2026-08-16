from fastapi.testclient import TestClient


def test_health_returns_service_metadata(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "dachik",
        "version": "0.1.0",
    }


def test_health_allows_local_vite_origin(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
