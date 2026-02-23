"""
E2E тесты Tigrit API: GET /api/health, /api/village, /api/users, /api/events,
/api/events/active, /api/map, /api/assets, /api/zones, /api/admin/*;
PUT /api/map (с ключом и без); POST /api/chat/message.
"""
import os

import pytest


@pytest.mark.e2e
class TestTigritHealth:
    """Проверка эндпоинта живучести сервиса."""

    def test_get_health_returns_ok(self, tigrit_client):
        r = tigrit_client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data, "Ответ /api/health должен содержать поле 'status'"
        assert data["status"] == "ok", f"Ожидалось 'ok', получено: {data['status']!r}"


@pytest.mark.e2e
class TestTigritGetEndpoints:
    """GET-эндпоинты Tigrit."""

    def test_get_village(self, tigrit_client):
        r = tigrit_client.get("/api/village")
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            assert isinstance(r.json(), dict)

    def test_get_users(self, tigrit_client):
        r = tigrit_client.get("/api/users")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_events(self, tigrit_client):
        r = tigrit_client.get("/api/events")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_events_active(self, tigrit_client):
        r = tigrit_client.get("/api/events/active")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_map(self, tigrit_client):
        r = tigrit_client.get("/api/map")
        assert r.status_code == 200
        data = r.json()
        assert "width" in data
        assert "height" in data
        assert "tiles" in data
        assert isinstance(data["tiles"], list)

    def test_get_assets(self, tigrit_client):
        r = tigrit_client.get("/api/assets")
        assert r.status_code == 200
        data = r.json()
        assert "tiles" in data
        assert "buildings" in data
        assert "characters" in data
        assert isinstance(data["tiles"], list)
        assert isinstance(data["buildings"], list)
        assert isinstance(data["characters"], list)


@pytest.mark.e2e
class TestTigritPutMap:
    """PUT /api/map: 401/503 без ключа, 422 при невалидном body, 200 с ключом."""

    def test_put_map_without_key_returns_401_or_503(self, tigrit_client):
        body = {"width": 32, "height": 32, "tiles": [{"x": 0, "y": 0, "type": "grass", "name": "Trava"}]}
        r = tigrit_client.put("/api/map", json=body)
        assert r.status_code in (401, 503)
        assert "detail" in r.json()

    def test_put_map_with_wrong_key_returns_401_or_503(self, tigrit_client):
        """401 — если EDITOR_API_KEY задан, но ключ неверный; 503 — если ключ не настроен вообще."""
        body = {"width": 32, "height": 32, "tiles": [{"x": 0, "y": 0, "type": "grass"}]}
        r = tigrit_client.put(
            "/api/map",
            json=body,
            headers={"X-API-Key": "wrong-key", "Content-Type": "application/json"},
        )
        assert r.status_code in (401, 503)

    def test_put_map_invalid_body_returns_422(self, tigrit_client, tigrit_editor_headers):
        if not tigrit_editor_headers:
            pytest.skip("EDITOR_API_KEY не задан")
        r = tigrit_client.put(
            "/api/map",
            json={"width": -1, "height": 32, "tiles": []},
            headers=tigrit_editor_headers,
        )
        assert r.status_code == 422

    def test_put_map_valid_with_key_returns_200(self, tigrit_client, tigrit_editor_headers):
        if not tigrit_editor_headers:
            pytest.skip("EDITOR_API_KEY не задан")
        body = {
            "width": 32,
            "height": 32,
            "tiles": [
                {"x": 15, "y": 15, "type": "center", "name": "Площадь"},
                {"x": 14, "y": 13, "type": "house", "name": "Дом"},
            ],
        }
        r = tigrit_client.put("/api/map", json=body, headers=tigrit_editor_headers)
        assert r.status_code == 200
        assert r.json().get("ok") is True


