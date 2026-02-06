import json
import os
from pathlib import Path
from typing import Any, Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# ——— Master config (game.field, game.mine, game.eggs) ———
_CONFIG_DIR = Path(__file__).resolve().parent
_DEFAULT_GAME_CONFIG_PATH = _CONFIG_DIR / "data" / "game_config.json"

def _load_game_config() -> Dict[str, Any]:
    path_str = _env("GAME_CONFIG_PATH", "").strip()
    path = Path(path_str) if path_str else _DEFAULT_GAME_CONFIG_PATH
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"game": {}}


GAME_CONFIG = _load_game_config()

# Удобные доступы по 25_Архитектура.md, 18_Dev
def get_field_config() -> Dict[str, Any]:
    return GAME_CONFIG.get("game", {}).get("field") or {"maxBuildingsPlaced": 9, "demolishRefundRate": 0.25}


def get_mine_config() -> Dict[str, Any]:
    return GAME_CONFIG.get("game", {}).get("mine") or {
        "gridSize": 36,
        "checkin": {"cooldownHours": 10, "attemptsPerClaim": 3},
        "prizeCellsDistribution": [
            {"cells": 2, "chancePct": 10}, {"cells": 3, "chancePct": 20},
            {"cells": 4, "chancePct": 30}, {"cells": 5, "chancePct": 25}, {"cells": 6, "chancePct": 15}
        ],
        "prizeCellLoot": {"relicPct": 72.0, "amuletPct": 15.0, "coinsPct": 12.1, "eggPct": 0.9},
    }


def get_eggs_config() -> Dict[str, Any]:
    return GAME_CONFIG.get("game", {}).get("eggs") or {"colors": []}


# game_rules (ключи конфига по 18_Dev)
CHECKIN_RULES = {
    "baseCdMinutes": 600,
    "minCdMinutes": 540,
    "grantedAttempts": 3,
    "resetBonusMinutesAfterCheckin": True,
}
MINE_RULES = {
    "gridSize": 36,
    "eggChancePerDig": 0.001,
    "prizeCellsDist": get_mine_config().get("prizeCellsDistribution", []),
    "prizeTypeWeights": get_mine_config().get("prizeCellLoot") or {"relicPct": 72, "amuletPct": 15, "coinsPct": 12.1, "eggPct": 0.9},
}

DATABASE_URL = _env("DATABASE_URL", "postgresql://localhost/village_era")
REDIS_URL = _env("REDIS_URL", "redis://localhost:6379/0")
TON_API_URL = _env("TON_API_URL", "https://tonapi.io/v2")
TON_API_KEY = _env("TON_API_KEY", "")
PHOEX_TOKEN_ADDRESS = _env("PHOEX_TOKEN_ADDRESS", "EQABtSLSzrAOISWPfIjBl2VmeStkM1eHaPrUxRTj8mY-9h43")
PROJECT_WALLET_ADDRESS = _env("PROJECT_WALLET_ADDRESS", "")
GAME_ADMIN_TG_ID = int(_env("GAME_ADMIN_TG_ID", "496560064"))
GAME_NOTIFY_BOT_TOKEN = _env("GAME_NOTIFY_BOT_TOKEN", "")
PHOENIX_QUEST_REWARD_AMOUNT = int(_env("PHOENIX_QUEST_REWARD_AMOUNT", "100000"))
POINTS_PER_TON = int(_env("POINTS_PER_TON", "10"))
# Защита награды: минимум сжиганий и возраст аккаунта (дней)
MIN_BURN_COUNT_FOR_PHOENIX_QUEST = int(_env("MIN_BURN_COUNT_FOR_PHOENIX_QUEST", "5"))
MIN_ACCOUNT_AGE_DAYS_FOR_PHOENIX_QUEST = int(_env("MIN_ACCOUNT_AGE_DAYS_FOR_PHOENIX_QUEST", "3"))
# Rate-limit на попытки завершения квеста (секунды)
PHOENIX_QUEST_SUBMIT_RATE_LIMIT_SEC = int(_env("PHOENIX_QUEST_SUBMIT_RATE_LIMIT_SEC", "5"))
# Diminishing returns: после скольких сжиганий множитель опыта 0.5
BURN_DIMINISHING_AFTER = int(_env("BURN_DIMINISHING_AFTER", "50"))
# Telegram bot (для проверки пользователя в чате/канале getChatMember)
BOT_TOKEN = _env("BOT_TOKEN", "")
