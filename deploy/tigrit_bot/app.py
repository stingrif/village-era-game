import os, asyncio, random, logging, time, math, json
from pathlib import Path
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

from db_async import (
    ensure_tigrit_profile,
    get_profile,
    gain_xp_and_level,
    get_persona_prompt,
    get_setting,
    set_setting,
    upsert_chat,
    execute,
    query_one,
    query_all,
    fetchval,
    top_users,
    get_village_row,
    get_feathers_balance,
    get_user_id,
)
from llm import chat

# Загружаем .env из корня проекта (если есть) и из папки скрипта
load_dotenv()  # ./.env
load_dotenv(Path(__file__).with_name('.env'), override=True)  # ./tigrit_village/.env имеет приоритет
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tigrit")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
AGENT_REPLY_CHANCE = float(os.getenv("AGENT_REPLY_CHANCE", "0.2"))
TICK_SECONDS = int(os.getenv("TICK_SECONDS", "60"))
MEETINGS_PER_TICK = int(os.getenv("MEETINGS_PER_TICK", "1"))
LLM_API_BASE = os.getenv("LLM_API_BASE", "http://127.0.0.1:11434/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.2-3B-instruct:Q4_K_S")

# Интерактивные события
DAILY_EVENTS_MIN = int(os.getenv("DAILY_EVENTS_MIN", "2"))
DAILY_EVENTS_MAX = int(os.getenv("DAILY_EVENTS_MAX", "3"))
EVENT_JOIN_WINDOW_MINUTES = int(os.getenv("EVENT_JOIN_WINDOW_MINUTES", "15"))

if not TOKEN or not isinstance(TOKEN, str):
    raise ValueError("TELEGRAM_BOT_TOKEN не задан. Создайте файл tigrit_village/.env с TELEGRAM_BOT_TOKEN=... либо экспортируйте переменную окружения.")

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Оформление сообщений в стиле проекта
PHX_BUY = "https://app.ston.fi/swap?ft=TON&tt=EQABtSLSzrAOISWPfIjBl2VmeStkM1eHaPrUxRTj8mY-9h43&chartVisible=false&chartInterval=1w"
PHX_STAKE = "https://tonraffles.app/jetton/staking/Phxpw"

def themed(text: str) -> str:
    header = "🔥❄️ <b>Деревня Тигрит</b> | Дыхание Феникса ❄️🔥"
    footer = f"\n\n🔥 PHXPW: Купить ({PHX_BUY}) • Стейкинг ({PHX_STAKE})"
    return f"{header}\n{text}{footer}"

MSG_UNAVAILABLE = "Сервис игры временно недоступен. Попробуйте позже."

async def _ensure_home_chat(chat_id: int):
    home = await get_setting("home_chat_id")
    if not home:
        await set_setting("home_chat_id", str(chat_id))

@dp.message(CommandStart())
async def start(m: types.Message):
    if await ensure_tigrit_profile(m.from_user.id, m.from_user.username) is None:
        await m.answer(MSG_UNAVAILABLE)
        return
    prof = await get_profile(m.from_user.id)
    if not prof:
        await m.answer(MSG_UNAVAILABLE)
        return
    if m.chat.type == 'private':
        text = (f"<b>Добро пожаловать в деревню Тигрит!</b>\n"
                f"Твоя раса: <b>{prof['race']}</b>\n"
                f"Класс: <b>{prof['clazz']}</b>\n\n"
                f"Добавь меня в группу/канал и запусти там /bind, либо пришли ссылку приглашения командой:\n"
                f"/group https://t.me/…")
    else:
        text = (f"<b>Добро пожаловать в деревню Тигрит!</b>\n"
                f"Твоя раса: <b>{prof['race']}</b>\n"
                f"Класс: <b>{prof['clazz']}</b>\n"
                f"Пиши в чат — получай XP и развивайся. Команды: /me, /top, /village, /bind")
    await m.answer(text)