@pytest.mark.e2e
class TestTigritZones:
    """GET /api/zones — всегда 200, массив с id и name."""

    def test_zones_returns_list(self, tigrit_client):
        r = tigrit_client.get("/api/zones")
        assert r.status_code == 200, f"Ожидалось 200, получено {r.status_code}: {r.text}"
        data = r.json()
        assert isinstance(data, list), "Ответ /api/zones должен быть массивом"
        assert len(data) >= 1, "Массив зон не должен быть пустым"
        for zone in data:
            assert "id" in zone, f"У зоны нет поля 'id': {zone}"
            assert "name" in zone, f"У зоны нет поля 'name': {zone}"


@pytest.mark.e2e
class TestTigritChatMessage:
    """POST /api/chat/message — 200/201 при валидных данных, не 500 при любых."""

    def test_chat_message_ok(self, tigrit_client):
        body = {"text": "e2e test message", "xp": 1, "zone_id": "zone_1"}
        r = tigrit_client.post("/api/chat/message", json=body)
        assert r.status_code in (200, 201), f"Ожидалось 200/201, получено {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("ok") is True, f"Поле 'ok' должно быть true: {data}"

    def test_chat_message_invalid_text_returns_422(self, tigrit_client):
        r = tigrit_client.post("/api/chat/message", json={"text": "", "xp": 0, "zone_id": "z"})
        assert r.status_code == 422, f"Пустой text должен давать 422: {r.status_code}"

    def test_chat_message_no_500_on_errors(self, tigrit_client):
        """При любых ошибках БД — не должно быть 500."""
        body = {"text": "stress test", "xp": 5, "zone_id": "zone_3"}
        r = tigrit_client.post("/api/chat/message", json=body)
        assert r.status_code != 500, f"500 недопустим: {r.text}"


@pytest.mark.e2e
class TestTigritAdminStatus:
    """GET /api/admin/status — 200 для всех, правильная структура."""

    def test_admin_status_no_key_returns_200(self, tigrit_client):
        """Status без ключа всё равно возвращает 200 (db_connected без ключа)."""
        r = tigrit_client.get("/api/admin/status")
        assert r.status_code == 200, f"Ожидалось 200, получено {r.status_code}: {r.text}"
        data = r.json()
        assert "admin_key_configured" in data
        assert "db_connected" in data

    def test_admin_status_with_wrong_key(self, tigrit_client):
        """С неверным ключом — key_valid: false, но ответ 200."""
        r = tigrit_client.get("/api/admin/status", headers={"X-Admin-Key": "wrong-key"})
        assert r.status_code == 200
        data = r.json()
        assert data.get("key_valid") is False

    def test_admin_status_with_correct_key(self, tigrit_client):
        """С правильным ключом — key_valid: true."""
        key = os.environ.get("TIGRIT_ADMIN_API_KEY", "")
        if not key:
            pytest.skip("TIGRIT_ADMIN_API_KEY не задан")
        r = tigrit_client.get("/api/admin/status", headers={"X-Admin-Key": key})
        assert r.status_code == 200
        data = r.json()
        assert data.get("key_valid") is True
        assert "server_time" in data

    def test_admin_village_get_not_500(self, tigrit_client):
        """GET /api/admin/village/1 с ключом — не 500 (200 или 404 или 401/503)."""
        key = os.environ.get("TIGRIT_ADMIN_API_KEY", "")
        if not key:
            pytest.skip("TIGRIT_ADMIN_API_KEY не задан")
        r = tigrit_client.get("/api/admin/village/1", headers={"X-Admin-Key": key})
        assert r.status_code in (200, 404), f"Ожидалось 200/404, получено {r.status_code}: {r.text}"

    def test_admin_village_no_key_returns_401_or_503(self, tigrit_client):
        """GET /api/admin/village/1 без ключа — 401 или 503."""
        r = tigrit_client.get("/api/admin/village/1")
        assert r.status_code in (401, 503), f"Ожидалось 401/503, получено {r.status_code}"
