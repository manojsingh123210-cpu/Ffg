#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XYVEN PREMIUM REFER & EARN
Single-file Telegram Refer & Earn Bot + Flask Admin Dashboard.

- Flask (WSGI / Gunicorn) is the only public HTTP server on $PORT.
- /telegram/webhook/<secret> feeds updates into an aiogram Dispatcher
  running on a dedicated asyncio thread.
- SQLite with WAL, foreign keys, and explicit transactions.
- Money stored as integer paise (₹1 = 100 paise).
"""

from __future__ import annotations

import asyncio
import atexit
import html as html_lib
import json
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
)
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    ChatJoinRequest,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template_string,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

# ---------------------------------------------------------------------------
# 1. CONFIGURATION
# ---------------------------------------------------------------------------

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}
if not ADMIN_IDS:
    raise RuntimeError("ADMIN_IDS must contain numeric Telegram user IDs.")

DATABASE_PATH: str = os.getenv("DATABASE_PATH", "/var/data/xyven.db").strip()
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "").strip().rstrip("/")
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "").strip()
if not WEBHOOK_SECRET:
    WEBHOOK_SECRET = secrets.token_urlsafe(32)
    logging.warning("WEBHOOK_SECRET not set; using ephemeral secret.")

DASHBOARD_USERNAME: str = os.getenv("DASHBOARD_USERNAME", "admin").strip()
DASHBOARD_PASSWORD_HASH: str = os.getenv("DASHBOARD_PASSWORD_HASH", "").strip()
if not DASHBOARD_PASSWORD_HASH:
    _dev = os.getenv("DASHBOARD_PASSWORD", "change-me-now")
    DASHBOARD_PASSWORD_HASH = generate_password_hash(_dev)
    logging.warning("DASHBOARD_PASSWORD_HASH not set; using development default.")

SESSION_SECRET: str = os.getenv("SESSION_SECRET", "").strip()
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_urlsafe(48)
    logging.warning("SESSION_SECRET not set; using ephemeral secret.")

PORT: int = int(os.getenv("PORT", "8080"))
REFERRAL_REWARD_PAISE: int = int(os.getenv("REFERRAL_REWARD_PAISE", "200"))
MIN_WITHDRAWAL_PAISE: int = int(os.getenv("MIN_WITHDRAWAL_PAISE", "1000"))
BROADCAST_DELAY_SECONDS: float = float(os.getenv("BROADCAST_DELAY_SECONDS", "0.05"))

_db_dir = os.path.dirname(DATABASE_PATH)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("xyven")

# ---------------------------------------------------------------------------
# 2. PREMIUM CUSTOM EMOJI LAYER
# ---------------------------------------------------------------------------

EMOJI_IDS: List[str] = [
    "5357592447557848986", "5258387666616994756", "5391118489824015979",
    "5334665104677941170", "5289862389552919154", "5397730656400714154",
    "5301275719681190738", "5301096984617166561", "5386521874089914548",
    "5332423642850536254", "5264892613630111886", "5258113901106580375",
    "5258212320282168974", "5258274739041883702", "5258457030338844822",
    "5260373152688540294", "5258420785109830474", "5258178411515382761",
    "5260691173541970181", "6014620343883273557", "6015104451122042405",
    "6104794084205925773", "6104675564583392962", "6107015024679592166",
    "6120548140211770562",
]

class E:
    CROWN = EMOJI_IDS[0]
    USER = EMOJI_IDS[1]
    GIFT = EMOJI_IDS[2]
    MONEY = EMOJI_IDS[3]
    WALLET = EMOJI_IDS[4]
    CARD = EMOJI_IDS[5]
    CHART = EMOJI_IDS[6]
    LINK = EMOJI_IDS[7]
    SHARE = EMOJI_IDS[8]
    CHECK = EMOJI_IDS[9]
    CROSS = EMOJI_IDS[10]
    INFO = EMOJI_IDS[11]
    SUPPORT = EMOJI_IDS[12]
    BELL = EMOJI_IDS[13]
    LOCK = EMOJI_IDS[14]
    KEY = EMOJI_IDS[15]
    SETTINGS = EMOJI_IDS[16]
    MEGAPHONE = EMOJI_IDS[17]
    STATS = EMOJI_IDS[18]
    STAR = EMOJI_IDS[19]
    DIAMOND = EMOJI_IDS[20]
    ROCKET = EMOJI_IDS[21]
    SHIELD = EMOJI_IDS[22]
    CLOCK = EMOJI_IDS[23]
    FIRE = EMOJI_IDS[24]

_FALLBACKS = {
    E.CROWN: "👑", E.USER: "👤", E.GIFT: "🎁", E.MONEY: "💰",
    E.WALLET: "👛", E.CARD: "💳", E.CHART: "📊", E.LINK: "🔗",
    E.SHARE: "📤", E.CHECK: "✅", E.CROSS: "❌", E.INFO: "ℹ️",
    E.SUPPORT: "🛟", E.BELL: "🔔", E.LOCK: "🔒", E.KEY: "🔑",
    E.SETTINGS: "⚙️", E.MEGAPHONE: "📣", E.STATS: "📈", E.STAR: "⭐",
    E.DIAMOND: "💎", E.ROCKET: "🚀", E.SHIELD: "🛡️", E.CLOCK: "⏰",
    E.FIRE: "🔥",
}

def ce(emoji_id: str, fallback: Optional[str] = None) -> str:
    safe_id = re.sub(r"[^0-9]", "", str(emoji_id))
    if not safe_id:
        return fallback or "✨"
    fb = fallback or _FALLBACKS.get(emoji_id, "✨")
    return f'<tg-emoji emoji-id="{safe_id}">{fb}</tg-emoji>'

def strip_premium_html(text: str) -> str:
    return re.sub(r"<tg-emoji[^>]*>(.*?)</tg-emoji>", r"\1", text, flags=re.S)

class _TagStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: List[str] = []
    def handle_data(self, data: str) -> None:
        self._parts.append(data)
    def get_text(self) -> str:
        return "".join(self._parts)

def plain_text(text: str) -> str:
    stripped = strip_premium_html(text)
    parser = _TagStripper()
    try:
        parser.feed(stripped)
        return parser.get_text()
    except Exception:
        return html_lib.unescape(re.sub(r"<[^>]+>", "", stripped))

def he(value: Any) -> str:
    return html_lib.escape(str(value), quote=False)

# ---------------------------------------------------------------------------
# 3. DATABASE LAYER
# ---------------------------------------------------------------------------

_db_lock = threading.RLock()

@contextmanager
def db():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")
    try:
        yield conn
    finally:
        conn.close()

def init_db() -> None:
    with _db_lock, db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                referred_by INTEGER,
                referral_count INTEGER NOT NULL DEFAULT 0,
                successful_referrals INTEGER NOT NULL DEFAULT 0,
                balance_paise INTEGER NOT NULL DEFAULT 0,
                reserved_paise INTEGER NOT NULL DEFAULT 0,
                total_earned_paise INTEGER NOT NULL DEFAULT 0,
                total_withdrawn_paise INTEGER NOT NULL DEFAULT 0,
                is_verified INTEGER NOT NULL DEFAULT 0,
                is_banned INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                reward_paise INTEGER NOT NULL DEFAULT 200,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                credited_at TEXT,
                FOREIGN KEY (referrer_id) REFERENCES users(user_id),
                FOREIGN KEY (referred_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount_paise INTEGER NOT NULL,
                description TEXT,
                reference_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount_paise INTEGER NOT NULL,
                upi_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                processed_at TEXT,
                admin_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            CREATE TABLE IF NOT EXISTS promo_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE,
                username TEXT,
                title TEXT,
                invite_link TEXT,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                auto_approve INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id);
            CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
            CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals(status);
        """)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                     ("referral_reward_paise", str(REFERRAL_REWARD_PAISE)))
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                     ("min_withdrawal_paise", str(MIN_WITHDRAWAL_PAISE)))
        for admin_id in ADMIN_IDS:
            conn.execute("INSERT OR IGNORE INTO admins(user_id, added_at) VALUES(?, ?)",
                         (admin_id, now))

def db_one(sql: str, params: Tuple[Any, ...] = ()) -> Optional[sqlite3.Row]:
    with _db_lock, db() as conn:
        return conn.execute(sql, params).fetchone()

def db_all(sql: str, params: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
    with _db_lock, db() as conn:
        return conn.execute(sql, params).fetchall()

def get_setting(key: str, default: str = "") -> str:
    row = db_one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else default

def get_setting_int(key: str, default: int = 0) -> int:
    try:
        return int(get_setting(key, str(default)))
    except (TypeError, ValueError):
        return default

def set_setting(key: str, value: str) -> None:
    with _db_lock, db() as conn:
        conn.execute("INSERT INTO settings(key, value) VALUES(?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def fmt_inr(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"

def get_user(user_id: int) -> Optional[sqlite3.Row]:
    return db_one("SELECT * FROM users WHERE user_id=?", (user_id,))

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def create_user(user_id: int, username: Optional[str], first_name: Optional[str],
                referred_by: Optional[int] = None) -> bool:
    with _db_lock, db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            if conn.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,)).fetchone():
                conn.execute("COMMIT")
                return False
            conn.execute("INSERT INTO users(user_id, username, first_name, referred_by, created_at) "
                         "VALUES(?, ?, ?, ?, ?)", (user_id, username, first_name, referred_by, now_iso()))
            if (referred_by and referred_by != user_id and
                conn.execute("SELECT 1 FROM users WHERE user_id=?", (referred_by,)).fetchone()):
                conn.execute("INSERT OR IGNORE INTO referrals "
                             "(referrer_id, referred_id, reward_paise, status, created_at) "
                             "VALUES(?, ?, ?, 'pending', ?)",
                             (referred_by, user_id,
                              get_setting_int("referral_reward_paise", REFERRAL_REWARD_PAISE), now_iso()))
                conn.execute("UPDATE users SET referral_count = referral_count + 1 WHERE user_id=?",
                             (referred_by,))
            conn.execute("COMMIT")
            return True
        except Exception:
            conn.execute("ROLLBACK")
            raise