@dp.message(Command("bind"))
async def bind_here(m: types.Message):
    await upsert_chat(chat_id=m.chat.id, type_=m.chat.type, title=m.chat.title or m.chat.full_name or "")
    await m.answer("Этот чат подключён для сбора активности и начисления XP участникам. Я буду слушать сообщения здесь. Если нужно публиковать фоновые события — также можно привязать этот чат как домашний (сейчас он им и является).")

@dp.message(Command("home"))
async def set_home_chat(m: types.Message):
    await set_setting("home_chat_id", str(m.chat.id))
    await upsert_chat(chat_id=m.chat.id, type_=m.chat.type, title=m.chat.title or m.chat.full_name or "")
    await m.answer("Этот чат привязан как домашний. Фоновые события и диалоги будут публиковаться здесь.")

@dp.message(Command("group"))
async def save_group_link(m: types.Message):
    if m.chat.type != 'private':
        return
    parts = (m.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await m.answer("Пришли ссылку приглашения после команды. Пример:\n/group https://t.me/+AbCdEf...")
        return
    link = parts[1].strip()
    await set_setting(f"invite_link_{m.from_user.id}", link)
    await m.answer("Сохранил ссылку. Добавь меня в эту группу и выполни там /bind, чтобы я начал слушать и начислять XP.")

@dp.message(Command("me"))
async def me(m: types.Message):
    if await ensure_tigrit_profile(m.from_user.id, m.from_user.username) is None:
        await m.answer(MSG_UNAVAILABLE)
        return
    prof = await get_profile(m.from_user.id)
    if not prof:
        await m.answer(MSG_UNAVAILABLE)
        return
    text = (f"<b>@{prof['username'] or 'игрок'}</b>\n"
            f"Раса: {prof['race']} | Класс: {prof['clazz']}\n"
            f"XP: {prof['xp']} | Уровень: {prof['level']}\n"
            f"Дом: {prof['house']} | Работа: {prof['job']} | Друзья: {prof['friends']}")
    await m.answer(text)

@dp.message(Command("top"))
async def top(m: types.Message):
    rows = await top_users(10)
    if not rows:
        await m.answer("Ещё нет игроков.")
        return
    text = "<b>🏆 Топ игроков:</b>\n"
    for i, (username, xp) in enumerate(rows, 1):
        text += f"{i}. @{username or 'anon'} — {xp} XP\n"
    await m.answer(text)

@dp.message(Command("village"))
async def village_status(m: types.Message):
    row = await get_village_row()
    if not row:
        await m.answer("Деревня не инициализирована.")
        return
    lvl, act, res, pop, bname, bprog = row["level"], row["activity"], row["resources"], row["population"], row["build_name"], row["build_progress"]
    await m.answer(f"🌳 <b>Деревня Тигрит</b>\n"
                   f"Уровень деревни: {lvl}\n"
                   f"Активность: {act}\n"
                   f"Ресурсы: {res}\n"
                   f"Население: {pop}\n"
                   f"Стройка: {bname} ({bprog}%)")

@dp.message(Command("help"))
async def help_cmd(m: types.Message):
    text = (
        "Команды бота\n\n"
        "Общие: /start, /help, /top, /village\n"
        "Профиль: /me, /balance\n"
        "Друзья: /friends, /addfriend @username (или ответом на сообщение)\n"
        "Проект: /god\n"
        "Админ: /bind , /home, /group, /makeadmin @username, /privatechat, /adduser @username, /listusers, /removeuser ID, /admins, /access, /syncpull, /syncpush\n\n"
        "Доступ к личным и дружеским командам есть только у админов/вайтлиста/членов приватной группы."
    )
    await m.answer(themed(text))

@dp.message(Command("feathers"))
async def feathers_cmd(m: types.Message):
    """Показывает актуальный баланс перьев. Источник: БД или Google Sheets (если FEATHERS_SOURCE=sheets)."""
    uid = m.from_user.id
    source = (os.getenv("FEATHERS_SOURCE", "db") or "db").lower()
    feathers_val = None

    if source == "sheets":
        try:
            # Прямое чтение из Google Sheets без кэша
            sid = os.getenv("GOOGLE_SPREADSHEET_ID")
            if not sid:
                raise RuntimeError("GOOGLE_SPREADSHEET_ID не задан")
            import gspread
            from google.oauth2.service_account import Credentials
            creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
            if creds_json:
                import json
                data = json.loads(creds_json)
                scopes = [
                    "https://www.googleapis.com/auth/spreadsheets.readonly",
                    "https://www.googleapis.com/auth/drive.readonly",
                ]
                creds = Credentials.from_service_account_info(data, scopes=scopes)
            else:
                path = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")
                scopes = [
                    "https://www.googleapis.com/auth/spreadsheets.readonly",
                    "https://www.googleapis.com/auth/drive.readonly",
                ]
                creds = Credentials.from_service_account_file(path, scopes=scopes)
            gc = gspread.authorize(creds)
            sh = gc.open_by_key(sid)
            ws = sh.worksheet("users")
            values = ws.get_all_records()
            for r in values:
                try:
                    if int(r.get("user_id") or 0) == int(uid):
                        feathers_val = int(r.get("feathers") or 0)
                        break
                except Exception:
                    continue
        except Exception as e:
            log.error(f"feathers sheets read error: {e}")

    if feathers_val is None:
        feathers_val = await get_feathers_balance(uid)

    await m.answer(f"🪶 Перья: <b>{feathers_val}</b>")

@dp.message()
async def on_msg(m: types.Message):
    if not m.text or len(m.text.strip()) < 5:
        return

    # Быстрая обработка ручного спавна ивента через общий хендлер (на случай приоритета)
    try:
        if m.text.strip().split()[0].split('@',1)[0] == '/spawn_event':
            await spawn_event_command(m)
            return
    except Exception:
        pass

    user_id = await ensure_tigrit_profile(m.from_user.id, m.from_user.username)
    if user_id is None:
        return
    try:
        zone_row = await query_one(
            "SELECT zone_id FROM zones WHERE tg_chat_id = $1 LIMIT 1",
            int(m.chat.id),
        )
        zone_id = zone_row["zone_id"] if zone_row else None
        payload = json.dumps(
            {
                "text": (m.text or "")[:200],
                "zone_id": zone_id,
                "chat_id": int(m.chat.id),
                "username": m.from_user.username or "",
            },
            ensure_ascii=False,
        )
        await execute(
            "INSERT INTO tigrit_interactions(kind, actor_id, target_id, payload) VALUES ($1,$2,$3,$4)",
            "msg", user_id, None, payload,
        )
        if zone_id:
            await execute(
                """
                UPDATE tigrit_user_profile
                SET home_zone_first_activity_at = COALESCE(home_zone_first_activity_at, NOW()),
                    trust_score = GREATEST(-100, LEAST(100, COALESCE(trust_score, 50) + 2))
                WHERE user_id = $1
                  AND home_zone_id = $2
                """,
                user_id,
                zone_id,
            )
            await execute(
                """
                INSERT INTO game_events(user_id, event_type, reason_code, payload, created_at)
                VALUES ($1, 'trust_change', 'zone_chat_activity', $2, NOW())
                """,
                user_id,
                json.dumps({"delta": 2, "zone_id": zone_id}, ensure_ascii=False),
            )
        await upsert_chat(chat_id=m.chat.id, type_=m.chat.type, title=m.chat.title or m.chat.full_name or "")
    except Exception:
        pass
    res = await gain_xp_and_level(m.from_user.id)
    if res:
        xp, lvl = res
        if xp % 250 == 0:
            await m.answer(f"✨ Прогресс @{m.from_user.username}: XP={xp}, уровень={lvl}")

    if random.random() < AGENT_REPLY_CHANCE:
        persona = await get_persona_prompt(m.from_user.id)
        if persona:
            text = chat(system=persona, user=f"Коротко ответь на сообщение игрока: «{m.text.strip()}».", max_tokens=80)
            if text:
                await m.answer(f"<i>{text}</i>")

def _today_key() -> str:
    return time.strftime('%Y-%m-%d', time.localtime())

async def _reset_daily_event_counters_if_needed():
    today = _today_key()
    cur = await get_setting("daily_events_date")
    if cur != today:
        await set_setting("daily_events_date", today)
        target = random.randint(DAILY_EVENTS_MIN, DAILY_EVENTS_MAX)
        await set_setting("daily_events_target", str(target))
        await set_setting("daily_events_done", "0")
        await set_setting("last_event_created_ts", "0")

async def _spawn_interactive_event(chat_id: int):
    """Создаёт интерактивный ивент и публикует сообщение с кнопками участия."""
    # Пул названий событий
    titles = [
        "Вылазка в руины",
        "Оборона ворот",
        "Охота в зачарованном лесу",
        "Экспедиция к источнику",
        "Поиск пропавшего купца",
        "Ремонт моста через реку",
    ]
    title = random.choice(titles)

    # Эффект по умолчанию: XP, величина 10–30; знак определится при завершении
    effect_type = "xp"
    effect_value = random.randint(10, 30)
    start_ts = int(time.time())
    end_ts = start_ts + EVENT_JOIN_WINDOW_MINUTES * 60

    event_id = await fetchval(
        """INSERT INTO tigrit_events(title, effect_type, effect_sign, effect_value, chat_id, message_id, start_ts, end_ts, status)
           VALUES($1,$2,$3,$4,$5,$6,$7,$8,'active') RETURNING id""",
        title, effect_type, 0, effect_value, int(chat_id), 0, start_ts, end_ts,
    )
    event_id = int(event_id) if event_id else 0

    # Кнопки участия
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="✅ Участвую", callback_data=f"event:join:{event_id}"),
            types.InlineKeyboardButton(text="✖️ Пропустить", callback_data=f"event:skip:{event_id}"),
        ]
    ])

    text = (
        f"🎲 <b>Ивент:</b> {title}\n"
        f"Окно участия: {EVENT_JOIN_WINDOW_MINUTES} минут. Нажмите кнопку ниже, чтобы присоединиться.\n"
        f"Итог может быть положительным или отрицательным и затронет только участников."
    )
    try:
        msg = await bot.send_message(int(chat_id), text, reply_markup=kb)
    except (TelegramBadRequest, TelegramAPIError) as e:
        log.error(f"spawn event send_message failed: chat_id={chat_id}, err={e}")
        await execute("UPDATE tigrit_events SET status='finished' WHERE id=$1", int(event_id))
        return

    await execute("UPDATE tigrit_events SET message_id=$1 WHERE id=$2", int(msg.message_id), int(event_id))
    await set_setting("last_event_created_ts", str(start_ts))
    done = int(await get_setting("daily_events_done") or 0)
    await set_setting("daily_events_done", str(done + 1))

