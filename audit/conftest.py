"""
Общие фикстуры для audit: клиенты к Game API, Tigrit API, заголовки.
"""
import os
import sys
from pathlib import Path

import pytest

# Корень проекта Игра и бэкенд
AUDIT_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = AUDIT_ROOT.parent
BACKEND_ROOT = PROJECT_ROOT / "бэкенд"

TEST_TELEGRAM_ID = "999001"
GAME_HEADERS = {"X-Telegram-User-Id": TEST_TELEGRAM_ID}


def _game_client():
    """Клиент к Game API: TestClient или httpx к TEST_API_BASE_URL."""
    base_url = os.environ.get("TEST_API_BASE_URL", "").strip()
    if base_url:
        try:
            import httpx
            return httpx.Client(base_url=base_url.rstrip("/"), timeout=15.0)
        except ImportError:
            pytest.skip("Для TEST_API_BASE_URL нужен httpx")
    # TestClient к приложению бэкенда
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)
    except Exception as e:
        pytest.skip(f"Не удалось создать TestClient к бэкенду: {e}")


def _tigrit_client():
    """Клиент к Tigrit API по TIGRIT_API_BASE или skip."""
    base_url = os.environ.get("TIGRIT_API_BASE", "").strip()
    if not base_url:
        pytest.skip("TIGRIT_API_BASE не задан")
    try:
        import httpx
        return httpx.Client(base_url=base_url.rstrip("/"), timeout=10.0)
    except ImportError:
        pytest.skip("Для Tigrit нужен httpx")


@pytest.fixture(scope="function")
def game_client():
    """Клиент к Game API (игра + internal). Function scope избегает проблем с event loop при TestClient."""
    return _game_client()


@pytest.fixture(scope="session")
def game_headers():
    """Заголовок пользователя для эндпоинтов игры."""
    return GAME_HEADERS.copy()


@pytest.fixture(scope="session")
def internal_secret():
    """INTERNAL_API_SECRET из env (для /internal/ensure-user)."""
    return os.environ.get("INTERNAL_API_SECRET", "").strip()


@pytest.fixture(scope="session")
def internal_headers(internal_secret):
    """Заголовки для internal API."""
    if not internal_secret:
        return {}
    return {"X-Internal-Secret": internal_secret}


@pytest.fixture(scope="session")
def tigrit_client():
    """Клиент к Tigrit API (опционально)."""
    return _tigrit_client()


@pytest.fixture(scope="session")
def editor_api_key():
    """EDITOR_API_KEY из env (для PUT /api/map)."""
    return os.environ.get("EDITOR_API_KEY", "").strip()


@pytest.fixture(scope="session")
def tigrit_editor_headers(editor_api_key):
    """Заголовки для сохранения карты Tigrit."""
    if not editor_api_key:
        return {}
    return {"X-API-Key": editor_api_key, "Content-Type": "application/json"}
