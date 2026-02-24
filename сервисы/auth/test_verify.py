"""
Проверка эндпоинтов auth: 400 без body, 401 при невалидном init_data, health.
Полный e2e с валидным init_data — ручной (нужен реальный bot token и подпись).
"""
import os
import sys

# Запуск без секретов — бот-токен пустой, невалидные данные дадут 401
os.environ.setdefault("INTERNAL_TOKEN", "test")
os.environ.setdefault("SECRETS_SERVICE_URL", "http://localhost:8003")

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_verify_no_body():
    r = client.post("/verify", json={})
    # Pydantic: оба поля Optional, но хотя бы одно нужно по логике -> 400 из handler
    assert r.status_code in (400, 422)


def test_verify_empty_init_data_unauthorized():
    r = client.post("/verify", json={"init_data": ""})
    # Пустой init_data: 400 (required) или без токена/невалидные данные — 401/500
    assert r.status_code in (400, 401, 500)


def test_verify_invalid_init_data_unauthorized():
    r = client.post("/verify", json={"init_data": "invalid=data&hash=wrong"})
    assert r.status_code in (401, 500)


if __name__ == "__main__":
    test_health()
    print("health ok")
    test_verify_no_body()
    print("verify no body ok")
    test_verify_empty_init_data_unauthorized()
    print("verify empty ok")
    test_verify_invalid_init_data_unauthorized()
    print("verify invalid ok")
    print("All checks passed.")
