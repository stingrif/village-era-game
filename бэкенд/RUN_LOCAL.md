# Запуск фронта + бэкенда локально

## 0. Виртуальное окружение (рекомендуется)

В папке `Игра/бэкенд` уже создано виртуальное окружение `venv`. Используйте его, чтобы не засорять системный Python.

**Один раз создать venv и установить зависимости:**

```bash
cd "/Users/Den/Downloads/Игра/бэкенд"
python3 -m venv venv
source venv/bin/activate   # macOS/Linux
# Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Каждый раз перед работой — активировать venv и запускать бэкенд:**

```bash
cd "/Users/Den/Downloads/Игра/бэкенд"
source venv/bin/activate
# Задайте DATABASE_URL в .env или: export DATABASE_URL="postgresql://..."
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Либо без активации — вызвать uvicorn напрямую из venv:

```bash
cd "/Users/Den/Downloads/Игра/бэкенд"
./venv/bin/uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

(Тогда переменные окружения читаются из `.env` в этой папке.)

---

## 1. PostgreSQL

У вас уже есть PostgreSQL. Выберите один из вариантов.

### Вариант A — контейнер с пользователем `phoenix` (порт 5440)

```bash
export DATABASE_URL="postgresql://phoenix:PASTE_PASSWORD@127.0.0.1:5440/PhoenixBD"
```

Если пароль другой (например с `));` в конце) — подставьте свой:
```bash
export DATABASE_URL="postgresql://phoenix:PASTE_PASSWORD@127.0.0.1:5440/PhoenixBD"
```

### Вариант B — контейнер `projectdb` (n8n, порт обычно 5432)

Если этот Postgres доступен на хосте (порт 5432 или тот, что проброшен в docker):

```bash
export DATABASE_URL="postgresql://project:PASTE_PASSWORD@127.0.0.1:5432/PhoenixBD"
```

Порт смотрите в `ports:` в `бэкенд/docker/docker-compose.yml` (например `5432:5432` → порт 5432).

### Отдельная база для игры (рекомендуется)

Чтобы не смешивать таблицы с другими проектами, создайте отдельную БД:

```bash
# Подключитесь к Postgres (для варианта A — порт 5440)
psql -h 127.0.0.1 -p 5440 -U phoenix -d PhoenixBD -c "CREATE DATABASE village_era;"

# Или для варианта B
psql -h 127.0.0.1 -p 5432 -U project -d PhoenixBD -c "CREATE DATABASE village_era;"
```

Тогда используйте URL с базой `village_era`:

```bash
# Вариант A
export DATABASE_URL="postgresql://phoenix:PASTE_PASSWORD@127.0.0.1:5440/village_era"

# Вариант B
export DATABASE_URL="postgresql://project:PASTE_PASSWORD@127.0.0.1:5432/village_era"
```

Таблицы `game_players` и `pending_payouts` бэкенд создаст сам при первом запуске.

### Подключение с ПК по IP сервера

Если бэкенд запускается **на ПК**, а PostgreSQL — на сервере в той же сети, в `DATABASE_URL` указывайте **IP сервера** (например `192.168.1.149`), а не `127.0.0.1`. Так потом перенос приложения на сервер не потребует смены кода.

Проверка подключения с ПК (порт 5440 — для phoenix-postgres; для n8n-projectdb порт смотрите в `docker port n8n-projectdb-1`):

```bash
psql "postgresql://project:PASTE_PASSWORD@192.168.1.149:5440/PhoenixBD"
```

---

## 1.5 Redis (Docker)

Postgres у вас уже есть. Redis можно поднять отдельно через Docker. Перейдите в папку **бэкенд** (там лежит `docker-compose.yml`):

```bash
cd бэкенд
docker compose up redis -d
```
(Если вы в другом каталоге, укажите полный путь к бэкенду, например: `cd /Users/Den/Downloads/Игра/бэкенд`.)

В `.env` укажите: `REDIS_URL=redis://localhost:6379/0`. Подробнее — в **docker/README.md**. Проверка всех подключений: `python скрипты/check_db_connections.py`.

---

## 2. Запуск бэкенда

На машине, где лежит проект (или по SSH к серверу с Postgres). Лучше использовать venv (см. раздел 0).

```bash
cd "/Users/Den/Downloads/Игра/бэкенд"
source venv/bin/activate
# Один раз задать DATABASE_URL в .env или:
export DATABASE_URL="postgresql://phoenix:PASTE_PASSWORD@127.0.0.1:5440/village_era"

uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Проверка: в браузере открыть **http://localhost:8000/health** — должно быть `{"status":"ok"}`.

Если бэкенд на другом хосте (например сервер), подставьте его IP в `DATABASE_URL` и открывайте **http://IP_СЕРВЕРА:8000/health**.

---

## 3. Запуск фронта

В другом терминале:

```bash
cd "/Users/Den/Downloads/Игра"
node generate_config.js   # один раз при смене API: генерирует config.js с GAME_API_BASE из .env
python3 -m http.server 8080
```

Откройте в браузере: **http://localhost:8080/village-era-game-final.html** (единственная точка входа; другие HTML не используют актуальный код).

URL бэкенда задаётся в **config.js** (поле `window.GAME_API_BASE`), который генерируется из `.env` в папке Игра. В `.env` в папке Игра добавьте, например: `API_BASE=http://localhost:8000`. После изменения API запустите снова `node generate_config.js`.

Если фронт открыт с другого компьютера — укажите IP сервера в API_BASE, например `http://192.168.1.10:8000`.

---

## 4. Файл .env (удобно)

В папке `Игра/бэкенд` создайте файл `.env`:

```
DATABASE_URL=postgresql://phoenix:PASTE_PASSWORD@127.0.0.1:5440/village_era
```

Бэкенд подхватывает `.env` через `python-dotenv`. После этого можно запускать без `export`:

```bash
cd "/Users/Den/Downloads/Игра/бэкенд"
source venv/bin/activate
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Итог

| Шаг | Команда / действие |
|-----|---------------------|
| 1 | Задать `DATABASE_URL` (см. варианты выше) |
| 2 | `cd Игра/бэкенд` → `pip3 install -r requirements.txt` → `uvicorn api.main:app --reload --port 8000` |
| 3 | В другом терминале: `cd Игра` → `python3 -m http.server 8080` |
| 4 | В HTML выставить `API_BASE: 'http://localhost:8000'` |
| 5 | Открыть http://localhost:8080/village-era-game-final.html |
