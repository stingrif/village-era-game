"""
Проверка авторизации: 401 без X-Telegram-User-Id у игры; 403 у internal без X-Internal-Secret;
401/503 у Tigrit PUT /api/map без X-API-Key.
"""
import pytest


@pytest.mark.security
class TestGameAuth:
    """Эндпоинты игры требуют X-Telegram-User-Id (или сессию)."""

    def test_attempts_without_header_401(self, game_client):
        r = game_client.get("/api/game/attempts")
        assert r.status_code == 401

    def test_state_without_header_401(self, game_client):
        r = game_client.get("/api/game/state")
        assert r.status_code == 401

    def test_inventory_without_header_401(self, game_client):
        r = game_client.get("/api/game/inventory")
        assert r.status_code == 401

    def test_mine_create_without_header_401(self, game_client):
        r = game_client.post("/api/game/mine/create")
        assert r.status_code == 401

    def test_field_without_header_401(self, game_client):
        r = game_client.get("/api/game/field")
        assert r.status_code == 401


@pytest.mark.security
class TestInternalAuth:
    """Internal API требует X-Internal-Secret."""

    def test_ensure_user_without_secret_403(self, game_client):
        r = game_client.post("/internal/ensure-user", json={"telegram_id": 123})
        assert r.status_code == 403


@pytest.mark.security
class TestTigritEditorAuth:
    """PUT /api/map Tigrit требует X-API-Key."""

    def test_put_map_without_key_401_or_503(self, tigrit_client):
        r = tigrit_client.put(
            "/api/map",
            json={"width": 32, "height": 32, "tiles": []},
        )
        assert r.status_code in (401, 503)
        body = r.json()
        assert "detail" in body