async def _finalize_event(event_row):
    """Закрывает ивент по окончании окна участия и применяет эффекты участникам."""
    event_id, title, effect_type, effect_sign, effect_value, chat_id, message_id, start_ts, end_ts, status = event_row
    if status != 'active':
        return
    now = int(time.time())
    end_ts_int = int(end_ts or 0)
    if now < end_ts_int:
        return

    sign = 1 if random.random() < 0.6 else -1
    await execute("UPDATE tigrit_events SET effect_sign=$1, status='finished' WHERE id=$2", sign, event_id)

    participants = await query_all("SELECT user_id FROM tigrit_event_participants WHERE event_id=$1 AND decision='join'", event_id)
    user_ids = [r["user_id"] for r in participants]

    affected = []
    for uid in user_ids:
        try:
            row = await query_one("SELECT xp FROM tigrit_user_profile WHERE user_id=$1", int(uid))
            old_xp = int(row["xp"]) if row and row["xp"] is not None else 0
            delta = int(sign) * int(effect_value)
            new_xp = max(0, old_xp + delta)
            new_level = int(math.floor(math.sqrt(new_xp / 50)))
            await execute("UPDATE tigrit_user_profile SET xp=$2, level=$3 WHERE user_id=$1", int(uid), new_xp, new_level)
            affected.append((int(uid), delta, new_xp))
        except (ValueError, Exception) as e:
            log.error(f"apply effect failed: event_id={event_id}, uid={uid}, err={e}")

    # Убираем кнопки у исходного сообщения
    try:
        await bot.edit_message_reply_markup(chat_id=int(chat_id), message_id=int(message_id), reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[]))
    except (TelegramBadRequest, TelegramAPIError) as e:
        log.debug(f"edit markup failed (maybe already edited): event_id={event_id}, err={e}")

    # Публикуем результат
    if affected:
        names = []
        for uid, delta, new_xp in affected[:10]:
            u = await query_one("SELECT username FROM tigrit_user_profile WHERE user_id=$1", uid)
            uname = u["username"] if u and u["username"] else str(uid)
            sign_sym = "+" if delta > 0 else ""
            names.append(f"@{uname}: {sign_sym}{delta} XP")
        more = '' if len(affected) <= 10 else f"\n... и ещё {len(affected) - 10} участника(ов)"
        outcome = "положительный" if sign > 0 else "негативный"
        summary = (
            f"🧭 <b>Ивент завершён:</b> {title}\n"
            f"Итог: {outcome}. Эффект на участников: {('+' if sign>0 else '')}{sign*effect_value} XP каждому.\n"
            + "\n".join(names) + more
        )
    else:
        summary = f"🧭 <b>Ивент завершён:</b> {title}\nНикто не принял участие."

    try:
        await bot.send_message(int(chat_id), summary)
    except (TelegramBadRequest, TelegramAPIError) as e:
        log.error(f"send summary failed: event_id={event_id}, err={e}")

