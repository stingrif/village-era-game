"""
E2E тесты полного API игры Village Era.
Проверяют все основные эндпоинты по 25_Архитектура и 18_Dev.
Запуск: из корня бэкенда: pytest tests/test_game_api_e2e.py -v
"""
import os
import sys
from pathlib import Path

# Корень бэкенда = родитель папки tests
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(BACKEND_ROOT)

import pytest

from api.main import app

# Один тестовый пользователь для всех запросов с заголовком
TEST_TELEGRAM_ID = "999001"
HEADERS = {"X-Telegram-User-Id": TEST_TELEGRAM_ID}

def _make_client():
    """Предпочитаем TestClient; при несовместимости starlette/httpx — HTTP к уже запущенному серверу или uvicorn."""
    # Если сервер уже запущен — подключаемся к нему
    base_url = os.environ.get("TEST_API_BASE_URL", "").strip()
    if base_url:
        try:
            import httpx
            c = httpx.Client(base_url=base_url.rstrip("/"), timeout=10.0)
            return ("httpx", c)
        except ImportError:
            pytest.skip("Для TEST_API_BASE_URL нужен httpx")
    try:
        from fastapi.testclient import TestClient
        return ("testclient", TestClient(app))
    except (ImportError, TypeError):
        pass
    # Запасной вариант: поднять сервер в процессе и ходить по HTTP
    import subprocess
    import time
    import atexit
    port = 18765
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=BACKEND_ROOT,
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(proc.terminate)
    for _ in range(30):
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        pytest.skip("Не удалось запустить uvicorn за 6 сек")
    try:
        import httpx
        c = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10.0)
        return ("httpx", c)
    except ImportError:
        proc.terminate()
        pytest.skip("Для запасного режима нужен httpx")


_client_type = None
_client_obj = None


@pytest.fixture(scope="module")
def client():
    """Клиент к API: TestClient или живой сервер."""
    global _client_type, _client_obj
    if _client_type is None:
        kind, _client_obj = _make_client()
        _client_type = kind
    if _client_type == "testclient":
        with _client_obj as c:
            yield c
    else:
        yield _client_obj


# ——— Дымовые тесты (быстрая проверка) ———

@pytest.mark.smoke
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.smoke
def test_config(client):
    r = client.get("/api/game/config")
    assert r.status_code == 200
    data = r.json()
    assert "field" in data
    assert "mine" in data
    assert "eggs" in data


@pytest.mark.smoke
def test_auth_required(client):
    """Эндпоинты с пользователем требуют X-Telegram-User-Id."""
    r = client.get("/api/game/attempts")
    assert r.status_code == 401


# ——— Чекин и попытки ———