def mark_user_verified(user_id: int) -> None:
    with _db_lock, db() as conn:
        conn.execute("UPDATE users SET is_verified=1 WHERE user_id=?", (user_id,))

def qualify_referral(user_id: int) -> Optional[int]:
    referrer_id = None
    with _db_lock, db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            ref = conn.execute("SELECT * FROM referrals WHERE referred_id=? AND status='pending'",
                               (user_id,)).fetchone()
            if not ref:
                conn.execute("COMMIT")
                return None
            user = conn.execute("SELECT is_banned FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not user or user["is_banned"]:
                conn.execute("COMMIT")
                return None
            reward = get_setting_int("referral_reward_paise", REFERRAL_REWARD_PAISE)
            referrer_id = int(ref["referrer_id"])
            conn.execute("UPDATE users SET balance_paise = balance_paise + ?, "
                         "total_earned_paise = total_earned_paise + ?, "
                         "successful_referrals = successful_referrals + 1 "
                         "WHERE user_id=?", (reward, reward, referrer_id))
            conn.execute("UPDATE referrals SET status='credited', reward_paise=?, credited_at=? "
                         "WHERE id=? AND status='pending'",
                         (reward, now_iso(), ref["id"]))
            conn.execute("INSERT INTO transactions (user_id, type, amount_paise, description, "
                         "reference_id, created_at) VALUES(?, 'referral_reward', ?, ?, ?, ?)",
                         (referrer_id, reward, f"Referral reward for user {user_id}",
                          str(user_id), now_iso()))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return referrer_id

def referral_link(user_id: int) -> str:
    username = BOT_USERNAME or "your_bot"
    return f"https://t.me/{username}?start={user_id}"

# ---------------------------------------------------------------------------
# 4. RATE LIMITING
# ---------------------------------------------------------------------------

_rate_buckets: Dict[str, List[float]] = {}
_rate_lock = threading.Lock()

def rate_ok(key: str, limit: int = 8, window: float = 10.0) -> bool:
    now = time.monotonic()
    with _rate_lock:
        bucket = [t for t in _rate_buckets.get(key, []) if now - t < window]
        if len(bucket) >= limit:
            _rate_buckets[key] = bucket
            return False
        bucket.append(now)
        _rate_buckets[key] = bucket
        return True

# ---------------------------------------------------------------------------
# 5. BOT / DISPATCHER INITIALISATION
# ---------------------------------------------------------------------------

LOOP = asyncio.new_event_loop()
BOT: Optional[Bot] = None
DP: Optional[Dispatcher] = None
_bot_ready = threading.Event()

def _start_loop() -> None:
    asyncio.set_event_loop(LOOP)
    LOOP.run_forever()

threading.Thread(target=_start_loop, daemon=True, name="xyven-asyncio").start()

async def _init_bot() -> Tuple[Bot, Dispatcher]:
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    register_handlers(dp, bot)

    sample = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="SERIALIZATION TEST", callback_data="test",
                              style="success", icon_custom_emoji_id=E.CROWN)]
    ])
    log.info("Button serialization check: %s",
             sample.model_dump_json(exclude_none=True, by_alias=True))

    if WEBHOOK_URL:
        url = f"{WEBHOOK_URL}/telegram/webhook/{WEBHOOK_SECRET}"
        await bot.set_webhook(url, secret_token=WEBHOOK_SECRET,
                              allowed_updates=dp.resolve_used_update_types(),
                              drop_pending_updates=False)
        log.info("Webhook set to %s", url)
    else:
        log.warning("WEBHOOK_URL not set. Starting long polling on background loop.")
        asyncio.create_task(dp.start_polling(bot))
    return bot, dp

def _bootstrap_bot() -> None:
    global BOT, DP
    future = asyncio.run_coroutine_threadsafe(_init_bot(), LOOP)
    try:
        BOT, DP = future.result(timeout=90)
    except Exception:
        log.exception("Bot initialisation failed")
        raise
    finally:
        _bot_ready.set()

@atexit.register
def _shutdown() -> None:
    try:
        if BOT is not None:
            asyncio.run_coroutine_threadsafe(BOT.session.close(), LOOP)
        LOOP.call_soon_threadsafe(LOOP.stop)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# 6. KEYBOARD BUILDERS
# ---------------------------------------------------------------------------

def btn(text: str, *, cb: Optional[str] = None, url: Optional[str] = None,
        copy: Optional[str] = None, style: Optional[str] = None,
        emoji_id: Optional[str] = None) -> InlineKeyboardButton:
    kwargs: Dict[str, Any] = {"text": text}
    if cb is not None:
        kwargs["callback_data"] = cb
    if url is not None:
        kwargs["url"] = url
    if copy is not None:
        kwargs["copy_text"] = CopyTextButton(text=copy)
    if style in {"success", "danger", "primary"}:
        kwargs["style"] = style
    if emoji_id:
        kwargs["icon_custom_emoji_id"] = emoji_id
    return InlineKeyboardButton(**kwargs)

def sanitize_kb(kb: Optional[InlineKeyboardMarkup]) -> Optional[InlineKeyboardMarkup]:
    if kb is None:
        return None
    rows = []
    for row in kb.inline_keyboard:
        rows.append([InlineKeyboardButton(text=b.text, callback_data=b.callback_data,
                                          url=b.url, copy_text=b.copy_text) for b in row])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [btn("MY ACCOUNT", cb="menu:account", style="primary", emoji_id=E.USER)],
        [btn("REFER & EARN", cb="menu:refer", style="success", emoji_id=E.GIFT)],
        [btn("MY BALANCE", cb="menu:balance", style="success", emoji_id=E.WALLET)],
        [btn("WITHDRAW", cb="menu:withdraw", style="primary", emoji_id=E.CARD),
         btn("STATISTICS", cb="menu:stats", style="success", emoji_id=E.CHART)],
        [btn("PROMO CHANNELS", cb="menu:channels", style="success", emoji_id=E.MEGAPHONE)],
        [btn("HOW TO USE", cb="menu:howto", style="primary", emoji_id=E.INFO),
         btn("SUPPORT", cb="menu:support", style="success", emoji_id=E.SUPPORT)],
    ]
    if is_admin(user_id):
        rows.append([btn("ADMIN PANEL", cb="adm:dashboard", style="danger", emoji_id=E.SHIELD)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def back_kb(target: str = "menu:main", label: str = "BACK") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn(label, cb=target, style="danger", emoji_id=E.CROSS)]
    ])

