"""
Инъекции: передача SQL/NoSQL-подобных строк в body — ожидаем 400/422 или экранирование,
не 500 и не выполнение кода.
"""
import pytest


@pytest.mark.security
class TestInjectionGame:
    """Игровые эндпоинты с пользовательским вводом в body."""

    def test_action_sync_sql_like_username(self, game_client, game_headers):
        r = game_client.post(
            "/api/game/action",
            json={
                "action": "sync",
                "params": {"username": "'; DROP TABLE users--", "first_name": "x"},
            },
            headers=game_headers,
        )
        assert r.status_code in (200, 400, 422), "Не должно быть 500 при подозрительной строке"
        if r.status_code == 200:
            # Повторный запрос состояния — данные не должны быть испорчены
            r2 = game_client.get("/api/game/state", headers=game_headers)
            assert r2.status_code == 200
            assert isinstance(r2.json(), dict)

    def test_phoenix_submit_invalid_word(self, game_client, game_headers):
        r = game_client.post(
            "/api/game/phoenix/submit",
            json={"word": "'; DELETE FROM user_items;--", "letter_item_ids": []},
            headers=game_headers,
        )
        assert r.status_code in (200, 400, 422)
        assert r.status_code != 500

    def test_mine_dig_no_sql_in_body(self, game_client, game_headers):
        # Создаём шахту и копаем с «странным» cell_index
        create = game_client.post("/api/game/mine/create", headers=game_headers)
        if create.status_code != 200:
            pytest.skip("mine/create не доступен")
        mine_id = create.json().get("mine_id")
        r = game_client.post(
            "/api/game/mine/dig",
            json={"mine_id": mine_id, "cell_index": "0 OR 1=1"},
            headers=game_headers,
        )
        assert r.status_code in (200, 400, 422)
        assert r.status_code != 500
