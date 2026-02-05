import json
import math
import random
import time
from typing import Any, Dict, List, Optional

from config import (
    BURN_DIMINISHING_AFTER,
    POINTS_PER_TON,
    PHOENIX_QUEST_REWARD_AMOUNT,
)

POINTS_PER_TON_ENGINE = POINTS_PER_TON
PHOENIX_WORD = "ФЕНИКС"
RUS_ALPHABET = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"

DEFAULT_STATE = {
    "gems": 0,
    "coins": 1000,
    "wood": 100,
    "stone": 100,
    "era": 1,
    "eraStart": int(time.time() * 1000),
    "vLevel": 1,
    "skyFall": False,
    "skyStart": None,
    "lossMult": 1,
    "buildings": [],
    "mineBlocks": [],
    "relicsFound": 0,
    "relics": [],
    "amulets": [],
    "buffs": [],
    "digsLeft": 5,
    "lastCheckin": None,
    "exp": 0,
    "level": 0,
    "createdAt": int(time.time() * 1000),
    "actions": 0,
    "weekId": None,
    "weeklyScore": 0,
    "withdrawsThisWeek": 0,
    "lock": {"active": False, "amount": 0, "until": 0},
    "kyc": {"verified": False},
    "sellDay": None,
    "sellsToday": 0,
    "walletBound": False,
    "walletVerifyCode": None,
    "subscribedChannels": {"phxpw": False, "ludoman": False, "kriptobratv": False},
    "points": 0,
    "eraMedals": [],
    "mineHintIndices": [],
    "mineScanActive": False,
    "phoenixEyeActive": False,
    "burnedCount": 0,
    "letters": [],
    "phoenixQuestCompleted": False,
}


def _deep_copy(s: Dict) -> Dict:
    return json.loads(json.dumps(s, ensure_ascii=False))


def _ensure_week(state: Dict) -> None:
    # Simplified week id
    state.setdefault("weekId", "")
    state.setdefault("withdrawsThisWeek", 0)


def _add_exp(state: Dict, x: int) -> None:
    _ensure_week(state)
    state["exp"] = (state.get("exp") or 0) + x
    e = state["exp"]
    state["level"] = 3 if e >= 2500 else (2 if e >= 1200 else (1 if e >= 400 else 0))


def apply_collect(state: Dict) -> Dict:
    state = _deep_copy(state)
    now = int(time.time() * 1000)
    buildings = state.get("buildings", [])
    if not buildings:
        return state
    total = 0
    for b in buildings:
        last = b.get("last", now)
        hours = (now - last) / (1000 * 60 * 60)
        inc = 5 * b.get("lv", 1) * hours  # simplified inc
        total += int(inc)
        b["last"] = now
    state["coins"] = state.get("coins", 0) + total
    state["actions"] = state.get("actions", 0) + 1
    _add_exp(state, 5)
    return state


def apply_burn(state: Dict, relic_idx: int) -> Dict:
    state = _deep_copy(state)
    relics = state.get("relics", [])
    if relic_idx < 0 or relic_idx >= len(relics):
        return state
    r = relics[relic_idx]
    del relics[relic_idx]
    ev = r.get("ev", 0)
    exp_gain = 10 + ev // 2
    burned = (state.get("burnedCount") or 0) + 1
    state["burnedCount"] = burned
    if burned > BURN_DIMINISHING_AFTER:
        exp_gain = math.floor(exp_gain * 0.5)
    _add_exp(state, exp_gain)
    state.setdefault("letters", [])
    state["letters"].append(random.choice(RUS_ALPHABET))
    return state


def validate_phoenix_sequence(letters_sequence: Any) -> bool:
    """Проверка последовательности букв только на сервере."""
    if isinstance(letters_sequence, str):
        return letters_sequence.strip().upper() == PHOENIX_WORD
    if isinstance(letters_sequence, list):
        return "".join(str(c).strip().upper() for c in letters_sequence) == PHOENIX_WORD
    return False


def apply_phoenix_quest(state: Dict) -> Dict:
    state = _deep_copy(state)
    if state.get("phoenixQuestCompleted"):
        return state
    state["phoenixQuestCompleted"] = True
    return state


def points_ceil(ton_value: float) -> int:
    """Единообразное округление поинтов на сервере (целые только)."""
    return math.ceil(ton_value * POINTS_PER_TON_ENGINE)


def apply_buy_diamonds_points(state: Dict, pack_idx: int) -> Dict:
    state = _deep_copy(state)
    packs = [
        {"gems": 100, "ton": 10, "bonus": 0},
        {"gems": 500, "ton": 45, "bonus": 50},
        {"gems": 1000, "ton": 85, "bonus": 150},
        {"gems": 5000, "ton": 400, "bonus": 1000},
    ]
    if pack_idx < 0 or pack_idx >= len(packs):
        return state
    pk = packs[pack_idx]
    pts_need = points_ceil(pk["ton"])
    points = int(state.get("points") or 0)
    if points < pts_need:
        return state
    state["points"] = points - pts_need
    state["gems"] = (state.get("gems") or 0) + pk["gems"] + (pk.get("bonus") or 0)
    return state


def apply_sell(state: Dict, relic_idx: int) -> Dict:
    state = _deep_copy(state)
    relics = state.get("relics", [])
    if relic_idx < 0 or relic_idx >= len(relics):
        return state
    r = relics[relic_idx]
    raw = (r.get("ev") or 10) * 10 or 100
    level = state.get("level", 0)
    tax_rates = {0: 0.25, 1: 0.20, 2: 0.15, 3: 0.12}
    tax = tax_rates.get(level, 0.25)
    tax_amt = int(raw * tax)
    net = max(0, raw - tax_amt)
    state["coins"] = (state.get("coins") or 0) + net
    del relics[relic_idx]
    state["sellsToday"] = (state.get("sellsToday") or 0) + 1
    _add_exp(state, 20)
    return state


def get_default_state() -> Dict:
    return _deep_copy(DEFAULT_STATE)


def merge_client_state(server_state: Dict, client_state: Dict) -> Dict:
    """Merge client state into server state (server wins on critical fields)."""
    out = _deep_copy(client_state)
    out["phoenixQuestCompleted"] = server_state.get("phoenixQuestCompleted", False)
    out["burnedCount"] = server_state.get("burnedCount", 0)
    out["letters"] = list(server_state.get("letters", []))
    out["points"] = server_state.get("points", 0)
    out["gems"] = server_state.get("gems", 0)
    out["coins"] = server_state.get("coins", 0)
    out["exp"] = server_state.get("exp", 0)
    out["level"] = server_state.get("level", 0)
    out["relics"] = list(server_state.get("relics", []))
    out["amulets"] = list(server_state.get("amulets", []))
    return out
