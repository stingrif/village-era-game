# 30. Admin API Тигрит

Базовый URL: `https://tigrit.stakingphxpw.com`

Авторизация: заголовок `X-Admin-Key: YOUR_ADMIN_KEY`  
(`YOUR_ADMIN_KEY` = значение переменной окружения `TIGRIT_ADMIN_API_KEY` на сервере)

Все endpoint'ы требуют заголовок кроме `/status` (он возвращает db_connected без ключа).

---

## Эндпоинты

### GET /api/admin/status
Проверка доступности API. Не требует ключа для базовой проверки.

```bash
curl -s https://tigrit.stakingphxpw.com/api/admin/status \
  -H "X-Admin-Key: YOUR_ADMIN_KEY"
```

Ответ:
```json
{
  "ok": true,
  "admin_key_configured": true,
  "key_valid": true,
  "db_connected": true,
  "village_exists": true,
  "server_time": "2026-02-23T12:00:00Z"
}
```

---

### GET /api/admin/village/1
Полные данные деревни (включая name, xp, population_max).

```bash
curl -s https://tigrit.stakingphxpw.com/api/admin/village/1 \
  -H "X-Admin-Key: YOUR_ADMIN_KEY"
```

Ответ 200:
```json
{
  "id": 1, "name": "Тигрит", "level": 7, "xp": 630,
  "activity": 84, "population": 34, "population_max": 50,
  "build_name": "Рыночная площадь", "build_progress": 63,
  "resources": {"wood": 340, "stone": 120, "gold": 890, "food": 210, "influence": 45}
}
```

---

### PATCH /api/admin/village/1
Изменить поля деревни без проверки ресурсов.

```bash
curl -s -X PATCH https://tigrit.stakingphxpw.com/api/admin/village/1 \
  -H "X-Admin-Key: YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"level": 10, "xp": 0, "name": "Тигрит Великий"}'
```

Допустимые поля: `name`, `level`, `xp`, `activity`, `population`, `population_max`, `build_name`, `build_progress`, `resources`

Ответ 200: `{"ok": true, "updated_fields": ["level","xp","name"], "village": {...}}`

Ошибки:
- `422` — колонка отсутствует (нужна миграция)
- `503` — БД недоступна
- `401` — неверный ключ

---

### POST /api/admin/village/1/activate
Быстрые активации без редактирования полей.

```bash
# Завершить стройку
curl -s -X POST https://tigrit.stakingphxpw.com/api/admin/village/1/activate \
  -H "X-Admin-Key: YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"action": "build_complete"}'
```

Допустимые `action`:

| action | Эффект |
|--------|--------|
| `build_complete` | build_progress → 100% |
| `build_reset` | build_progress → 0% |
| `resources_fill` | wood/stone/gold/food/influence → max |
| `level_up` | level+1, xp=0 |
| `activity_reset` | activity → 0 |

Ответ: `{"ok": true, "action": "build_complete", "village": {...}}`

---

### GET /api/admin/users
Список игроков с поиском по username.

```bash
# Поиск по нику
curl -s "https://tigrit.stakingphxpw.com/api/admin/users?search=Aldric&limit=10" \
  -H "X-Admin-Key: YOUR_ADMIN_KEY"
```

Ответ: `{"total": 1, "players": [{"user_id": 123, "username": "Aldric", "level": 12, ...}]}`

---

### GET /api/admin/user/{user_id}
Профиль конкретного игрока.

```bash
curl -s https://tigrit.stakingphxpw.com/api/admin/user/123 \
  -H "X-Admin-Key: YOUR_ADMIN_KEY"
```

---

### PATCH /api/admin/user/{user_id}
Прокачать игрока без проверки ресурсов.

```bash
curl -s -X PATCH https://tigrit.stakingphxpw.com/api/admin/user/123 \
  -H "X-Admin-Key: YOUR_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{"xp": 5000, "level": 12, "race": "Elf"}'
```

Допустимые поля: `xp`, `level`, `race`, `clazz`, `job`

Ошибки:
- `404` + hint — игрок не найден
- `422` + field — ошибка валидации
- `200` + `user` — текущие данные после UPDATE

---

## Переменные окружения

| Переменная | Где используется |
|------------|-----------------|
| `TIGRIT_ADMIN_API_KEY` | Admin API (`X-Admin-Key`) |
| `EDITOR_API_KEY` | PUT /api/map (редактор карты, `X-API-Key`) |
| `DATABASE_URL` | asyncpg пул подключения |
| `CORS_ORIGINS` | CORS: через запятую, включая `https://tigrit.stakingphxpw.com` |

---

## Миграция перед первым деплоем

```bash
# На сервере — применить SQL-миграции
docker exec stakingphxpw-tigrit-api python3 backend/run_migrations.py
```

Логи: `[OK] 001_tigrit_village_extend.sql [OK] 002_tigrit_interactions_ensure.sql`
