"""
Латентность критичных эндпоинтов: время ответа не превышает порог (например 2 с).
"""
import time
import pytest

LATENCY_THRESHOLD_SEC = 2.0


@pytest.mark.performance
class TestGameLatency:
    def test_config_latency(self, game_client):
        start = time.perf_counter()
        r = game_client.get("/api/game/config")
        elapsed = time.perf_counter() - start
        assert r.status_code == 200
        assert elapsed < LATENCY_THRESHOLD_SEC, f"/api/game/config занял {elapsed:.2f} с"

    def test_state_latency(self, game_client, game_headers):
        start = time.perf_counter()
        r = game_client.get("/api/game/state", headers=game_headers)
        elapsed = time.perf_counter() - start
        assert r.status_code == 200
        assert elapsed < LATENCY_THRESHOLD_SEC, f"/api/game/state занял {elapsed:.2f} с"

    def test_checkin_latency(self, game_client, game_headers):
        start = time.perf_counter()
        r = game_client.post("/api/game/checkin", json={}, headers=game_headers)
        elapsed = time.perf_counter() - start
        assert r.status_code == 200
        assert elapsed < LATENCY_THRESHOLD_SEC, f"/api/game/checkin занял {elapsed:.2f} с"

    def test_field_latency(self, game_client, game_headers):
        start = time.perf_counter()
        r = game_client.get("/api/game/field", headers=game_headers)
        elapsed = time.perf_counter() - start
        assert r.status_code == 200
        assert elapsed < LATENCY_THRESHOLD_SEC, f"/api/game/field занял {elapsed:.2f} с"


@pytest.mark.performance
class TestTigritLatency:
    def test_map_latency(self, tigrit_client):
        start = time.perf_counter()
        r = tigrit_client.get("/api/map")
        elapsed = time.perf_counter() - start
        assert r.status_code == 200
        assert elapsed < LATENCY_THRESHOLD_SEC, f"/api/map занял {elapsed:.2f} с"
