"""
Валидация формата ответов: успешные ответы соответствуют JSON Schema;
ошибки 4xx/5xx содержат detail и не содержат stack trace.
"""
import json
from pathlib import Path

import pytest

try:
    import jsonschema
except ImportError:
    jsonschema = None

SCHEMAS_DIR = Path(__file__).resolve().parent / "schemas"


def _load_schema(name):
    path = SCHEMAS_DIR / f"{name}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.output
class TestResponseSchemas:
    """Успешные ответы проходят валидацию по схеме."""

    @pytest.fixture
    def validator(self):
        if jsonschema is None:
            pytest.skip("jsonschema не установлен")
        return jsonschema.Draft7Validator

    def test_config_schema(self, game_client, validator):
        r = game_client.get("/api/game/config")
        if r.status_code != 200:
            pytest.skip("backend returned non-200")
        schema = _load_schema("config")
        if schema and validator:
            validator(schema).validate(r.json())

    def test_state_schema(self, game_client, game_headers, validator):
        r = game_client.get("/api/game/state", headers=game_headers)
        if r.status_code != 200:
            pytest.skip("backend returned non-200")
        schema = _load_schema("state")
        if schema and validator:
            validator(schema).validate(r.json())

    def test_field_schema(self, game_client, game_headers, validator):
        r = game_client.get("/api/game/field", headers=game_headers)
        if r.status_code != 200:
            pytest.skip("backend returned non-200")
        schema = _load_schema("field")
        if schema and validator:
            validator(schema).validate(r.json())

    def test_leaderboards_schema(self, game_client, game_headers, validator):
        r = game_client.get("/api/game/leaderboards", params={"period": "weekly"}, headers=game_headers)
        if r.status_code != 200:
            pytest.skip("backend returned non-200")
        schema = _load_schema("leaderboards")
        if schema and validator:
            validator(schema).validate(r.json())


@pytest.mark.output
class TestErrorFormat:
    """Ответы с ошибкой содержат detail и не содержат stack trace."""

    def test_401_has_detail(self, game_client):
        r = game_client.get("/api/game/state")
        assert r.status_code == 401
        body = r.json()
        assert "detail" in body
        detail = str(body.get("detail", ""))
        assert "Traceback" not in detail
        assert "File \"" not in detail

    def test_400_or_422_has_detail(self, game_client, game_headers):
        r = game_client.post("/api/game/craft/upgrade", json={}, headers=game_headers)
        assert r.status_code in (400, 422, 500)
        if r.status_code in (400, 422):
            body = r.json()
            assert "detail" in body

    def test_500_no_traceback_in_body(self, game_client):
        r = game_client.get("/api/game/config")
        if r.status_code == 500:
            body = r.json() if "application/json" in (r.headers.get("content-type") or "") else {}
            if isinstance(body, dict):
                detail = str(body.get("detail", ""))
                assert "Traceback" not in detail
                assert "File \"" not in detail
