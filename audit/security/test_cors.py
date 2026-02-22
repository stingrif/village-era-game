"""
CORS: при заданном CORS_ORIGINS запрос с чужого origin не должен получать
Access-Control-Allow-Origin с этим origin.
"""
import os
import pytest


@pytest.mark.security
class TestCors:
    def test_origin_not_reflected_when_not_in_whitelist(self, game_client):
        """Запрос с Origin: https://evil.com не должен вернуть Allow-Origin: https://evil.com."""
        # Если CORS_ORIGINS не задан (["*"]), то FastAPI/Starlette может вернуть * или origin.
        # Проверяем только случай, когда CORS ограничен — тогда evil origin не должен быть в ответе.
        origin = "https://evil.example.com"
        r = game_client.get(
            "/health",
            headers={"Origin": origin},
        )
        assert r.status_code == 200
        allow_origin = r.headers.get("Access-Control-Allow-Origin")
        # Если сервер настроен на конкретные origins, не должно быть Allow-Origin: evil
        if allow_origin and allow_origin != "*":
            assert allow_origin != origin, "CORS не должен отражать неразрешённый origin"