def test_checkin(client):
    r = client.post("/api/game/checkin", headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert "next_checkin_at" in j
    assert "granted_attempts" in j


def test_checkin_state(client):
    r = client.get("/api/game/checkin-state", headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert "next_checkin_at" in j
    assert "streak" in j


def test_attempts(client):
    r = client.get("/api/game/attempts", headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert "attempts" in j
    assert isinstance(j["attempts"], (int, float))


# ——— Шахта ———

def test_mine_create(client):
    r = client.post("/api/game/mine/create", headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert "mine_id" in j


def test_mine_get(client):
    r = client.post("/api/game/mine/create", headers=HEADERS)
    assert r.status_code == 200
    mine_id = r.json()["mine_id"]
    r = client.get(f"/api/game/mine/{mine_id}", headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert j["id"] == mine_id
    assert "grid_size" in j
    assert "opened_cells" in j


def test_mine_dig(client):
    r = client.post("/api/game/mine/create", headers=HEADERS)
    assert r.status_code == 200
    mine_id = r.json()["mine_id"]
    r = client.post(
        "/api/game/mine/dig",
        json={"mine_id": mine_id, "cell_index": 0},
        headers=HEADERS,
    )
    assert r.status_code == 200
    j = r.json()
    assert "opened_cells" in j


def test_mine_dig_bad_request(client):
    r = client.post("/api/game/mine/dig", json={}, headers=HEADERS)
    assert r.status_code == 400


# ——— Балансы и инвентарь ———

def test_balances(client):
    r = client.get("/api/game/balances", headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert "balances" in j


def test_inventory(client):
    r = client.get("/api/game/inventory", headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j, (dict, list))


# ——— Поле и здания ———

def test_field(client):
    r = client.get("/api/game/field", headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j, (dict, list))


def test_buildings_def(client):
    r = client.get("/api/game/buildings/def", headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j, list)


def test_field_place(client):
    defs = client.get("/api/game/buildings/def", headers=HEADERS).json()
    if not defs:
        pytest.skip("no buildings def")
    building_key = defs[0].get("key") or defs[0].get("building_key") or "hut"
    r = client.post(
        "/api/game/field/place",
        json={"slot_index": 1, "building_key": building_key, "cost": 100},
        headers=HEADERS,
    )
    assert r.status_code in (200, 400)


def test_field_demolish(client):
    r = client.post("/api/game/field/demolish", json={"slot_index": 1}, headers=HEADERS)
    assert r.status_code in (200, 400)


def test_field_upgrade(client):
    r = client.post(
        "/api/game/field/upgrade",
        json={"building_key": "hut", "cost": 50},
        headers=HEADERS,
    )
    assert r.status_code in (200, 400)


def test_field_slots(client):
    r = client.get("/api/game/field/slots/hut", headers=HEADERS)
    assert r.status_code == 200


def test_field_equip_unequip(client):
    r = client.post(
        "/api/game/field/equip",
        json={"building_key": "hut", "slot_index": 0, "user_item_id": 999999},
        headers=HEADERS,
    )
    assert r.status_code in (200, 400)
    r2 = client.post(
        "/api/game/field/unequip",
        json={"building_key": "hut", "slot_index": 0},
        headers=HEADERS,
    )
    assert r2.status_code in (200, 400)


def test_field_collect(client):
    r = client.post("/api/game/field/collect", headers=HEADERS)
    assert r.status_code == 200


# ——— Крафт ———

def test_craft_merge_validation(client):
    r = client.post(
        "/api/game/craft/merge",
        json={"item_ids": [1, 2]},
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_craft_upgrade_validation(client):
    r = client.post(
        "/api/game/craft/upgrade",
        json={},
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_craft_reroll_validation(client):
    r = client.post(
        "/api/game/craft/reroll",
        json={},
        headers=HEADERS,
    )
    assert r.status_code == 400


# ——— Рынок ———

def test_market_orders_list(client):
    r = client.get("/api/game/market/orders", headers=HEADERS)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_market_order_create_validation(client):
    r = client.post(
        "/api/game/market/orders",
        json={"user_item_ids": [], "pay_amount": 1},
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_market_order_fill_validation(client):
    r = client.post(
        "/api/game/market/orders/999999/fill",
        headers=HEADERS,
    )
    assert r.status_code in (400, 404)


def test_trade_offer_create_validation(client):
    r = client.post(
        "/api/game/market/trade-offers",
        json={"maker_item_ids": []},
        headers=HEADERS,
    )
    assert r.status_code == 400


# ——— Вывод, реклама, донаты ———

def test_withdraw_eligibility(client):
    r = client.get("/api/game/withdraw/eligibility", headers=HEADERS)
    assert r.status_code == 200
    j = r.json()
    assert "can_withdraw" in j or isinstance(j, dict)


def test_withdraw_request_stub(client):
    r = client.post(
        "/api/game/withdraw/request",
        json={"amount": 100},
        headers=HEADERS,
    )
    # 200 — заглушка приняла; 403 — вывод отключён (can_withdraw False)
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        j = r.json()
        assert "message" in j or "ok" in j


def test_ads_view(client):
    r = client.post(
        "/api/game/ads/view",
        json={"ad_kind": "short"},
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


def test_donate(client):
    r = client.post(
        "/api/game/donate",
        json={"currency": "STARS", "amount": 10, "period_key": "2026-W06"},
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json().get("ok") is True


# ——— Стейкинг и лидерборды ———

def test_staking_sessions(client):
    r = client.get("/api/game/staking/sessions", headers=HEADERS)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_staking_create_stub(client):
    r = client.post(
        "/api/game/staking/create",
        json={},
        headers=HEADERS,
    )
    assert r.status_code == 200
    j = r.json()
    assert "message" in j or "ok" in j


def test_leaderboards(client):
    r = client.get("/api/game/leaderboards?period=weekly")
    assert r.status_code == 200
    j = r.json()
    assert isinstance(j, (dict, list))


# ——— Legacy state/action (по маршрутам) ———

def test_game_state(client):
    r = client.get("/api/game/state", headers=HEADERS)
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_game_action_collect(client):
    r = client.post(
        "/api/game/action",
        json={"action": "collect", "params": {}},
        headers=HEADERS,
    )
    assert r.status_code == 200