def force_join_kb(channels: List[sqlite3.Row]) -> InlineKeyboardMarkup:
    rows = []
    for ch in channels:
        url = ch["invite_link"] or (f"https://t.me/{ch['username']}" if ch["username"] else None)
        if url:
            rows.append([btn(f"JOIN {ch['title'] or 'CHANNEL'}", url=url,
                             style="primary", emoji_id=E.LINK)])
    rows.append([btn("VERIFY JOIN", cb="verify:check", style="success", emoji_id=E.CHECK)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ---------------------------------------------------------------------------
# 7. SAFE SEND / EDIT
# ---------------------------------------------------------------------------

async def safe_send(bot: Bot, chat_id: int, text: str,
                    kb: Optional[InlineKeyboardMarkup] = None, **kwargs: Any) -> Optional[Message]:
    try:
        return await bot.send_message(chat_id, text, reply_markup=kb,
                                      parse_mode=ParseMode.HTML,
                                      disable_web_page_preview=True, **kwargs)
    except TelegramBadRequest as exc:
        log.error("safe_send bad request chat=%s error=%s", chat_id, exc)
        try:
            return await bot.send_message(chat_id, plain_text(text),
                                          reply_markup=sanitize_kb(kb),
                                          parse_mode=None,
                                          disable_web_page_preview=True, **kwargs)
        except Exception:
            log.exception("safe_send fallback failed")
            return None
    except TelegramForbiddenError:
        log.warning("safe_send blocked chat=%s", chat_id)
        return None

async def safe_answer(message: Message, text: str,
                      kb: Optional[InlineKeyboardMarkup] = None, **kwargs: Any) -> Optional[Message]:
    try:
        return await message.answer(text, reply_markup=kb,
                                    disable_web_page_preview=True, **kwargs)
    except TelegramBadRequest as exc:
        log.error("safe_answer bad request error=%s", exc)
        try:
            return await message.answer(plain_text(text), reply_markup=sanitize_kb(kb),
                                        parse_mode=None, disable_web_page_preview=True, **kwargs)
        except Exception:
            log.exception("safe_answer fallback failed")
            return None

async def safe_edit(cb: CallbackQuery, text: str,
                    kb: Optional[InlineKeyboardMarkup] = None) -> None:
    if cb.message is None:
        return
    try:
        await cb.message.edit_text(text, reply_markup=kb,
                                   parse_mode=ParseMode.HTML,
                                   disable_web_page_preview=True)
    except TelegramBadRequest as exc:
        log.error("safe_edit bad request error=%s", exc)
        try:
            await cb.message.edit_text(plain_text(text), reply_markup=sanitize_kb(kb),
                                       parse_mode=None, disable_web_page_preview=True)
        except Exception:
            log.exception("safe_edit fallback failed")

# ---------------------------------------------------------------------------
# 8. FORCE JOIN
# ---------------------------------------------------------------------------

async def enabled_channels() -> List[sqlite3.Row]:
    return db_all("SELECT * FROM promo_channels WHERE is_enabled=1 AND chat_id IS NOT NULL ORDER BY id ASC")

async def missing_channels(bot: Bot, user_id: int) -> List[sqlite3.Row]:
    missing = []
    for ch in await enabled_channels():
        try:
            member = await bot.get_chat_member(int(ch["chat_id"]), user_id)
            if str(member.status) not in {"creator", "administrator", "member"}:
                missing.append(ch)
        except TelegramBadRequest as exc:
            log.warning("Membership check failed channel=%s user=%s error=%s",
                        ch["chat_id"], user_id, exc)
            missing.append(ch)
        except TelegramAPIError:
            missing.append(ch)
    return missing

async def show_force_join(event, bot: Bot, missing: List[sqlite3.Row]) -> None:
    text = (f"{ce(E.LOCK)} <b>CHANNEL VERIFICATION REQUIRED</b>\n\n"
            f"Join all official channels, then tap <b>VERIFY JOIN</b>.")
    kb = force_join_kb(missing)
    if isinstance(event, CallbackQuery):
        await safe_edit(event, text, kb)
        await event.answer("Join all channels first.", show_alert=True)
    else:
        await safe_answer(event, text, kb)

async def ensure_joined(event, bot: Bot) -> bool:
    user = event.from_user
    if user is None:
        return False
    if is_admin(user.id):
        return True
    missing = await missing_channels(bot, user.id)
    if missing:
        await show_force_join(event, bot, missing)
        return False
    row = get_user(user.id)
    if row and not row["is_verified"]:
        mark_user_verified(user.id)
        referrer_id = qualify_referral(user.id)
        if referrer_id:
            await notify_referrer(bot, referrer_id, user)
    return True

async def notify_referrer(bot: Bot, referrer_id: int, referred_user: Any) -> None:
    reward = get_setting_int("referral_reward_paise", REFERRAL_REWARD_PAISE)
    name = he(referred_user.first_name or "A new user")
    text = (f"{ce(E.GIFT)} <b>NEW SUCCESSFUL REFERRAL</b>\n\n"
            f"{ce(E.USER)} <b>{name}</b> joined using your link.\n"
            f"{ce(E.MONEY)} <b>{fmt_inr(reward)}</b> credited.\n\n"
            f"{ce(E.ROCKET)} Keep inviting friends.")
    await safe_send(bot, referrer_id, text)

# ---------------------------------------------------------------------------
# 9. HANDLERS
# ---------------------------------------------------------------------------

router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject) -> None:
    user = message.from_user
    if user is None:
        return
    if not rate_ok(f"start:{user.id}", limit=4, window=10):
        return
    ref_id = None
    if command.args and command.args.strip().isdigit():
        candidate = int(command.args.strip())
        if candidate != user.id:
            ref_id = candidate
    existing = get_user(user.id)
    if existing is None:
        created = create_user(user.id, user.username, user.first_name, ref_id)
        log.info("New user id=%s referred_by=%s", user.id, ref_id)
        if created and not (await enabled_channels()):
            referrer_id = qualify_referral(user.id)
            if referrer_id:
                await notify_referrer(BOT, referrer_id, user)
    row = get_user(user.id)
    if row and row["is_banned"]:
        await safe_answer(message, f"{ce(E.LOCK)} Account restricted. Contact support.")
        return
    if not await ensure_joined(message, BOT):
        return
    welcome = (f"{ce(E.CROWN)} <b>XYVEN PREMIUM REFER &amp; EARN</b>\n\n"
               f"{ce(E.STAR)} Welcome to your personal earning platform.\n\n"
               f"{ce(E.GIFT)} Earn <b>{fmt_inr(get_setting_int('referral_reward_paise', REFERRAL_REWARD_PAISE))}</b> "
               f"per successful referral.\n"
               f"{ce(E.WALLET)} Minimum withdrawal: "
               f"<b>{fmt_inr(get_setting_int('min_withdrawal_paise', MIN_WITHDRAWAL_PAISE))}</b>.\n\n"
               f"{ce(E.DIAMOND)} Invite friends, grow your balance, withdraw with ease.\n\n"
               f"{ce(E.INFO)} Choose an option below.")
    await safe_answer(message, welcome, main_menu_kb(user.id))

@router.callback_query(F.data == "verify:check")
async def cb_verify(cb: CallbackQuery) -> None:
    missing = await missing_channels(BOT, cb.from_user.id)
    if missing:
        await cb.answer("You have not joined all required channels.", show_alert=True)
        await show_force_join(cb, BOT, missing)
        return
    row = get_user(cb.from_user.id)
    if row and not row["is_verified"]:
        mark_user_verified(cb.from_user.id)
        referrer_id = qualify_referral(cb.from_user.id)
        if referrer_id:
            await notify_referrer(BOT, referrer_id, cb.from_user)
    await cb.answer("Verification successful.")
    text = (f"{ce(E.CHECK)} <b>VERIFICATION COMPLETE</b>\n\n"
            f"{ce(E.KEY)} All earning features are now unlocked.\n\n"
            f"{ce(E.ROCKET)} Start inviting friends.")
    await safe_edit(cb, text, main_menu_kb(cb.from_user.id))

@router.callback_query(F.data == "menu:main")
async def cb_main(cb: CallbackQuery) -> None:
    if not await ensure_joined(cb, BOT):
        return
    text = f"{ce(E.CROWN)} <b>XYVEN PREMIUM REFER &amp; EARN</b>\n\n{ce(E.STAR)} Main Menu\n\n{ce(E.INFO)} Select an option."
    await safe_edit(cb, text, main_menu_kb(cb.from_user.id))
    await cb.answer()

@router.callback_query(F.data == "menu:account")
async def cb_account(cb: CallbackQuery) -> None:
    if not await ensure_joined(cb, BOT):
        return
    row = get_user(cb.from_user.id)
    if row is None:
        await cb.answer("User not found.", show_alert=True)
        return
    username = f"@{row['username']}" if row["username"] else "Not set"
    created = row["created_at"][:10] if row["created_at"] else "Unknown"
    link = referral_link(cb.from_user.id)
    text = (f"{ce(E.USER)} <b>MY ACCOUNT</b>\n\n"
            f"{ce(E.INFO)} <b>Username:</b> {he(username)}\n"
            f"{ce(E.KEY)} <b>User ID:</b> <code>{cb.from_user.id}</code>\n"
            f"{ce(E.CLOCK)} <b>Registered:</b> {he(created)}\n\n"
            f"{ce(E.LINK)} <b>Referral Link:</b>\n<code>{he(link)}</code>\n\n"
            f"{ce(E.GIFT)} <b>Total Invited:</b> {row['referral_count']}\n"
            f"{ce(E.CHECK)} <b>Successful Referrals:</b> {row['successful_referrals']}\n"
            f"{ce(E.MONEY)} <b>Total Earnings:</b> {fmt_inr(row['total_earned_paise'])}\n"
            f"{ce(E.WALLET)} <b>Available Balance:</b> {fmt_inr(row['balance_paise'])}\n"
            f"{ce(E.LOCK)} <b>Reserved Withdrawal:</b> {fmt_inr(row['reserved_paise'])}\n"
            f"{ce(E.CARD)} <b>Total Withdrawn:</b> {fmt_inr(row['total_withdrawn_paise'])}\n"
            f"{ce(E.SHIELD)} <b>Status:</b> {'Active' if not row['is_banned'] else 'Restricted'}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("COPY REFERRAL LINK", copy=link, style="primary", emoji_id=E.LINK)],
        [btn("REFER NOW", cb="menu:refer", style="success", emoji_id=E.SHARE)],
        [btn("BACK", cb="menu:main", style="danger", emoji_id=E.CROSS)],
    ])
    await safe_edit(cb, text, kb)
    await cb.answer()

@router.callback_query(F.data == "menu:refer")
async def cb_refer(cb: CallbackQuery) -> None:
    if not await ensure_joined(cb, BOT):
        return
    reward = get_setting_int("referral_reward_paise", REFERRAL_REWARD_PAISE)
    min_wd = get_setting_int("min_withdrawal_paise", MIN_WITHDRAWAL_PAISE)
    link = referral_link(cb.from_user.id)
    share_text = f"Join XYVEN Premium Refer & Earn and get rewards! Use my link: {link}"
    share_url = f"https://t.me/share/url?url={link}&text={share_text}"
    text = (f"{ce(E.GIFT)} <b>REFER &amp; EARN</b>\n\n"
            f"{ce(E.MONEY)} <b>Reward per referral:</b> {fmt_inr(reward)}\n"
            f"{ce(E.WALLET)} <b>Minimum withdrawal:</b> {fmt_inr(min_wd)}\n\n"
            f"{ce(E.INFO)} <b>How it works:</b>\n"
            f"1. Share your unique referral link.\n"
            f"2. Your friend joins through your link.\n"
            f"3. Your friend verifies all required channels.\n"
            f"4. {fmt_inr(reward)} is credited to your balance automatically.\n\n"
            f"{ce(E.LINK)} <b>Your referral link:</b>\n<code>{he(link)}</code>\n\n"
            f"{ce(E.CHECK)} <b>Successful referrals:</b> {get_user(cb.from_user.id)['successful_referrals']}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("SHARE REFERRAL LINK", url=share_url, style="success", emoji_id=E.SHARE)],
        [btn("MY REFERRALS", cb="menu:my_referrals", style="primary", emoji_id=E.USER)],
        [btn("BACK", cb="menu:main", style="danger", emoji_id=E.CROSS)],
    ])
    await safe_edit(cb, text, kb)
    await cb.answer()

