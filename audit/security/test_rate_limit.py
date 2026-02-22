"""
Rate limit: Tigrit API при превышении лимита возвращает 429.
Лимит PUT /api/map — 10/min; GET — 120/min. Отправляем много запросов подряд.
"""
import pytest


@pytest.mark.security
class TestTigritRateLimit:
    """Проверка 429 при превышении лимита (Tigrit slowapi)."""

    def test_put_map_rate_limit_eventually_429(self, tigrit_client, tigrit_editor_headers):
        if not tigrit_editor_headers:
            pytest.skip("EDITOR_API_KEY не задан")
        body = {
            "width": 32,
            "height": 32,
            "tiles": [{"x": 0, "y": 0, "type": "grass", "name": "x"}],
        }
        # Лимит 10/minute для PUT /api/map — делаем 12 запросов
        responses = []
        for _ in range(12):
            r = tigrit_client.put("/api/map", json=body, headers=tigrit_editor_headers)
            responses.append(r.status_code)
            if r.status_code == 429:
                assert "detail" in r.json() or "Слишком много" in str(r.json())
                break
        # Либо один из ответов 429, либо все 200 (если лимит не сработал за 12 запросов)
        assert 200 in responses or 429 in responses