async def _finalize_expired_events():
    rows = await query_all(
        "SELECT id, title, effect_type, effect_sign, effect_value, chat_id, message_id, start_ts, end_ts, status FROM tigrit_events WHERE status='active'"
    )
    now = int(time.time())
    for r in rows:
        end_ts = r["end_ts"] or 0
        if end_ts > 0 and now >= int(end_ts):
            await _finalize_event((r["id"], r["title"], r["effect_type"], r["effect_sign"], r["effect_value"], r["chat_id"], r["message_id"], r["start_ts"], r["end_ts"], r["status"]))

@dp.message(Command("spawn_event"))
async def spawn_event_command(m: types.Message):
    try:
        member = await bot.get_chat_member(m.chat.id, m.from_user.id)
        if getattr(member, "status", None) not in ("administrator", "creator"):
            await m.answer("❌ Только администраторы могут запускать ивенты вручную.")
            return
    except Exception as e:
        log.warning(f"spawn_event: can't verify admin rights in chat {m.chat.id}: {e}. Proceeding anyway.")

    home_chat = await get_setting("home_chat_id")
    if not home_chat:
        await set_setting("home_chat_id", str(m.chat.id))
        home_chat = str(m.chat.id)

    await _spawn_interactive_event(int(home_chat))
    await m.answer("✅ Ивент создан и отправлен в домашний чат.")