@router.callback_query(F.data == "menu:my_referrals")
async def cb_my_referrals(cb: CallbackQuery) -> None:
    if not await ensure_joined(cb, BOT):
        return
    rows = db_all("SELECT r.*, u.first_name, u.username FROM referrals r "
                  "JOIN users u ON u.user_id=r.referred_id "
                  "WHERE r.referrer_id=? ORDER BY r.id DESC LIMIT 20",
                  (cb.from_user.id,))
    lines = [f"{ce(E.USER)} <b>MY REFERRALS</b>", ""]
    if not rows:
        lines.append("No referrals yet. Share your link to get started.")
    else:
        for r in rows:
            name = r["first_name"] or "User"
            uname = f"@{r['username']}" if r["username"] else ""
            icon = ce(E.CHECK) if r["status"] == "credited" else ce(E.CLOCK)
            lines.append(f"{icon} {he(name)} {he(uname)} — <b>{r['status'].title()}</b>")
    await safe_edit(cb, "\n".join(lines), back_kb("menu:refer"))
    await cb.answer()

@router.callback_query(F.data == "menu:balance")
async def cb_balance(cb: CallbackQuery) -> None:
    if not await ensure_joined(cb, BOT):
        return
    row = get_user(cb.from_user.id)
    pending = db_one("SELECT COALESCE(SUM(amount_paise),0) AS total FROM withdrawals "
                     "WHERE user_id=? AND status='pending'", (cb.from_user.id,))
    text = (f"{ce(E.WALLET)} <b>MY BALANCE</b>\n\n"
            f"{ce(E.MONEY)} <b>Total Earned:</b> {fmt_inr(row['total_earned_paise'])}\n"
            f"{ce(E.CHECK)} <b>Available Balance:</b> {fmt_inr(row['balance_paise'])}\n"
            f"{ce(E.LOCK)} <b>Reserved:</b> {fmt_inr(row['reserved_paise'])}\n"
            f"{ce(E.CLOCK)} <b>Pending Withdrawals:</b> {fmt_inr(pending['total'])}\n"
            f"{ce(E.CARD)} <b>Total Paid:</b> {fmt_inr(row['total_withdrawn_paise'])}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("WITHDRAW", cb="menu:withdraw", style="success", emoji_id=E.CARD)],
        [btn("TRANSACTION HISTORY", cb="menu:transactions", style="primary", emoji_id=E.CHART)],
        [btn("BACK", cb="menu:main", style="danger", emoji_id=E.CROSS)],
    ])
    await safe_edit(cb, text, kb)
    await cb.answer()

@router.callback_query(F.data == "menu:transactions")
async def cb_transactions(cb: CallbackQuery) -> None:
    if not await ensure_joined(cb, BOT):
        return
    rows = db_all("SELECT * FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 25",
                  (cb.from_user.id,))
    lines = [f"{ce(E.CHART)} <b>TRANSACTION HISTORY</b>", ""]
    if not rows:
        lines.append("No transactions yet.")
    else:
        for t in rows:
            sign = "+" if t["amount_paise"] >= 0 else ""
            lines.append(f"{ce(E.DIAMOND)} <b>{sign}{fmt_inr(t['amount_paise'])}</b>\n"
                         f"   {he(t['description'] or t['type'])}\n"
                         f"   <i>{he(t['created_at'][:16].replace('T', ' '))}</i>")
    await safe_edit(cb, "\n".join(lines), back_kb("menu:balance"))
    await cb.answer()

@router.callback_query(F.data == "menu:stats")
async def cb_stats(cb: CallbackQuery) -> None:
    if not await ensure_joined(cb, BOT):
        return
    user_id = cb.from_user.id
    row = get_user(user_id)
    rank = db_one("SELECT COUNT(*) + 1 AS r FROM users WHERE successful_referrals > ?",
                  (row["successful_referrals"],))["r"]
    text = (f"{ce(E.STATS)} <b>YOUR STATISTICS</b>\n\n"
            f"{ce(E.GIFT)} Successful Referrals: <b>{row['successful_referrals']}</b>\n"
            f"{ce(E.CHART)} Your Rank: <b>#{rank}</b>\n"
            f"{ce(E.MONEY)} Total Earned: <b>{fmt_inr(row['total_earned_paise'])}</b>\n"
            f"{ce(E.FIRE)} Keep referring to climb higher!")
    await safe_edit(cb, text, back_kb())
    await cb.answer()

@router.callback_query(F.data == "menu:channels")
async def cb_channels(cb: CallbackQuery) -> None:
    if not await ensure_joined(cb, BOT):
        return
    channels = await enabled_channels()
    lines = [f"{ce(E.MEGAPHONE)} <b>PROMO CHANNELS</b>", ""]
    if not channels:
        lines.append("No promotional channels configured yet.")
    else:
        for ch in channels:
            url = ch["invite_link"] or (f"https://t.me/{ch['username']}" if ch["username"] else "N/A")
            lines.append(f"{ce(E.LINK)} <b>{he(ch['title'] or 'Channel')}</b>\n   {he(url)}")
    await safe_edit(cb, "\n".join(lines), back_kb())
    await cb.answer()

@router.callback_query(F.data == "menu:howto")
async def cb_howto(cb: CallbackQuery) -> None:
    if not await ensure_joined(cb, BOT):
        return
    reward = fmt_inr(get_setting_int("referral_reward_paise", REFERRAL_REWARD_PAISE))
    min_wd = fmt_inr(get_setting_int("min_withdrawal_paise", MIN_WITHDRAWAL_PAISE))
    text = (f"{ce(E.INFO)} <b>HOW TO USE</b>\n\n"
            f"1. Share your referral link with friends.\n"
            f"2. They join and verify all channels.\n"
            f"3. You earn {reward} per successful referral.\n"
            f"4. Reach {min_wd} and request a withdrawal.\n"
            f"5. Admin processes your UPI payment.\n\n"
            f"{ce(E.SHIELD)} All rewards are verified and secure.")
    await safe_edit(cb, text, back_kb())
    await cb.answer()

@router.callback_query(F.data == "menu:support")
async def cb_support(cb: CallbackQuery) -> None:
    if not await ensure_joined(cb, BOT):
        return
    text = (f"{ce(E.SUPPORT)} <b>SUPPORT</b>\n\n"
            f"Contact the admin team:\n"
            f"{ce(E.USER)} @cytunn\n{ce(E.USER)} @R0syug\n\n"
            f"{ce(E.CLOCK)} Response time: within 24 hours.")
    await safe_edit(cb, text, back_kb())
    await cb.answer()

# ---------------------------------------------------------------------------
# 10. WITHDRAWAL FLOW
# ---------------------------------------------------------------------------

class WithdrawStates(StatesGroup):
    amount = State()
    upi = State()
    confirm = State()

UPI_RE = re.compile(r"^[A-Za-z0-9._\-]{2,256}@[A-Za-z]{2,64}$")

@router.callback_query(F.data == "menu:withdraw")
async def cb_withdraw(cb: CallbackQuery, state: FSMContext) -> None:
    if not await ensure_joined(cb, BOT):
        return
    row = get_user(cb.from_user.id)
    min_wd = get_setting_int("min_withdrawal_paise", MIN_WITHDRAWAL_PAISE)
    if row["balance_paise"] < min_wd:
        await cb.answer(f"Minimum withdrawal is {fmt_inr(min_wd)}. Your balance is {fmt_inr(row['balance_paise'])}.",
                        show_alert=True)
        return
    await state.set_state(WithdrawStates.amount)
    text = (f"{ce(E.CARD)} <b>WITHDRAWAL</b>\n\n"
            f"{ce(E.WALLET)} Available: <b>{fmt_inr(row['balance_paise'])}</b>\n"
            f"{ce(E.INFO)} Minimum: <b>{fmt_inr(min_wd)}</b>\n\n"
            f"{ce(E.KEY)} Enter the amount (₹):")
    await safe_edit(cb, text, back_kb("menu:balance"))
    await cb.answer()

@router.message(WithdrawStates.amount)
async def wd_amount(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    raw = message.text.strip().replace("₹", "").replace(",", "")
    try:
        amount_paise = int(round(float(raw) * 100))
    except ValueError:
        await safe_answer(message, f"{ce(E.CROSS)} Invalid amount. Enter a number.")
        return
    min_wd = get_setting_int("min_withdrawal_paise", MIN_WITHDRAWAL_PAISE)
    row = get_user(message.from_user.id)
    if amount_paise < min_wd:
        await safe_answer(message, f"{ce(E.CROSS)} Minimum is <b>{fmt_inr(min_wd)}</b>.")
        return
    if amount_paise > row["balance_paise"]:
        await safe_answer(message, f"{ce(E.CROSS)} Exceeds balance <b>{fmt_inr(row['balance_paise'])}</b>.")
        return
    await state.update_data(amount_paise=amount_paise)
    await state.set_state(WithdrawStates.upi)
    await safe_answer(message, f"{ce(E.KEY)} Enter your UPI ID (name@bank).", back_kb("menu:balance"))

@router.message(WithdrawStates.upi)
async def wd_upi(message: Message, state: FSMContext) -> None:
    if not message.text:
        return
    upi = message.text.strip()
    if not UPI_RE.match(upi):
        await safe_answer(message, f"{ce(E.CROSS)} Invalid UPI ID. Use format name@bank.")
        return
    data = await state.get_data()
    await state.update_data(upi_id=upi)
    await state.set_state(WithdrawStates.confirm)
    text = (f"{ce(E.CHECK)} <b>CONFIRM WITHDRAWAL</b>\n\n"
            f"{ce(E.MONEY)} Amount: <b>{fmt_inr(int(data['amount_paise']))}</b>\n"
            f"{ce(E.KEY)} UPI: <code>{he(upi)}</code>\n\n"
            f"{ce(E.INFO)} Balance will be reserved until admin processes.")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("CONFIRM & SUBMIT", cb="wd:submit", style="success", emoji_id=E.CHECK)],
        [btn("CANCEL", cb="wd:cancel", style="danger", emoji_id=E.CROSS)],
    ])
    await safe_answer(message, text, kb)

