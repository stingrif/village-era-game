import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

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
