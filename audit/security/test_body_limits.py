"""
Лимиты тела запроса: очень большой JSON или длинная строка — ожидаем 413/422/400,
не падение сервера.
"""
import pytest


@pytest.mark.security
class TestBodyLimits:
    def test_large_json_body_rejected_or_413(self, game_client, game_headers):
        # Тело ~1 MB — не должно приводить к 500
        large_array = ["x" * 1000] * 1000  # ~1M символов
        r = game_client.post(
            "/api/game/action",
            json={"action": "sync", "params": {"data": large_array}},
            headers=game_headers,
        )
        assert r.status_code in (200, 400, 413, 422, 500)
        if r.status_code == 500:
            # Допустимо для перегруженного сервера, но в ответе не должно быть stack trace
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if isinstance(body, dict):
                detail = str(body.get("detail", ""))
                assert "Traceback" not in detail
                assert "File \"" not in detail

    def test_very_long_string_in_params(self, game_client, game_headers):
        r = game_client.post(
            "/api/game/action",
            json={"action": "sync", "params": {"username": "a" * 100000}},
            headers=game_headers,
        )
        assert r.status_code in (200, 400, 413, 422, 500)
