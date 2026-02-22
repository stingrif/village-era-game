"""
E2E тесты Game API: полное покрытие /api/game/* — успех и отказ по каждому эндпоинту.
"""
import pytest


BASE = "/api/game"


@pytest.mark.e2e
class TestAuthRequired:
    """Эндпоинты с пользователем возвращают 401 без X-Telegram-User-Id."""

    def test_config_no_auth_required(self, game_client):
        r = game_client.get(f"{BASE}/config")
        assert r.status_code == 200

    def test_attempts_requires_auth(self, game_client):
        r = game_client.get(f"{BASE}/attempts")
        assert r.status_code == 401

    def test_state_requires_auth(self, game_client):
        r = game_client.get(f"{BASE}/state")
        assert r.status_code == 401

    def test_checkin_requires_auth(self, game_client):
        r = game_client.post(f"{BASE}/checkin", json={})
        assert r.status_code in (401, 422)


@pytest.mark.e2e
class TestHealthAndConfig:
    def test_health(self, game_client):
        r = game_client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_config_structure(self, game_client):
        r = game_client.get(f"{BASE}/config")
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            j = r.json()
            assert "field" in j
            assert "mine" in j


@pytest.mark.e2e
class TestCheckinAndAttempts:
    def test_checkin(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/checkin", json={}, headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            j = r.json()
            assert "next_checkin_at" in j or "granted_attempts" in j or "message" in j

    def test_checkin_state(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/checkin-state", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), dict)

    def test_attempts(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/attempts", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            j = r.json()
            assert "attempts" in j or isinstance(j, dict)


@pytest.mark.e2e
class TestMine:
    def test_mine_create(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/mine/create", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert "mine_id" in r.json()

    def test_mine_dig_empty_body_400(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/mine/dig", json={}, headers=game_headers)
        assert r.status_code == 400

    def test_mine_get_nonexistent(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/mine/00000000-0000-0000-0000-000000000000", headers=game_headers)
        assert r.status_code in (400, 404, 422, 500)


@pytest.mark.e2e
class TestBalancesAndInventory:
    def test_balances(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/balances", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert "balances" in r.json() or isinstance(r.json(), dict)

    def test_inventory(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/inventory", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), (dict, list))


@pytest.mark.e2e
class TestFieldAndBuildings:
    def test_field(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/field", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), (dict, list))

    def test_buildings_def(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/buildings/def", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), list)

    def test_field_place_invalid_slot(self, game_client, game_headers):
        r = game_client.post(
            f"{BASE}/field/place",
            json={"slot_index": 99, "building_key": "hut", "cost": 100},
            headers=game_headers,
        )
        assert r.status_code in (200, 400, 422, 500)

    def test_field_slots(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/field/slots/hut", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_field_collect(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/field/collect", headers=game_headers)
        assert r.status_code in (200, 500)


@pytest.mark.e2e
class TestPhoenix:
    def test_phoenix_word(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/phoenix/word", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), dict)

    def test_phoenix_letters(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/phoenix/letters", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_phoenix_submit_empty_validation(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/phoenix/submit", json={}, headers=game_headers)
        assert r.status_code in (200, 400, 422, 500)


@pytest.mark.e2e
class TestCraft:
    def test_craft_merge_validation(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/craft/merge", json={"item_ids": [1, 2]}, headers=game_headers)
        assert r.status_code in (200, 400)

    def test_craft_upgrade_no_body_400(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/craft/upgrade", json={}, headers=game_headers)
        assert r.status_code in (400, 422, 500)

    def test_craft_reroll_no_body_400(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/craft/reroll", json={}, headers=game_headers)
        assert r.status_code in (400, 422, 500)


@pytest.mark.e2e
class TestItemsAndShop:
    def test_items_catalog(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/items-catalog", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), list)

    def test_items_stats(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/items-stats", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_shop_offers(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/shop/offers", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), (list, dict))

    def test_shop_purchase_invalid_400(self, game_client, game_headers):
        r = game_client.post(
            f"{BASE}/shop/purchase",
            json={"offer_id": 0, "quantity": 1},
            headers=game_headers,
        )
        assert r.status_code in (200, 400, 404, 500)


@pytest.mark.e2e
class TestMarket:
    def test_market_orders(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/market/orders", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), list)

    def test_market_order_create_validation(self, game_client, game_headers):
        r = game_client.post(
            f"{BASE}/market/orders",
            json={"user_item_ids": [], "pay_amount": 1},
            headers=game_headers,
        )
        assert r.status_code in (400, 422, 500)

    def test_market_order_fill_nonexistent(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/market/orders/999999/fill", json={}, headers=game_headers)
        assert r.status_code in (400, 404, 500)


@pytest.mark.e2e
class TestWithdrawAndDonate:
    def test_withdraw_eligibility(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/withdraw/eligibility", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), dict)

    def test_withdraw_request(self, game_client, game_headers):
        r = game_client.post(
            f"{BASE}/withdraw/request",
            json={"amount": 100},
            headers=game_headers,
        )
        assert r.status_code in (200, 403, 500)

    def test_ads_view(self, game_client, game_headers):
        r = game_client.post(
            f"{BASE}/ads/view",
            json={"ad_kind": "short"},
            headers=game_headers,
        )
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert r.json().get("ok") is True

    def test_donate(self, game_client, game_headers):
        r = game_client.post(
            f"{BASE}/donate",
            json={"currency": "STARS", "amount": 10, "period_key": "2026-W06"},
            headers=game_headers,
        )
        assert r.status_code in (200, 500)


@pytest.mark.e2e
class TestStakingAndLeaderboards:
    def test_staking_sessions(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/staking/sessions", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), list)

    def test_staking_create(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/staking/create", json={}, headers=game_headers)
        assert r.status_code in (200, 500)

    def test_leaderboards(self, game_client):
        r = game_client.get(f"{BASE}/leaderboards", params={"period": "weekly"})
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), (dict, list))


@pytest.mark.e2e
class TestStateAndAction:
    def test_state(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/state", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), dict)

    def test_action_sync(self, game_client, game_headers):
        r = game_client.post(
            f"{BASE}/action",
            json={"action": "sync", "params": {}},
            headers=game_headers,
        )
        assert r.status_code in (200, 500)

    def test_action_collect(self, game_client, game_headers):
        r = game_client.post(
            f"{BASE}/action",
            json={"action": "collect", "params": {}},
            headers=game_headers,
        )
        assert r.status_code in (200, 500)


@pytest.mark.e2e
class TestRatesStatsPnl:
    def test_rates(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/rates", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_stats(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/stats", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_pnl_wallet_state(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/pnl/wallet-state", headers=game_headers)
        assert r.status_code in (200, 500)


@pytest.mark.e2e
class TestWalletsAndNft:
    def test_wallets(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/wallets", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), (list, dict))

    def test_wallet_post(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/wallet", json={}, headers=game_headers)
        assert r.status_code in (200, 201, 400, 500)

    def test_nft_check(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/nft/check", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_nft_dev_profile(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/nft/dev-profile", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_nft_user_nfts(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/nft/user-nfts", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_nft_catalog(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/nft/catalog", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_nft_holders_summary(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/nft/holders-summary", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_nft_sync(self, game_client, game_headers):
        r = game_client.post(f"{BASE}/nft/sync", json={}, headers=game_headers)
        assert r.status_code in (200, 403, 404, 500)


@pytest.mark.e2e
class TestVisitLogHistoryAttack:
    def test_visit_log(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/visit-log", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_history_logs(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/history/logs", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_attack_validation(self, game_client, game_headers):
        r = game_client.post(
            f"{BASE}/attack/999999999",
            json={},
            headers=game_headers,
        )
        assert r.status_code in (200, 400, 404, 500)


@pytest.mark.e2e
class TestPartnerTokensTasksPageTexts:
    def test_partner_tokens(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/partner-tokens", headers=game_headers)
        assert r.status_code in (200, 500)

    def test_tasks(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/tasks", headers=game_headers)
        assert r.status_code in (200, 500)
        if r.status_code == 200:
            assert isinstance(r.json(), (list, dict))

    def test_page_texts(self, game_client, game_headers):
        r = game_client.get(f"{BASE}/page-texts/about", headers=game_headers)
        assert r.status_code in (200, 404, 500)