@dp.callback_query()
async def on_event_callback(c: types.CallbackQuery):
    """Обработка нажатий на кнопки ивента (участие/пропуск) с валидацией и логированием."""
    data = c.data or ""
    try:
        log.info(f"cbq from uid={c.from_user.id} chat={getattr(c.message.chat, 'id', None)} data={data}")
    except Exception:
        pass
    if not data.startswith("event:"):
        return
    parts = data.split(":")
    if len(parts) != 3:
        await c.answer("Ошибка данных", show_alert=False)
        return
    action, event_id_str = parts[1], parts[2]
    if action not in ("join", "skip"):
        await c.answer("Неизвестное действие", show_alert=False)
        return
    try:
        event_id = int(event_id_str)
    except ValueError:
        await c.answer("Некорректный ивент", show_alert=False)
        return

    try:
        row = await query_one("SELECT id, chat_id, end_ts, status, message_id FROM tigrit_events WHERE id=$1", event_id)
    except Exception as e:
        log.error(f"event fetch failed: event_id={event_id}, err={e}")
        await c.answer("Ошибка сервера", show_alert=False)
        return
    if not row:
        await c.answer("Ивент не найден", show_alert=False)
        return
    chat_id, end_ts, status, message_id = row["chat_id"], row["end_ts"], row["status"], row["message_id"]
    now = int(time.time())
    end_ts_int = int(end_ts or 0)
    if status != 'active' or now >= end_ts_int:
        await c.answer("Ивент уже завершён", show_alert=False)
        return

    decision = 'join' if action == 'join' else 'skip'
    try:
        uid = await get_user_id(c.from_user.id)
        if uid is None:
            await c.answer(MSG_UNAVAILABLE, show_alert=True)
            return
        await execute(
            """INSERT INTO tigrit_event_participants(event_id, user_id, decision, ts) VALUES($1,$2,$3,$4)
               ON CONFLICT(event_id, user_id) DO UPDATE SET decision=EXCLUDED.decision, ts=EXCLUDED.ts""",
            event_id, uid, decision, now,
        )
        r_join = await query_one("SELECT COUNT(1) AS c FROM tigrit_event_participants WHERE event_id=$1 AND decision='join'", event_id)
        r_skip = await query_one("SELECT COUNT(1) AS c FROM tigrit_event_participants WHERE event_id=$1 AND decision='skip'", event_id)
        cnt_join = r_join["c"] if r_join else 0
        cnt_skip = r_skip["c"] if r_skip else 0
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [
                types.InlineKeyboardButton(text=f"✅ Участвую ({cnt_join})", callback_data=f"event:join:{event_id}"),
                types.InlineKeyboardButton(text=f"✖️ Пропустить ({cnt_skip})", callback_data=f"event:skip:{event_id}"),
            ]
        ])
        try:
            await bot.edit_message_reply_markup(chat_id=int(chat_id), message_id=int(message_id), reply_markup=kb)
        except (TelegramBadRequest, TelegramAPIError) as e:
            log.debug(f"cbq edit markup counts failed: event_id={event_id}, err={e}")
        await c.answer("Выбор сохранён", show_alert=False)
    except Exception as e:
        log.error(f"save decision failed: event_id={event_id}, uid={c.from_user.id}, err={e}")
        await c.answer("Не удалось сохранить", show_alert=False)