@router.callback_query(F.data == "wd:cancel")
async def wd_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await cb.answer("Cancelled.")
    await safe_edit(cb, f"{ce(E.CROSS)} Withdrawal cancelled.", back_kb("menu:balance"))

@router.callback_query(F.data == "wd:submit")
async def wd_submit(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    amount_paise = int(data.get("amount_paise", 0))
    upi = data.get("upi_id", "")
    if not rate_ok(f"wd:{cb.from_user.id}", limit=3, window=60):
        await cb.answer("Too many attempts.", show_alert=True)
        return
    result = create_withdrawal(cb.from_user.id, amount_paise, upi)
    await state.clear()
    if not result["ok"]:
        await cb.answer(result["error"], show_alert=True)
        return
    text = (f"{ce(E.CLOCK)} <b>WITHDRAWAL SUBMITTED</b>\n\n"
            f"{ce(E.CARD)} Request: <code>#{result['id']}</code>\n"
            f"{ce(E.MONEY)} Amount: <b>{fmt_inr(amount_paise)}</b>\n"
            f"{ce(E.KEY)} UPI: <code>{he(upi)}</code>\n"
            f"{ce(E.INFO)} Status: <b>Pending</b>")
    await safe_edit(cb, text, back_kb("menu:balance"))
    await cb.answer("Submitted.")
    await notify_admins_withdrawal(result["id"])

def create_withdrawal(user_id: int, amount_paise: int, upi: str) -> Dict[str, Any]:
    min_wd = get_setting_int("min_withdrawal_paise", MIN_WITHDRAWAL_PAISE)
    if amount_paise < min_wd:
        return {"ok": False, "error": f"Minimum is {fmt_inr(min_wd)}."}
    if not UPI_RE.match(upi):
        return {"ok": False, "error": "Invalid UPI."}
    with _db_lock, db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            user = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            if not user or user["is_banned"] or user["balance_paise"] < amount_paise:
                conn.execute("COMMIT")
                return {"ok": False, "error": "Insufficient balance."}
            cur = conn.execute("UPDATE users SET balance_paise = balance_paise - ?, "
                               "reserved_paise = reserved_paise + ? "
                               "WHERE user_id=? AND balance_paise >= ?",
                               (amount_paise, amount_paise, user_id, amount_paise))
            if cur.rowcount != 1:
                conn.execute("ROLLBACK")
                return {"ok": False, "error": "Balance changed."}
            wd = conn.execute("INSERT INTO withdrawals(user_id, amount_paise, upi_id, status, created_at) "
                              "VALUES(?, ?, ?, 'pending', ?)", (user_id, amount_paise, upi, now_iso()))
            wid = wd.lastrowid
            conn.execute("INSERT INTO transactions (user_id, type, amount_paise, description, "
                         "reference_id, created_at) VALUES(?, 'withdrawal_reserved', ?, ?, ?, ?)",
                         (user_id, -amount_paise, f"Withdrawal #{wid} reserved", str(wid), now_iso()))
            conn.execute("COMMIT")
            return {"ok": True, "id": wid}
        except Exception:
            conn.execute("ROLLBACK")
            raise

def set_withdrawal_status(wid: int, new_status: str, admin_id: int) -> Dict[str, Any]:
    if new_status not in {"approved", "rejected", "paid"}:
        return {"ok": False, "error": "Invalid status."}
    with _db_lock, db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            wd = conn.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
            if not wd:
                conn.execute("COMMIT")
                return {"ok": False, "error": "Not found."}
            old = wd["status"]
            if old == "paid":
                conn.execute("COMMIT")
                return {"ok": False, "error": "Already paid."}
            if new_status == "paid" and old not in {"approved", "pending"}:
                conn.execute("COMMIT")
                return {"ok": False, "error": "Only approved can be paid."}
            if new_status == "approved" and old != "pending":
                conn.execute("COMMIT")
                return {"ok": False, "error": "Only pending can be approved."}
            if new_status == "rejected" and old not in {"pending", "approved"}:
                conn.execute("COMMIT")
                return {"ok": False, "error": "Cannot reject."}
            amount = int(wd["amount_paise"])
            user_id = int(wd["user_id"])
            if new_status == "rejected":
                conn.execute("UPDATE users SET reserved_paise = MAX(0, reserved_paise - ?), "
                             "balance_paise = balance_paise + ? WHERE user_id=?",
                             (amount, amount, user_id))
                conn.execute("INSERT INTO transactions (user_id, type, amount_paise, description, "
                             "reference_id, created_at) VALUES(?, 'withdrawal_released', ?, ?, ?, ?)",
                             (user_id, amount, f"Withdrawal #{wid} rejected", str(wid), now_iso()))
            elif new_status == "paid":
                conn.execute("UPDATE users SET reserved_paise = MAX(0, reserved_paise - ?), "
                             "total_withdrawn_paise = total_withdrawn_paise + ? WHERE user_id=?",
                             (amount, amount, user_id))
                conn.execute("INSERT INTO transactions (user_id, type, amount_paise, description, "
                             "reference_id, created_at) VALUES(?, 'withdrawal_paid', ?, ?, ?, ?)",
                             (user_id, -amount, f"Withdrawal #{wid} paid", str(wid), now_iso()))
            conn.execute("UPDATE withdrawals SET status=?, processed_at=?, admin_id=? WHERE id=?",
                         (new_status, now_iso(), admin_id, wid))
            conn.execute("COMMIT")
            return {"ok": True, "user_id": user_id, "amount_paise": amount}
        except Exception:
            conn.execute("ROLLBACK")
            raise

async def notify_admins_withdrawal(wid: int) -> None:
    wd = db_one("SELECT * FROM withdrawals WHERE id=?", (wid,))
    if not wd:
        return
    user = get_user(int(wd["user_id"]))
    text = (f"{ce(E.BELL)} <b>NEW WITHDRAWAL</b>\n\n"
            f"{ce(E.CARD)} Request: <code>#{wid}</code>\n"
            f"{ce(E.USER)} {he(user['first_name'] or '')} (@{he(user['username'] or 'none')}) — "
            f"<code>{user['user_id']}</code>\n"
            f"{ce(E.MONEY)} Amount: <b>{fmt_inr(int(wd['amount_paise']))}</b>\n"
            f"{ce(E.KEY)} UPI: <code>{he(wd['upi_id'])}</code>")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("APPROVE", cb=f"adm:wd:approve:{wid}", style="success", emoji_id=E.CHECK),
         btn("REJECT", cb=f"adm:wd:reject:{wid}", style="danger", emoji_id=E.CROSS)],
        [btn("MARK AS PAID", cb=f"adm:wd:paid:{wid}", style="primary", emoji_id=E.CARD)],
    ])
    for admin_id in ADMIN_IDS:
        await safe_send(BOT, admin_id, text, kb)

# ---------------------------------------------------------------------------
# 11. ADMIN PANEL
# ---------------------------------------------------------------------------

@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await safe_answer(message, f"{ce(E.LOCK)} Unauthorised.")
        return
    await safe_answer(message, admin_dashboard_text(), admin_dashboard_kb())

def admin_dashboard_text() -> str:
    users = db_one("SELECT COUNT(*) AS c FROM users")["c"]
    refs = db_one("SELECT COUNT(*) AS c FROM referrals WHERE status='credited'")["c"]
    rewards = db_one("SELECT COALESCE(SUM(amount_paise),0) AS c FROM transactions "
                     "WHERE type='referral_reward'")["c"]
    available = db_one("SELECT COALESCE(SUM(balance_paise),0) AS c FROM users")["c"]
    pending = db_one("SELECT COUNT(*) AS c FROM withdrawals WHERE status='pending'")["c"]
    approved = db_one("SELECT COUNT(*) AS c FROM withdrawals WHERE status='approved'")["c"]
    paid = db_one("SELECT COUNT(*) AS c FROM withdrawals WHERE status='paid'")["c"]
    channels = db_one("SELECT COUNT(*) AS c FROM promo_channels WHERE is_enabled=1")["c"]
    return (f"{ce(E.SHIELD)} <b>XYVEN ADMIN DASHBOARD</b>\n\n"
            f"{ce(E.USER)} Users: {users}\n"
            f"{ce(E.GIFT)} Referrals: {refs}\n"
            f"{ce(E.MONEY)} Rewards: {fmt_inr(rewards)}\n"
            f"{ce(E.WALLET)} Available: {fmt_inr(available)}\n"
            f"{ce(E.CLOCK)} Pending WD: {pending}\n"
            f"{ce(E.CHECK)} Approved WD: {approved}\n"
            f"{ce(E.CARD)} Paid WD: {paid}\n"
            f"{ce(E.MEGAPHONE)} Channels: {channels}")

def admin_dashboard_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("DASHBOARD", cb="adm:dashboard", style="primary", emoji_id=E.CHART)],
        [btn("ALL USERS", cb="adm:users:0", style="success", emoji_id=E.USER)],
        [btn("BOT STATISTICS", cb="adm:stats", style="primary", emoji_id=E.STATS)],
        [btn("WITHDRAWAL REQUESTS", cb="adm:withdrawals", style="success", emoji_id=E.CARD)],
        [btn("ADD PROMO CHANNEL", cb="adm:ch_add", style="success", emoji_id=E.LINK)],
        [btn("REMOVE PROMO CHANNEL", cb="adm:ch_list:remove", style="danger", emoji_id=E.CROSS)],
        [btn("MANAGE CHANNELS", cb="adm:ch_list:manage", style="primary", emoji_id=E.MEGAPHONE)],
        [btn("BROADCAST", cb="adm:broadcast", style="success", emoji_id=E.BELL)],
        [btn("USER MANAGEMENT", cb="adm:user_search", style="primary", emoji_id=E.KEY)],
        [btn("BOT SETTINGS", cb="adm:settings", style="danger", emoji_id=E.SETTINGS)],
        [btn("CLOSE ADMIN PANEL", cb="adm:close", style="danger", emoji_id=E.CROSS)],
    ])

