"""
E2E тесты Tigrit API: GET /api/health, /api/village, /api/users, /api/events,
/api/events/active, /api/map, /api/assets; PUT /api/map (с ключом и без).
"""
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