async def village_loop():
    while True:
        await asyncio.sleep(TICK_SECONDS)

        # Сообщения от деревенских событий и диалоги между жителями.
        # Заполняются при реализации village_tick и simulate_agents (Фаза расширения Тигрит).
        msgs: list = []
        meetings: list = []

        home_chat = await get_setting("home_chat_id")
        if not home_chat:
            continue

        try:
            await _finalize_expired_events()

            await _reset_daily_event_counters_if_needed()
            target = int(await get_setting("daily_events_target") or DAILY_EVENTS_MIN)
            done = int(await get_setting("daily_events_done") or 0)
            last_created = int(await get_setting("last_event_created_ts") or 0)
            hours_since_last = (int(time.time()) - last_created) / 3600 if last_created else 999
            if done < target and hours_since_last >= 2:
                # шансы по часу ~40% спавна при невыполненной квоте
                if random.random() < 0.4:
                    await _spawn_interactive_event(int(home_chat))

            for text in msgs:
                await bot.send_message(int(home_chat), text)
                await asyncio.sleep(1)

            for kind, a, b, lines in meetings:
                if kind == "solo":
                    await bot.send_message(int(home_chat), f"💬 <i>{lines[0]}</i>")
                else:
                    await bot.send_message(int(home_chat), f"🤝 <i>{lines[0]}</i>")
                    if len(lines) > 1:
                        await asyncio.sleep(1)
                        await bot.send_message(int(home_chat), f"🤝 <i>{lines[1]}</i>")
                await asyncio.sleep(1)
        except Exception as e:
            log.error(f"publish fail: {e}")

async def main():
    asyncio.create_task(village_loop())
    log.info("Бот запущен (общая БД с Игра).")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


