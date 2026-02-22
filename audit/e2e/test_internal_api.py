"""
E2E тесты внутреннего API: POST /internal/ensure-user.
Проверка 403 без секрета, 400 без/неверный telegram_id, 200 с секретом.
"""
import pytest


@pytest.mark.e2e
class TestInternalEnsureUser:
    """POST /internal/ensure-user."""

    def test_without_secret_returns_403(self, game_client):
        r = game_client.post("/internal/ensure-user", json={"telegram_id": 123456})
        assert r.status_code == 403
        assert "detail" in r.json() or "Forbidden" in str(r.json())

    def test_with_wrong_secret_returns_403(self, game_client):
        r = game_client.post(
            "/internal/ensure-user",
            json={"telegram_id": 123456},
            headers={"X-Internal-Secret": "wrong-secret"},
        )
        assert r.status_code == 403

    def test_without_telegram_id_returns_400(self, game_client, internal_headers):
        if not internal_headers:
            pytest.skip("INTERNAL_API_SECRET не задан")
        r = game_client.post("/internal/ensure-user", json={}, headers=internal_headers)
        assert r.status_code == 400
        assert "detail" in r.json()

    def test_telegram_id_not_integer_returns_400(self, game_client, internal_headers):
        if not internal_headers:
            pytest.skip("INTERNAL_API_SECRET не задан")
        r = game_client.post(
            "/internal/ensure-user",
            json={"telegram_id": "not-a-number"},
            headers=internal_headers,
        )
        assert r.status_code == 400

    def test_with_secret_and_telegram_id_returns_200(self, game_client, internal_headers):
        if not internal_headers:
            pytest.skip("INTERNAL_API_SECRET не задан")
        r = game_client.post(
            "/internal/ensure-user",
            json={"telegram_id": 987654321},
            headers=internal_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert "user_id" in data
        assert "telegram_id" in data
        assert data["telegram_id"] == 987654321