@router.callback_query(F.data == "adm:dashboard")
async def cb_adm_dashboard(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    await safe_edit(cb, admin_dashboard_text(), admin_dashboard_kb())
    await cb.answer()

@router.callback_query(F.data == "adm:close")
async def cb_adm_close(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    await safe_edit(cb, f"{ce(E.CROWN)} <b>XYVEN</b>\n\n{ce(E.STAR)} Main Menu",
                    main_menu_kb(cb.from_user.id))
    await cb.answer()

@router.callback_query(F.data.startswith("adm:users:"))
async def cb_adm_users(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    page = int(cb.data.split(":")[2])
    per_page = 10
    total = db_one("SELECT COUNT(*) AS c FROM users")["c"]
    rows = db_all("SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                  (per_page, page * per_page))
    lines = [f"{ce(E.USER)} <b>ALL USERS</b> ({total})", ""]
    for u in rows:
        lines.append(f"<code>{u['user_id']}</code> — {he(u['first_name'] or '')} "
                     f"@{he(u['username'] or 'none')} — {fmt_inr(u['balance_paise'])}")
    nav = []
    if page > 0:
        nav.append(btn("PREV", cb=f"adm:users:{page-1}", style="primary", emoji_id=E.INFO))
    if (page + 1) * per_page < total:
        nav.append(btn("NEXT", cb=f"adm:users:{page+1}", style="success", emoji_id=E.ROCKET))
    kb_rows = [nav] if nav else []
    kb_rows.append([btn("BACK", cb="adm:dashboard", style="danger", emoji_id=E.CROSS)])
    await safe_edit(cb, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await cb.answer()

@router.callback_query(F.data == "adm:withdrawals")
async def cb_adm_withdrawals(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    rows = db_all("SELECT w.*, u.first_name, u.username FROM withdrawals w "
                  "JOIN users u ON u.user_id=w.user_id "
                  "ORDER BY CASE w.status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, "
                  "w.id DESC LIMIT 20")
    lines = [f"{ce(E.CARD)} <b>WITHDRAWAL REQUESTS</b>", ""]
    for w in rows:
        lines.append(f"<code>#{w['id']}</code> {he(w['first_name'] or '')} "
                     f"(@{he(w['username'] or 'none')}) — "
                     f"<b>{fmt_inr(w['amount_paise'])}</b> — {w['status'].upper()}")
    await safe_edit(cb, "\n".join(lines), back_kb("adm:dashboard"))
    await cb.answer()

@router.callback_query(F.data.startswith("adm:wd:"))
async def cb_adm_wd_action(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    parts = cb.data.split(":")
    action = parts[2]
    wid = int(parts[3])
    result = set_withdrawal_status(wid, action, cb.from_user.id)
    if not result["ok"]:
        await cb.answer(result["error"], show_alert=True)
        return
    await cb.answer(f"Withdrawal {action}.")
    wd = db_one("SELECT * FROM withdrawals WHERE id=?", (wid,))
    user_id = int(wd["user_id"])
    amount = fmt_inr(int(wd["amount_paise"]))
    if action == "approved":
        user_text = (f"{ce(E.CHECK)} <b>WITHDRAWAL APPROVED</b>\n\n"
                     f"{ce(E.CARD)} Request <code>#{wid}</code>\n"
                     f"{ce(E.MONEY)} Amount: <b>{amount}</b>\n"
                     f"{ce(E.CLOCK)} Being processed.")
    elif action == "rejected":
        user_text = (f"{ce(E.CROSS)} <b>WITHDRAWAL REJECTED</b>\n\n"
                     f"{ce(E.CARD)} Request <code>#{wid}</code>\n"
                     f"{ce(E.MONEY)} Amount: <b>{amount}</b>\n"
                     f"{ce(E.WALLET)} Amount returned to your balance.")
    else:
        user_text = (f"{ce(E.CARD)} <b>WITHDRAWAL PAID</b>\n\n"
                     f"{ce(E.CHECK)} Request <code>#{wid}</code>\n"
                     f"{ce(E.MONEY)} Amount: <b>{amount}</b>\n"
                     f"{ce(E.DIAMOND)} Payment marked as completed.")
    await safe_send(BOT, user_id, user_text)

@router.callback_query(F.data == "adm:stats")
async def cb_adm_stats(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    total_users = db_one("SELECT COUNT(*) AS c FROM users")["c"]
    verified = db_one("SELECT COUNT(*) AS c FROM users WHERE is_verified=1")["c"]
    banned = db_one("SELECT COUNT(*) AS c FROM users WHERE is_banned=1")["c"]
    total_refs = db_one("SELECT COUNT(*) AS c FROM referrals")["c"]
    credited_refs = db_one("SELECT COUNT(*) AS c FROM referrals WHERE status='credited'")["c"]
    text = (f"{ce(E.STATS)} <b>BOT STATISTICS</b>\n\n"
            f"{ce(E.USER)} Total Users: {total_users}\n"
            f"{ce(E.CHECK)} Verified: {verified}\n"
            f"{ce(E.LOCK)} Banned: {banned}\n"
            f"{ce(E.GIFT)} Total Referrals: {total_refs}\n"
            f"{ce(E.MONEY)} Credited Referrals: {credited_refs}")
    await safe_edit(cb, text, back_kb("adm:dashboard"))
    await cb.answer()

# --- Channel management ----------------------------------------------------

class ChannelStates(StatesGroup):
    link = State()

@router.callback_query(F.data == "adm:ch_add")
async def cb_adm_ch_add(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    await state.set_state(ChannelStates.link)
    await safe_edit(cb, f"{ce(E.LINK)} Send the channel link (public @username or private invite link).",
                    back_kb("adm:dashboard"))
    await cb.answer()

@router.message(ChannelStates.link)
async def ch_link(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw:
        await safe_answer(message, f"{ce(E.CROSS)} Send a valid link.")
        return
    username = None
    invite = None
    if raw.startswith("https://t.me/") or raw.startswith("http://t.me/"):
        parts = urlparse(raw).path.strip("/").split("/")
        if len(parts) == 1 and not parts[0].startswith("+"):
            username = parts[0]
        else:
            invite = raw
    elif raw.startswith("@"):
        username = raw.lstrip("@")
    elif raw.startswith("+"):
        invite = f"https://t.me/{raw}"
    else:
        await safe_answer(message, f"{ce(E.CROSS)} Unrecognised link format.")
        return

    chat_id = None
    title = None
    final_link = invite
    try:
        if username:
            chat = await BOT.get_chat(f"@{username}")
            chat_id = chat.id
            title = chat.title or username
            final_link = f"https://t.me/{username}"
        elif invite:
            chat = await BOT.get_chat(invite)
            chat_id = chat.id
            title = chat.title or "Private Channel"
            final_link = invite
    except TelegramBadRequest as exc:
        log.warning("Channel resolve failed: %s", exc)
        await safe_answer(message, f"{ce(E.CROSS)} Could not resolve channel. Ensure the bot is an admin with invite-link permission.")
        return

    if chat_id is None:
        await safe_answer(message, f"{ce(E.CROSS)} Could not resolve numeric chat ID.")
        return

    with _db_lock, db() as conn:
        conn.execute("INSERT OR REPLACE INTO promo_channels "
                     "(chat_id, username, title, invite_link, is_enabled, auto_approve, created_at) "
                     "VALUES(?, ?, ?, ?, 1, 1, ?)",
                     (chat_id, username, title, final_link, now_iso()))
    await state.clear()
    await safe_answer(message, f"{ce(E.CHECK)} Channel <b>{he(title)}</b> added.",
                      back_kb("adm:dashboard"))

@router.callback_query(F.data.startswith("adm:ch_list:"))
async def cb_adm_ch_list(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    mode = cb.data.split(":")[2]
    channels = db_all("SELECT * FROM promo_channels ORDER BY id ASC")
    lines = [f"{ce(E.MEGAPHONE)} <b>CHANNELS</b>", ""]
    rows = []
    for ch in channels:
        status = "ON" if ch["is_enabled"] else "OFF"
        lines.append(f"<code>{ch['chat_id']}</code> — {he(ch['title'] or '')} [{status}]")
        label = ("DISABLE" if ch["is_enabled"] else "ENABLE") if mode == "manage" else "REMOVE"
        style = "danger" if mode == "remove" else "primary"
        emoji = E.CROSS if mode == "remove" else E.SETTINGS
        rows.append([btn(f"{label}: {ch['title'] or ch['chat_id']}",
                         cb=f"adm:ch_toggle:{ch['id']}:{mode}",
                         style=style, emoji_id=emoji)])
    rows.append([btn("BACK", cb="adm:dashboard", style="danger", emoji_id=E.CROSS)])
    await safe_edit(cb, "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows))
    await cb.answer()

@router.callback_query(F.data.startswith("adm:ch_toggle:"))
async def cb_adm_ch_toggle(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    _, _, cid, mode = cb.data.split(":")
    cid = int(cid)
    if mode == "remove":
        with _db_lock, db() as conn:
            conn.execute("DELETE FROM promo_channels WHERE id=?", (cid,))
        await cb.answer("Channel removed.")
    else:
        with _db_lock, db() as conn:
            conn.execute("UPDATE promo_channels SET is_enabled = 1 - is_enabled WHERE id=?", (cid,))
        await cb.answer("Channel toggled.")
    await safe_edit(cb, f"{ce(E.CHECK)} Updated.", back_kb("adm:dashboard"))

# --- Broadcast -------------------------------------------------------------

class BroadcastStates(StatesGroup):
    message = State()

@router.callback_query(F.data == "adm:broadcast")
async def cb_adm_broadcast(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    await state.set_state(BroadcastStates.message)
    await safe_edit(cb, f"{ce(E.BELL)} Send the message to broadcast (text or photo with caption).",
                    back_kb("adm:dashboard"))
    await cb.answer()

@router.message(BroadcastStates.message)
async def do_broadcast(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    users = db_all("SELECT user_id FROM users")
    sent = 0
    failed = 0
    for u in users:
        uid = int(u["user_id"])
        try:
            if message.text:
                await BOT.send_message(uid, message.text, parse_mode=ParseMode.HTML)
            elif message.photo:
                await BOT.send_photo(uid, message.photo[-1].file_id,
                                     caption=message.caption or "",
                                     parse_mode=ParseMode.HTML)
            sent += 1
        except TelegramForbiddenError:
            failed += 1
        except TelegramBadRequest:
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(BROADCAST_DELAY_SECONDS)
    await safe_answer(message, f"{ce(E.CHECK)} Broadcast complete.\n\n"
                               f"Delivered: {sent}\nFailed: {failed}",
                      back_kb("adm:dashboard"))

# --- Admin: user search / settings ----------------------------------------

class UserSearchStates(StatesGroup):
    query = State()

@router.callback_query(F.data == "adm:user_search")
async def cb_adm_user_search(cb: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    await state.set_state(UserSearchStates.query)
    await safe_edit(cb, f"{ce(E.KEY)} Send a numeric Telegram user ID to search.",
                    back_kb("adm:dashboard"))
    await cb.answer()

@router.message(UserSearchStates.query)
async def adm_user_lookup(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await safe_answer(message, f"{ce(E.CROSS)} Send a numeric ID.")
        return
    await state.clear()
    uid = int(raw)
    row = get_user(uid)
    if not row:
        await safe_answer(message, f"{ce(E.CROSS)} User not found.", back_kb("adm:dashboard"))
        return
    wd = db_all("SELECT * FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,))
    refs = db_all("SELECT * FROM referrals WHERE referrer_id=? ORDER BY id DESC LIMIT 5", (uid,))
    lines = [f"{ce(E.USER)} <b>USER DETAILS</b>\n",
             f"ID: <code>{row['user_id']}</code>",
             f"Name: {he(row['first_name'] or '')}",
             f"Username: @{he(row['username'] or 'none')}",
             f"Balance: {fmt_inr(row['balance_paise'])}",
             f"Reserved: {fmt_inr(row['reserved_paise'])}",
             f"Total Earned: {fmt_inr(row['total_earned_paise'])}",
             f"Successful Referrals: {row['successful_referrals']}",
             f"Banned: {'Yes' if row['is_banned'] else 'No'}",
             "\n<b>Recent Withdrawals:</b>"]
    for w in wd:
        lines.append(f"#{w['id']} — {fmt_inr(w['amount_paise'])} — {w['status']}")
    lines.append("\n<b>Recent Referrals:</b>")
    for r in refs:
        lines.append(f"{r['referred_id']} — {r['status']}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [btn("BAN USER" if not row["is_banned"] else "UNBAN USER",
             cb=f"adm:ban:{uid}", style="danger", emoji_id=E.LOCK)],
        [btn("BACK", cb="adm:dashboard", style="danger", emoji_id=E.CROSS)],
    ])
    await safe_answer(message, "\n".join(lines), kb)

@router.callback_query(F.data.startswith("adm:ban:"))
async def cb_adm_ban(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    uid = int(cb.data.split(":")[2])
    row = get_user(uid)
    if not row:
        await cb.answer("User not found.", show_alert=True)
        return
    new = 0 if row["is_banned"] else 1
    with _db_lock, db() as conn:
        conn.execute("UPDATE users SET is_banned=? WHERE user_id=?", (new, uid))
    await cb.answer("Updated.")
    await safe_edit(cb, f"{ce(E.CHECK)} User {'banned' if new else 'unbanned'}.",
                    back_kb("adm:dashboard"))

@router.callback_query(F.data == "adm:settings")
async def cb_adm_settings(cb: CallbackQuery) -> None:
    if not is_admin(cb.from_user.id):
        await cb.answer("Unauthorised", show_alert=True)
        return
    text = (f"{ce(E.SETTINGS)} <b>BOT SETTINGS</b>\n\n"
            f"Referral reward: {fmt_inr(get_setting_int('referral_reward_paise', REFERRAL_REWARD_PAISE))}\n"
            f"Minimum withdrawal: {fmt_inr(get_setting_int('min_withdrawal_paise', MIN_WITHDRAWAL_PAISE))}\n\n"
            f"Edit via the Flask dashboard for full control.")
    await safe_edit(cb, text, back_kb("adm:dashboard"))
    await cb.answer()

# ---------------------------------------------------------------------------
# 12. JOIN REQUEST HANDLING
# ---------------------------------------------------------------------------

@router.chat_join_request()
async def on_join_request(update: ChatJoinRequest) -> None:
    chat_id = update.chat.id
    user = update.from_user
    ch = db_one("SELECT * FROM promo_channels WHERE chat_id=?", (chat_id,))
    if not ch:
        return
    if ch["auto_approve"]:
        try:
            await BOT.approve_chat_join_request(chat_id, user.id)
            log.info("Approved join request chat=%s user=%s", chat_id, user.id)
            await safe_send(BOT, user.id,
                            f"{ce(E.CHECK)} Your join request has been approved. "
                            f"Return to the bot and tap VERIFY JOIN.")
        except TelegramBadRequest as exc:
            log.error("Approve failed chat=%s user=%s error=%s", chat_id, user.id, exc)

# ---------------------------------------------------------------------------
# 13. FLASK DASHBOARD + WEBHOOK
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = SESSION_SECRET

@app.before_request
def protect_dashboard():
    if request.path.startswith(("/telegram/", "/health", "/static/")):
        return None
    if request.endpoint in {"login", "health"}:
        return None
    if not session.get("admin_logged_in"):
        return redirect(url_for("login"))
    return None

@app.route("/health")
def health():
    return "ok", 200

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == DASHBOARD_USERNAME and check_password_hash(DASHBOARD_PASSWORD_HASH, password):
            session["admin_logged_in"] = True
            session.permanent = True
            return redirect(url_for("dashboard"))
        flash("Invalid credentials")
    return render_template_string(LOGIN_HTML)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def dashboard():
    users = db_one("SELECT COUNT(*) AS c FROM users")["c"]
    refs = db_one("SELECT COUNT(*) AS c FROM referrals WHERE status='credited'")["c"]
    rewards = db_one("SELECT COALESCE(SUM(amount_paise),0) AS c FROM transactions WHERE type='referral_reward'")["c"]
    pending = db_one("SELECT COUNT(*) AS c FROM withdrawals WHERE status='pending'")["c"]
    paid = db_one("SELECT COALESCE(SUM(amount_paise),0) AS c FROM withdrawals WHERE status='paid'")["c"]
    return render_template_string(DASHBOARD_HTML, users=users, refs=refs,
                                  rewards=fmt_inr(rewards), pending=pending, paid=fmt_inr(paid))

@app.route("/users")
def dashboard_users():
    page = int(request.args.get("page", 0))
    per_page = 20
    rows = db_all("SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                  (per_page, page * per_page))
    return render_template_string(USERS_HTML, users=rows, page=page)

@app.route("/withdrawals")
def dashboard_withdrawals():
    rows = db_all("SELECT w.*, u.first_name, u.username FROM withdrawals w "
                  "JOIN users u ON u.user_id=w.user_id ORDER BY w.id DESC LIMIT 100")
    return render_template_string(WITHDRAWALS_HTML, withdrawals=rows)

@app.route("/withdrawals/<int:wid>/<action>", methods=["POST"])
def dashboard_withdrawal_action(wid: int, action: str):
    if not session.get("admin_logged_in"):
        abort(403)
    if action not in {"approve", "reject", "paid"}:
        abort(400)
    status_map = {"approve": "approved", "reject": "rejected", "paid": "paid"}
    result = set_withdrawal_status(wid, status_map[action], 0)
    flash("Updated" if result["ok"] else result.get("error", "Failed"))
    return redirect(url_for("dashboard_withdrawals"))

@app.route("/channels")
def dashboard_channels():
    rows = db_all("SELECT * FROM promo_channels ORDER BY id ASC")
    return render_template_string(CHANNELS_HTML, channels=rows)

@app.route("/channels/add", methods=["POST"])
def dashboard_channel_add():
    if not session.get("admin_logged_in"):
        abort(403)
    link = request.form.get("link", "").strip()
    if not link:
        flash("Link required")
        return redirect(url_for("dashboard_channels"))
    # Reuse the bot's resolution logic synchronously via DB only for public usernames.
    username = None
    if link.startswith("@"):
        username = link.lstrip("@")
    elif "t.me/" in link:
        part = link.split("t.me/")[-1].split("/")[0]
        if part and not part.startswith("+"):
            username = part
    if username:
        with _db_lock, db() as conn:
            conn.execute("INSERT OR IGNORE INTO promo_channels "
                         "(chat_id, username, title, invite_link, is_enabled, auto_approve, created_at) "
                         "VALUES(?, ?, ?, ?, 1, 1, ?)",
                         (abs(hash(username)) % (10**12), username, username,
                          f"https://t.me/{username}", now_iso()))
        flash("Channel added (verify numeric ID via bot if private).")
    else:
        flash("Private links require the bot's /admin → ADD PROMO CHANNEL flow.")
    return redirect(url_for("dashboard_channels"))

@app.route("/broadcast", methods=["POST"])
def dashboard_broadcast():
    if not session.get("admin_logged_in"):
        abort(403)
    text = request.form.get("message", "").strip()
    if text and BOT:
        async def _send():
            for u in db_all("SELECT user_id FROM users"):
                try:
                    await BOT.send_message(int(u["user_id"]), text, parse_mode=ParseMode.HTML)
                except Exception:
                    pass
                await asyncio.sleep(BROADCAST_DELAY_SECONDS)
        asyncio.run_coroutine_threadsafe(_send(), LOOP)
        flash("Broadcast started.")
    return redirect(url_for("dashboard"))

# ---------------------------------------------------------------------------
# 14. TELEGRAM WEBHOOK ENDPOINT
# ---------------------------------------------------------------------------

@app.route(f"/telegram/webhook/{WEBHOOK_SECRET}", methods=["POST"])
def telegram_webhook():
    if not _bot_ready.wait(timeout=30):
        return "not ready", 503
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)
    data = request.get_json(force=True, silent=True) or {}
    async def _feed():
        try:
            update = Update.model_validate(data)
            await DP.feed_update(BOT, update)
        except Exception:
            log.exception("Webhook feed failed")
    asyncio.run_coroutine_threadsafe(_feed(), LOOP)
    return "ok", 200

# ---------------------------------------------------------------------------
# 15. TEMPLATES (embedded)
# ---------------------------------------------------------------------------

LOGIN_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>XYVEN Admin Login</title>
<style>
body{background:#0a0e1a;color:#fff;font-family:system-ui;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:rgba(255,255,255,.06);backdrop-filter:blur(16px);padding:40px;border-radius:20px;width:340px;border:1px solid rgba(255,255,255,.12)}
input{width:100%;padding:12px;margin:8px 0;border-radius:10px;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.04);color:#fff}
button{width:100%;padding:12px;border-radius:10px;border:0;background:linear-gradient(135deg,#2ecc71,#27ae60);color:#fff;font-weight:700;cursor:pointer}
h2{text-align:center;margin-bottom:20px}
</style></head><body><div class="card"><h2>👑 XYVEN Admin</h2>
<form method="post">
<input name="username" placeholder="Username" required>
<input name="password" type="password" placeholder="Password" required>
<button type="submit">Sign In</button>
</form></div></body></html>"""

DASHBOARD_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XYVEN Dashboard</title>
<style>
:root{--bg:#0a0e1a;--card:rgba(255,255,255,.06);--border:rgba(255,255,255,.12);--text:#e6edf7;--muted:#8b98b0;--green:#2ecc71;--blue:#3b82f6;--red:#ef4444}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,sans-serif;display:flex;min-height:100vh}
.sidebar{width:240px;padding:24px;background:rgba(255,255,255,.03);border-right:1px solid var(--border)}
.sidebar h2{font-size:18px;margin:0 0 24px}.sidebar a{display:block;color:var(--muted);text-decoration:none;padding:12px;border-radius:10px;margin-bottom:6px}
.sidebar a:hover,.sidebar a.active{background:var(--card);color:#fff}
.main{flex:1;padding:32px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-top:24px}
.card{background:var(--card);backdrop-filter:blur(16px);border:1px solid var(--border);border-radius:20px;padding:24px;transition:transform .2s}
.card:hover{transform:translateY(-3px)}.card .label{color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:.08em}
.card .value{font-size:28px;font-weight:800;margin-top:8px}
.green{color:var(--green)}.blue{color:var(--blue)}.red{color:var(--red)}
h1{margin:0 0 8px;font-size:26px}.sub{color:var(--muted);margin-bottom:16px}
.btn{display:inline-block;padding:10px 16px;border-radius:10px;border:0;font-weight:700;cursor:pointer;color:#fff;text-decoration:none;margin:4px 4px 0 0}
.btn-green{background:linear-gradient(135deg,#2ecc71,#27ae60)}.btn-blue{background:linear-gradient(135deg,#3b82f6,#2563eb)}.btn-red{background:linear-gradient(135deg,#ef4444,#dc2626)}
table{width:100%;border-collapse:collapse;margin-top:16px}th,td{text-align:left;padding:12px;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-size:12px;text-transform:uppercase}textarea{width:100%;padding:12px;border-radius:10px;border:1px solid var(--border);background:rgba(255,255,255,.04);color:#fff}
</style></head><body>
<div class="sidebar"><h2>👑 XYVEN</h2>
<a class="active" href="/">Dashboard</a><a href="/users">Users</a><a href="/withdrawals">Withdrawals</a><a href="/channels">Channels</a><a href="/logout">Logout</a></div>
<div class="main"><h1>Dashboard Overview</h1><div class="sub">Real-time database statistics</div>
<div class="grid">
<div class="card"><div class="label">Total Users</div><div class="value blue">{{users}}</div></div>
<div class="card"><div class="label">Referrals</div><div class="value green">{{refs}}</div></div>
<div class="card"><div class="label">Rewards Paid</div><div class="value green">{{rewards}}</div></div>
<div class="card"><div class="label">Pending Withdrawals</div><div class="value red">{{pending}}</div></div>
<div class="card"><div class="label">Total Paid Out</div><div class="value blue">{{paid}}</div></div>
</div>
<h2 style="margin-top:36px">Broadcast</h2>
<form method="post" action="/broadcast"><textarea name="message" rows="3" placeholder="Broadcast message (HTML supported)"></textarea>
<button class="btn btn-green" type="submit">Send Broadcast</button></form>
</div></body></html>"""

USERS_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Users</title>
<style>body{margin:0;background:#0a0e1a;color:#e6edf7;font-family:system-ui;padding:32px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;border-bottom:1px solid rgba(255,255,255,.1)}
th{color:#8b98b0;font-size:12px;text-transform:uppercase}a{color:#3b82f6}</style></head><body>
<h1>Users</h1><a href="/">← Back</a>
<table><tr><th>ID</th><th>Name</th><th>Username</th><th>Balance</th><th>Referrals</th><th>Banned</th></tr>
{% for u in users %}<tr><td>{{u.user_id}}</td><td>{{u.first_name or ''}}</td><td>@{{u.username or 'none'}}</td><td>₹{{'%.2f'|format(u.balance_paise/100)}}</td><td>{{u.successful_referrals}}</td><td>{{'Yes' if u.is_banned else 'No'}}</td></tr>{% endfor %}
</table></body></html>"""

WITHDRAWALS_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Withdrawals</title>
<style>body{margin:0;background:#0a0e1a;color:#e6edf7;font-family:system-ui;padding:32px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;border-bottom:1px solid rgba(255,255,255,.1)}
th{color:#8b98b0;font-size:12px;text-transform:uppercase}.btn{display:inline-block;padding:6px 12px;border-radius:8px;color:#fff;text-decoration:none;font-weight:600;margin-right:4px}
.g{background:#27ae60}.r{background:#e74c3c}.b{background:#2563eb}a{color:#3b82f6}</style></head><body>
<h1>Withdrawals</h1><a href="/">← Back</a>
<table><tr><th>ID</th><th>User</th><th>Amount</th><th>UPI</th><th>Status</th><th>Actions</th></tr>
{% for w in withdrawals %}<tr>
<td>{{w.id}}</td><td>{{w.first_name}} @{{w.username or 'none'}}</td><td>₹{{'%.2f'|format(w.amount_paise/100)}}</td><td>{{w.upi_id}}</td><td>{{w.status}}</td>
<td>
{% if w.status == 'pending' %}<a class="btn g" href="/withdrawals/{{w.id}}/approve">Approve</a><a class="btn r" href="/withdrawals/{{w.id}}/reject">Reject</a>{% endif %}
{% if w.status == 'approved' %}<a class="btn b" href="/withdrawals/{{w.id}}/paid">Mark Paid</a>{% endif %}
</td></tr>{% endfor %}
</table></body></html>"""

CHANNELS_HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Channels</title>
<style>body{margin:0;background:#0a0e1a;color:#e6edf7;font-family:system-ui;padding:32px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:12px;border-bottom:1px solid rgba(255,255,255,.1)}
th{color:#8b98b0;font-size:12px;text-transform:uppercase}input{padding:10px;border-radius:8px;border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.04);color:#fff;width:60%}
button{padding:10px 16px;border-radius:8px;border:0;background:#27ae60;color:#fff;font-weight:700;cursor:pointer}a{color:#3b82f6}</style></head><body>
<h1>Channels</h1><a href="/">← Back</a>
<table><tr><th>ID</th><th>Title</th><th>Username</th><th>Enabled</th></tr>
{% for c in channels %}<tr><td>{{c.chat_id}}</td><td>{{c.title}}</td><td>{{c.username or '-'}}</td><td>{{'Yes' if c.is_enabled else 'No'}}</td></tr>{% endfor %}
</table>
<h3>Add Public Channel</h3>
<form method="post" action="/channels/add"><input name="link" placeholder="@channel or https://t.me/channel" required>
<button type="submit">Add</button></form>
<p style="color:#8b98b0;font-size:13px">Private invite links must be added via the bot's admin panel so the numeric chat ID can be resolved.</p>
</body></html>"""

# ---------------------------------------------------------------------------
# 16. APPLICATION STARTUP
# ---------------------------------------------------------------------------

init_db()
_bootstrap_bot()

if __name__ == "__main__":
    # Development only. In production use Gunicorn: gunicorn -w 1 bot:app
    app.run(host="0.0.0.0", port=PORT, threaded=True)
