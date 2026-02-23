"""
Запускает SQL-миграции из папки migrations/ при старте tigrit-api.
Файлы выполняются в алфавитном порядке. Каждый файл идемпотентен (IF NOT EXISTS).
Вызывается из lifespan() в main.py.
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# Добавляем пути для доступа к tigrit_shared
_root = Path(__file__).resolve().parents[1]
_backend = Path(__file__).resolve().parent
for _p in (_root, _backend):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


async def run_migrations() -> None:
    """Выполняет все *.sql файлы из migrations/ в алфавитном порядке через asyncpg."""
    if not MIGRATIONS_DIR.exists():
        logger.warning("run_migrations: папка migrations/ не найдена, пропуск")
        return

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not sql_files:
        logger.info("run_migrations: нет SQL-файлов в migrations/")
        return

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.warning("run_migrations: DATABASE_URL не задан, миграции пропущены")
        return

    import asyncpg
    try:
        conn = await asyncpg.connect(database_url)
    except Exception as e:
        logger.error("run_migrations: не удалось подключиться к БД: %s", e)
        return

    try:
        for sql_file in sql_files:
            sql = sql_file.read_text(encoding="utf-8")
            try:
                await conn.execute(sql)
                logger.info("[OK] %s", sql_file.name)
            except Exception as e:
                logger.error("[FAIL] %s: %s", sql_file.name, e)
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_migrations())
