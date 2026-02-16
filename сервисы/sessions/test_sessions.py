"""
Проверка эндпоинтов sessions: create, validate, refresh, invalidate.
Требует Redis (REDIS_URL). Запуск: python test_sessions.py или pytest test_sessions.py -v
"""
import os
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    # 503 если Redis недоступен
    assert r.status_code in (200, 503)


def test_create_validate_refresh_invalidate():
    r = client.post("/session", json={"user_id": 42})
    if r.status_code != 200:
        raise AssertionError(f"create failed: {r.status_code} {r.text}")
    data = r.json()
    session_id = data["session_id"]
    expires_at = data["expires_at"]
    assert session_id and expires_at > 0

    r = client.get("/session/validate", params={"session_id": session_id})
    assert r.status_code == 200
    assert r.json() == {"valid": True, "user_id": 42}

    r = client.post("/session/refresh", json={"session_id": session_id})
    assert r.status_code == 200
    assert "expires_at" in r.json()

    r = client.post("/session/invalidate", json={"session_id": session_id})
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    r = client.get("/session/validate", params={"session_id": session_id})
    assert r.status_code == 200
    assert r.json() == {"valid": False}


def test_validate_missing_param():
    r = client.get("/session/validate")
    assert r.status_code in (400, 422)  # session_id required


if __name__ == "__main__":
    test_health()
    print("health ok")
    test_create_validate_refresh_invalidate()
    print("create/validate/refresh/invalidate ok")
    test_validate_missing_param()
    print("All passed.")
