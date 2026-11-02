"""
XYVEN PREMIUM REFER & EARN PLATFORM
Single-file Telegram bot + Flask admin dashboard.

Run:
    python bot.py
"""

import asyncio
import html
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask, abort, redirect, render_template, request, session, url_for, flash,
)
from jinja2 import DictLoader
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CallbackQueryHandler, ChatJoinRequestHandler,
    CommandHandler, ContextTypes, MessageHandler, filters,
)
from werkzeug.security import check_password_hash, generate_password_hash
from asgiref.wsgi import WsgiToAsgi
import uvicorn

load_dotenv()

# ══════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change_me_webhook_secret")
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DB_PATH", "/data/xyven.db")
BOT_USERNAME = os.getenv("BOT_USERNAME", "").lstrip("@")

ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}

WEB_ADMIN_USERNAME = os.getenv("WEB_ADMIN_USERNAME", "admin")
WEB_ADMIN_PASSWORD = os.getenv("WEB_ADMIN_PASSWORD", "admin123")

DEFAULT_SETTINGS = {
    "referral_reward": "2",
    "min_withdrawal": "10",
    "currency": "INR",
    "currency_symbol": "₹",
    "payment_methods": "UPI,Bank Transfer",
    "support_username": "@cytunn",
    "bot_name": "XYVEN REFER & EARN",
    "withdrawals_enabled": "1",
    "referrals_enabled": "1",
}

# 25 premium emoji slots. IDs come from PREMIUM_EMOJI_IDS.
EMOJI_FALLBACK = {
    "sparkle": "✨", "crown": "👑", "gem": "💎", "wallet": "👛",
    "money": "💰", "bank": "🏦", "card": "💳", "gift": "🎁",
    "users": "👥", "link": "🔗", "chart": "📊", "stats": "📈",
    "withdraw": "💸", "check": "✅", "cross": "❌", "clock": "⏳",
    "shield": "🛡️", "megaphone": "📢", "settings": "⚙️", "home": "🏠",
    "support": "🆘", "info": "ℹ️", "star": "⭐", "fire": "🔥",
    "rocket": "🚀",
}
try:
    EMOJI_IDS = json.loads(os.getenv("PREMIUM_EMOJI_IDS", "{}"))
    if not isinstance(EMOJI_IDS, dict):
        EMOJI_IDS = {}
except Exception:
    EMOJI_IDS = {}


def ce(key: str) -> str:
    """Return premium custom emoji HTML, or Unicode fallback."""
    fallback = EMOJI_FALLBACK.get(key, "✨")
    eid = EMOJI_IDS.get(key)
    if eid and str(eid).isdigit():
        return f'<tg-emoji emoji-id="{eid}">{fallback}</tg-emoji>'
    return fallback


def money(amount) -> str:
    sym = get_setting("currency_symbol", "₹")
    return f"{sym}{float(amount):,.2f}"


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("xyven")

LOOP = None
BOT = None

# ══════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════


def db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db():
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                referrer_id INTEGER,
                balance REAL NOT NULL DEFAULT 0,
                reserved REAL NOT NULL DEFAULT 0,
                total_earned REAL NOT NULL DEFAULT 0,
                total_withdrawn REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                reward REAL NOT NULL DEFAULT 2,
                rewarded INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                rewarded_at TEXT
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                description TEXT,
                reference TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                method TEXT NOT NULL,
                details TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                tx_id TEXT NOT NULL UNIQUE,
                admin_note TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS promo_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER UNIQUE,
                username TEXT,
                title TEXT,
                invite_link TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                auto_approve INTEGER NOT NULL DEFAULT 1,
                added_by INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_ref_referrer
                ON referrals(referrer_id, rewarded);
            CREATE INDEX IF NOT EXISTS idx_tx_user
                ON transactions(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_wd_user
                ON withdrawals(user_id, status);
            """
        )
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (k, v)
            )
        if not conn.execute("SELECT 1 FROM admins LIMIT 1").fetchone():
            conn.execute(
                "INSERT INTO admins(user_id, username, password_hash) VALUES(?,?,?)",
                (1, WEB_ADMIN_USERNAME,
                 generate_password_hash(WEB_ADMIN_PASSWORD)),
            )
    log.info("Database ready at %s", DB_PATH)


def get_setting(key, default=""):
    with db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )


def get_user(user_id):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id=?", (user_id,)
        ).fetchone()


def ensure_user(tg_user):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(user_id, username, first_name) "
            "VALUES(?,?,?)",
            (tg_user.id, tg_user.username or "", tg_user.first_name or ""),
        )
        conn.execute(
            "UPDATE users SET username=?, first_name=? WHERE user_id=?",
            (tg_user.username or "", tg_user.first_name or "", tg_user.id),
        )


def is_bot_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ══════════════════════════════════════════════════════════════════
# REFERRAL + BALANCE ENGINE
# ══════════════════════════════════════════════════════════════════


def create_pending_referral(referrer_id: int, referred_id: int):
    if referrer_id == referred_id:
        return False
    referrer = get_user(referrer_id)
    if not referrer:
        return False
    if get_setting("referrals_enabled", "1") != "1":
        return False
    reward = float(get_setting("referral_reward", "2"))
    with db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO referrals(referrer_id, referred_id, reward) "
            "VALUES(?,?,?)",
            (referrer_id, referred_id, reward),
        )
        return cur.rowcount > 0


def credit_pending_referral(referred_id: int):
    """Atomically credit one pending referral. Returns referrer row or None."""
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ref = conn.execute(
            "SELECT * FROM referrals WHERE referred_id=? AND rewarded=0",
            (referred_id,),
        ).fetchone()
        if not ref:
            conn.rollback()
            return None
        cur = conn.execute(
            "UPDATE referrals SET rewarded=1, rewarded_at=datetime('now') "
            "WHERE id=? AND rewarded=0",
            (ref["id"],),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return None
        reward = float(ref["reward"])
        conn.execute(
            "UPDATE users SET balance=balance+?, total_earned=total_earned+? "
            "WHERE user_id=?",
            (reward, reward, ref["referrer_id"]),
        )
        conn.execute(
            "INSERT INTO transactions(user_id,type,amount,description,reference) "
            "VALUES(?,?,?,?,?)",
            (ref["referrer_id"], "referral_bonus", reward,
             f"Referral reward for user {referred_id}", str(referred_id)),
        )
        conn.commit()
        return get_user(ref["referrer_id"])


def user_stats(user_id: int):
    with db() as conn:
        total_refs = conn.execute(
            "SELECT COUNT(*) c FROM referrals WHERE referrer_id=?", (user_id,)
        ).fetchone()["c"]
        successful = conn.execute(
            "SELECT COUNT(*) c FROM referrals WHERE referrer_id=? AND rewarded=1",
            (user_id,),
        ).fetchone()["c"]
        earned = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM transactions "
            "WHERE user_id=? AND type='referral_bonus'", (user_id,)
        ).fetchone()["s"]
        withdrawn = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM withdrawals "
            "WHERE user_id=? AND status='PAID'", (user_id,)
        ).fetchone()["s"]
        pending_wd = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM withdrawals "
            "WHERE user_id=? AND status IN ('PENDING','APPROVED')", (user_id,)
        ).fetchone()["s"]
    u = get_user(user_id)
    return {
        "total_referrals": total_refs,
        "successful": successful,
        "earned": float(earned),
        "withdrawn": float(withdrawn),
        "pending_withdrawals": float(pending_wd),
        "balance": float(u["balance"]) if u else 0.0,
        "reserved": float(u["reserved"]) if u else 0.0,
    }


# ══════════════════════════════════════════════════════════════════
# FORCE JOIN
# ══════════════════════════════════════════════════════════════════


def active_channels():
    with db() as conn:
        return conn.execute(
            "SELECT * FROM promo_channels WHERE is_active=1 ORDER BY id"
        ).fetchall()


async def is_member(bot, chat_id: int, user_id: int) -> bool:
    try:
        m = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception as exc:
        log.warning("Membership check failed for chat %s: %s", chat_id, exc)
        return False


async def unjoined_channels(bot, user_id: int):
    out = []
    for ch in active_channels():
        if not ch["chat_id"]:
            # Cannot verify. Do not fake it; surface to admin logs.
            log.warning("Channel %s has no numeric chat_id; skipping verification",
                        ch["id"])
            continue
        if not await is_member(bot, ch["chat_id"], user_id):
            out.append(ch)
    return out


async def send_join_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    channels = await unjoined_channels(context.bot, user.id)
    if not channels:
        return True
    rows = []
    for ch in channels:
        link = ch["invite_link"] or (
            f"https://t.me/{ch['username']}" if ch["username"] else None
        )
        if link:
            rows.append([InlineKeyboardButton(
                f"📣 JOIN {ch['title'] or 'CHANNEL'}", url=link
            )])
    rows.append([InlineKeyboardButton(
        "✅ VERIFY JOIN", callback_data="verify_join"
    )])
    text = (
        f"{ce('shield')} <b>CHANNEL VERIFICATION REQUIRED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"To use {get_setting('bot_name')} and earn rewards, join all "
        f"promotional channels below, then tap <b>VERIFY JOIN</b>.\n\n"
        f"{ce('info')} <i>If a channel uses join requests, your request "
        f"will be reviewed automatically where enabled.</i>"
    )
    kb = InlineKeyboardMarkup(rows)
    if update.callback_query:
        await update.callback_query.message.edit_text(
            text, reply_markup=kb, parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            text, reply_markup=kb, parse_mode=ParseMode.HTML
        )
    return False


async def require_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    pending = await unjoined_channels(context.bot, user.id)
    if pending:
        await send_join_prompt(update, context)
        return False
    return True


# ══════════════════════════════════════════════════════════════════
# BOT KEYBOARDS + MESSAGES
# ══════════════════════════════════════════════════════════════════


def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 MY ACCOUNT", callback_data="menu_account"),
         InlineKeyboardButton("🔗 REFER & EARN", callback_data="menu_refer")],
        [InlineKeyboardButton("💰 MY BALANCE", callback_data="menu_balance"),
         InlineKeyboardButton("💸 WITHDRAW", callback_data="menu_withdraw")],
        [InlineKeyboardButton("📊 STATISTICS", callback_data="menu_stats"),
         InlineKeyboardButton("📖 HOW IT WORKS", callback_data="menu_how")],
        [InlineKeyboardButton("🆘 SUPPORT", callback_data="menu_support")],
    ])


def back_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 MAIN MENU", callback_data="main_menu")]
    ])


def welcome_text(user):
    return (
        f"{ce('crown')} <b>WELCOME TO {get_setting('bot_name')}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Hello, <b>{html.escape(user.first_name or 'User')}</b>! 👋\n\n"
        f"Earn <b>{money(get_setting('referral_reward', '2'))}</b> for every "
        f"successful referral.\n\n"
        f"Invite friends, grow your balance, and withdraw once you reach "
        f"<b>{money(get_setting('min_withdrawal', '10'))}</b>.\n\n"
        f"{ce('sparkle')} <i>Your premium earning journey starts here.</i>"
    )


async def show_main_menu(update, context, edit=False):
    user = update.effective_user
    text = welcome_text(user)
    kb = main_menu_kb()
    if edit and update.callback_query:
        await update.callback_query.message.edit_text(
            text, reply_markup=kb, parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            text, reply_markup=kb, parse_mode=ParseMode.HTML
        )


# ══════════════════════════════════════════════════════════════════
# BOT HANDLERS — USER
# ══════════════════════════════════════════════════════════════════


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    existing = get_user(tg_user.id)
    ensure_user(tg_user)

    if not existing and context.args:
        try:
            referrer_id = int(context.args[0])
        except (ValueError, TypeError):
            referrer_id = None
        if referrer_id and referrer_id != tg_user.id:
            if create_pending_referral(referrer_id, tg_user.id):
                log.info("Pending referral %s -> %s", referrer_id, tg_user.id)

    if not await require_join(update, context):
        return
    await show_main_menu(update, context)


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_bot_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await admin_dashboard(update, context, edit=False)


async def cb_main_menu(update, context):
    q = update.callback_query
    await q.answer()
    await show_main_menu(update, context, edit=True)


async def cb_verify_join(update, context):
    q = update.callback_query
    await q.answer("Checking membership…")
    user = update.effective_user
    pending = await unjoined_channels(context.bot, user.id)
    if pending:
        await send_join_prompt(update, context)
        return
    referrer = credit_pending_referral(user.id)
    if referrer:
        try:
            await context.bot.send_message(
                referrer["user_id"],
                f"{ce('gift')} <b>REFERRAL REWARD CREDITED</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"You earned <b>{money(get_setting('referral_reward', '2'))}</b> "
                f"from a new verified referral.\n\n"
                f"{ce('wallet')} New balance: "
                f"<b>{money(referrer['balance'])}</b>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    await q.message.edit_text(
        f"{ce('check')} <b>VERIFICATION COMPLETE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"All promotional channels verified. Your earning features are now "
        f"unlocked.\n\n{welcome_text(user)}",
        reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML,
    )


async def cb_account(update, context):
    q = update.callback_query
    await q.answer()
    u = update.effective_user
    ensure_user(u)
    row = get_user(u.id)
    s = user_stats(u.id)
    link = f"https://t.me/{BOT_USERNAME}?start={u.id}"
    text = (
        f"{ce('gem')} <b>MY ACCOUNT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>Name:</b> {html.escape(u.first_name or 'User')}\n"
        f"🆔 <b>Telegram ID:</b> <code>{u.id}</code>\n"
        f"🔗 <b>Referral Link:</b>\n<code>{html.escape(link)}</code>\n\n"
        f"👥 <b>Total Referrals:</b> {s['total_referrals']}\n"
        f"✅ <b>Successful Referrals:</b> {s['successful']}\n"
        f"💰 <b>Total Earned:</b> {money(s['earned'])}\n"
        f"💳 <b>Available Balance:</b> {money(s['balance'])}\n"
        f"🔒 <b>Reserved:</b> {money(s['reserved'])}\n"
        f"📤 <b>Total Withdrawn:</b> {money(s['withdrawn'])}"
    )
    await q.message.edit_text(
        text, reply_markup=back_kb(), parse_mode=ParseMode.HTML
    )


async def cb_refer(update, context):
    q = update.callback_query
    await q.answer()
    if not await require_join(update, context):
        return
    u = update.effective_user
    link = f"https://t.me/{BOT_USERNAME}?start={u.id}"
    s = user_stats(u.id)
    share = (
        f"https://t.me/share/url?url={html.escape(link)}"
        f"&text=Join%20{html.escape(get_setting('bot_name'))}%20and%20earn!"
    )
    text = (
        f"{ce('link')} <b>REFER & EARN</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Earn <b>{money(get_setting('referral_reward', '2'))}</b> for every "
        f"friend who joins and verifies all channels.\n\n"
        f"<b>Your referral link:</b>\n<code>{html.escape(link)}</code>\n\n"
        f"👥 Successful referrals: <b>{s['successful']}</b>\n"
        f"💰 Referral earnings: <b>{money(s['earned'])}</b>\n\n"
        f"{ce('info')} <i>Rewards are credited after your friend passes "
        f"channel verification.</i>"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 SHARE LINK", url=share)],
        [InlineKeyboardButton("🏠 MAIN MENU", callback_data="main_menu")],
    ])
    await q.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def cb_balance(update, context):
    q = update.callback_query
    await q.answer()
    u = update.effective_user
    with db() as conn:
        txs = conn.execute(
            "SELECT * FROM transactions WHERE user_id=? "
            "ORDER BY id DESC LIMIT 15", (u.id,)
        ).fetchall()
    s = user_stats(u.id)
    lines = []
    for t in txs:
        sign = "+" if t["amount"] >= 0 else "−"
        lines.append(
            f"{sign}{money(abs(t['amount']))}  •  {html.escape(t['type'])}\n"
            f"<i>{html.escape(t['description'] or '')}</i>  "
            f"<code>{t['created_at'][:16]}</code>"
        )
    history = "\n\n".join(lines) if lines else "<i>No transactions yet.</i>"
    text = (
        f"{ce('wallet')} <b>MY BALANCE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💳 <b>Available:</b> {money(s['balance'])}\n"
        f"🔒 <b>Reserved:</b> {money(s['reserved'])}\n"
        f"💰 <b>Total Earned:</b> {money(s['earned'])}\n"
        f"📤 <b>Total Withdrawn:</b> {money(s['withdrawn'])}\n\n"
        f"{ce('chart')} <b>RECENT TRANSACTIONS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n{history}"
    )
    await q.message.edit_text(
        text, reply_markup=back_kb(), parse_mode=ParseMode.HTML
    )


async def cb_stats(update, context):
    q = update.callback_query
    await q.answer()
    u = update.effective_user
    s = user_stats(u.id)
    with db() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) c FROM withdrawals WHERE user_id=? "
            "AND status IN ('PENDING','APPROVED')", (u.id,)
        ).fetchone()["c"]
    text = (
        f"{ce('stats')} <b>MY STATISTICS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total Referrals: <b>{s['total_referrals']}</b>\n"
        f"✅ Successful: <b>{s['successful']}</b>\n"
        f"💰 Total Earnings: <b>{money(s['earned'])}</b>\n"
        f"💳 Available Balance: <b>{money(s['balance'])}</b>\n"
        f"💸 Total Withdrawn: <b>{money(s['withdrawn'])}</b>\n"
        f"⏳ Pending Withdrawals: <b>{pending}</b>"
    )
    await q.message.edit_text(
        text, reply_markup=back_kb(), parse_mode=ParseMode.HTML
    )


async def cb_how(update, context):
    q = update.callback_query
    await q.answer()
    reward = money(get_setting("referral_reward", "2"))
    minimum = money(get_setting("min_withdrawal", "10"))
    text = (
        f"{ce('info')} <b>HOW IT WORKS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<b>1.</b> Join all promotional channels.\n"
        f"<b>2.</b> Share your referral link with friends.\n"
        f"<b>3.</b> Earn <b>{reward}</b> when a new user joins through your "
        f"link and verifies all channels.\n"
        f"<b>4.</b> Reach <b>{minimum}</b> and request a withdrawal.\n"
        f"<b>5.</b> Admin reviews and processes your payout.\n\n"
        f"{ce('shield')} <i>One user can have only one referrer. Self-referral "
        f"and duplicate rewards are blocked.</i>"
    )
    await q.message.edit_text(
        text, reply_markup=back_kb(), parse_mode=ParseMode.HTML
    )


async def cb_support(update, context):
    q = update.callback_query
    await q.answer()
    sup = get_setting("support_username", "@cytunn")
    text = (
        f"{ce('support')} <b>SUPPORT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Need help? Contact: <b>{html.escape(sup)}</b>\n\n"
        f"{ce('info')} Include your Telegram ID "
        f"<code>{update.effective_user.id}</code> for faster assistance."
    )
    await q.message.edit_text(
        text, reply_markup=back_kb(), parse_mode=ParseMode.HTML
    )


# ══════════════════════════════════════════════════════════════════
# WITHDRAWAL — USER FLOW
# ══════════════════════════════════════════════════════════════════


def payment_methods():
    return [m.strip() for m in get_setting("payment_methods", "UPI").split(",")
            if m.strip()]


async def cb_withdraw(update, context):
    q = update.callback_query
    await q.answer()
    if not await require_join(update, context):
        return
    if get_setting("withdrawals_enabled", "1") != "1":
        await q.message.edit_text(
            "⛔ Withdrawals are temporarily disabled.", reply_markup=back_kb()
        )
        return
    u = update.effective_user
    s = user_stats(u.id)
    minimum = float(get_setting("min_withdrawal", "10"))
    if s["balance"] < minimum:
        await q.message.edit_text(
            f"{ce('cross')} <b>INSUFFICIENT BALANCE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Available: <b>{money(s['balance'])}</b>\n"
            f"Minimum withdrawal: <b>{money(minimum)}</b>\n\n"
            f"Invite more friends to reach the minimum.",
            reply_markup=back_kb(), parse_mode=ParseMode.HTML,
        )
        return
    context.user_data["state"] = "wd_amount"
    await q.message.edit_text(
        f"{ce('withdraw')} <b>WITHDRAW FUNDS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Available balance: <b>{money(s['balance'])}</b>\n"
        f"Minimum: <b>{money(minimum)}</b>\n\n"
        f"Send the amount you want to withdraw (numbers only).",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ CANCEL", callback_data="main_menu")]
        ]),
        parse_mode=ParseMode.HTML,
    )


async def wd_choose_method(update, context):
    q = update.callback_query
    method = q.data.split(":", 1)[1]
    context.user_data["wd_method"] = method
    context.user_data["state"] = "wd_details"
    await q.answer()
    await q.message.edit_text(
        f"{ce('card')} <b>{html.escape(method)} DETAILS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Send your {html.escape(method)} payment details.\n"
        f"<i>Example: yourname@upi or account number + IFSC.</i>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ CANCEL", callback_data="main_menu")]
        ]),
        parse_mode=ParseMode.HTML,
    )


def create_withdrawal(user_id, amount, method, details):
    tx_id = "WD" + secrets.token_hex(6).upper()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "UPDATE users SET balance=balance-?, reserved=reserved+? "
            "WHERE user_id=? AND balance>=?",
            (amount, amount, user_id, amount),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return None
        conn.execute(
            "INSERT INTO withdrawals(user_id,amount,method,details,tx_id) "
            "VALUES(?,?,?,?,?)",
            (user_id, amount, method, details, tx_id),
        )
        conn.execute(
            "INSERT INTO transactions(user_id,type,amount,description,reference) "
            "VALUES(?,?,?,?,?)",
            (user_id, "withdrawal_reserve", -amount,
             f"Withdrawal reserved ({method})", tx_id),
        )
        conn.commit()
        return conn.execute(
            "SELECT * FROM withdrawals WHERE tx_id=?", (tx_id,)
        ).fetchone()


def process_withdrawal_action(wid, action, admin_note=""):
    """Shared by bot and web. action: approve|reject|paid."""
    with db() as conn:
        w = conn.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        if not w:
            return None, "Not found"
        if action == "approve":
            if w["status"] != "PENDING":
                return None, "Only PENDING can be approved"
            conn.execute(
                "UPDATE withdrawals SET status='APPROVED', updated_at=datetime('now'), "
                "admin_note=? WHERE id=?", (admin_note, wid),
            )
        elif action == "reject":
            if w["status"] not in ("PENDING", "APPROVED"):
                return None, "Cannot reject this status"
            conn.execute(
                "UPDATE withdrawals SET status='REJECTED', updated_at=datetime('now'), "
                "admin_note=? WHERE id=?", (admin_note, wid),
            )
            conn.execute(
                "UPDATE users SET reserved=reserved-?, balance=balance+? "
                "WHERE user_id=? AND reserved>=?",
                (w["amount"], w["amount"], w["user_id"], w["amount"]),
            )
            conn.execute(
                "INSERT INTO transactions(user_id,type,amount,description,reference) "
                "VALUES(?,?,?,?,?)",
                (w["user_id"], "withdrawal_refund", w["amount"],
                 "Withdrawal rejected — amount released", w["tx_id"]),
            )
        elif action == "paid":
            if w["status"] != "APPROVED":
                return None, "Only APPROVED can be marked PAID"
            conn.execute(
                "UPDATE withdrawals SET status='PAID', updated_at=datetime('now'), "
                "admin_note=? WHERE id=?", (admin_note, wid),
            )
            conn.execute(
                "UPDATE users SET reserved=reserved-?, total_withdrawn=total_withdrawn+? "
                "WHERE user_id=? AND reserved>=?",
                (w["amount"], w["amount"], w["user_id"], w["amount"]),
            )
            conn.execute(
                "INSERT INTO transactions(user_id,type,amount,description,reference) "
                "VALUES(?,?,?,?,?)",
                (w["user_id"], "withdrawal_paid", -w["amount"],
                 "Withdrawal marked paid", w["tx_id"]),
            )
        else:
            return None, "Unknown action"
        conn.commit()
    return conn.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone(), None


# ══════════════════════════════════════════════════════════════════
# BOT ADMIN PANEL
# ══════════════════════════════════════════════════════════════════


def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 ALL USERS", callback_data="adm_users"),
         InlineKeyboardButton("📊 BOT STATISTICS", callback_data="adm_stats")],
        [InlineKeyboardButton("📢 BROADCAST", callback_data="adm_broadcast"),
         InlineKeyboardButton("💰 WITHDRAWAL REQUESTS", callback_data="adm_wds")],
        [InlineKeyboardButton("📺 ADD PROMO CHANNEL", callback_data="adm_ch_add"),
         InlineKeyboardButton("🗑 REMOVE PROMO CHANNEL", callback_data="adm_ch_list")],
        [InlineKeyboardButton("📋 MANAGE CHANNELS", callback_data="adm_ch_list"),
         InlineKeyboardButton("⚙️ BOT SETTINGS", callback_data="adm_settings")],
        [InlineKeyboardButton("🏠 MAIN MENU", callback_data="main_menu")],
    ])


def global_stats():
    with db() as conn:
        q = lambda sql, args=(): conn.execute(sql, args).fetchone()[0]
        return {
            "users": q("SELECT COUNT(*) FROM users"),
            "referrals": q("SELECT COUNT(*) FROM referrals WHERE rewarded=1"),
            "reward_paid": q("SELECT COALESCE(SUM(amount),0) FROM transactions "
                             "WHERE type='referral_bonus'"),
            "pending_wd": q("SELECT COALESCE(SUM(amount),0) FROM withdrawals "
                            "WHERE status='PENDING'"),
            "pending_count": q("SELECT COUNT(*) FROM withdrawals WHERE status='PENDING'"),
            "approved_wd": q("SELECT COALESCE(SUM(amount),0) FROM withdrawals "
                             "WHERE status='APPROVED'"),
            "available": q("SELECT COALESCE(SUM(balance),0) FROM users"),
            "channels": q("SELECT COUNT(*) FROM promo_channels WHERE is_active=1"),
        }


async def admin_dashboard(update, context, edit=False):
    s = global_stats()
    text = (
        f"{ce('shield')} <b>ADMIN DASHBOARD</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total Users: <b>{s['users']}</b>\n"
        f"🔗 Successful Referrals: <b>{s['referrals']}</b>\n"
        f"🎁 Referral Rewards Paid: <b>{money(s['reward_paid'])}</b>\n"
        f"⏳ Pending Withdrawals: <b>{s['pending_count']}</b> "
        f"({money(s['pending_wd'])})\n"
        f"✅ Approved Withdrawals: <b>{money(s['approved_wd'])}</b>\n"
        f"💳 Available User Balance: <b>{money(s['available'])}</b>\n"
        f"📢 Active Promo Channels: <b>{s['channels']}</b>"
    )
    if edit and update.callback_query:
        await update.callback_query.message.edit_text(
            text, reply_markup=admin_kb(), parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text(
            text, reply_markup=admin_kb(), parse_mode=ParseMode.HTML
        )


async def cb_admin(update, context):
    q = update.callback_query
    if not is_bot_admin(update.effective_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True)
        return
    data = q.data
    if data == "adm_dashboard":
        await q.answer()
        await admin_dashboard(update, context, edit=True)
    elif data == "adm_users":
        await q.answer()
        with db() as conn:
            users = conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT 30"
            ).fetchall()
        lines = [
            f"<code>{u['user_id']}</code>  {html.escape(u['first_name'] or '')}  "
            f"💰 {money(u['balance'])}"
            for u in users
        ]
        await q.message.edit_text(
            f"{ce('users')} <b>RECENT USERS</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            + ("\n".join(lines) if lines else "<i>No users.</i>"),
            reply_markup=admin_kb(), parse_mode=ParseMode.HTML,
        )
    elif data == "adm_stats":
        await q.answer()
        await admin_dashboard(update, context, edit=True)
    elif data == "adm_wds":
        await q.answer()
        await show_pending_withdrawals(update, context)
    elif data == "adm_broadcast":
        await q.answer()
        context.user_data["state"] = "adm_broadcast"
        await q.message.edit_text(
            f"{ce('megaphone')} <b>BROADCAST</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Send the announcement text, or a photo with caption.\n"
            f"Send /cancel to abort.",
            reply_markup=admin_kb(), parse_mode=ParseMode.HTML,
        )
    elif data == "adm_ch_add":
        await q.answer()
        context.user_data["state"] = "adm_ch_link"
        await q.message.edit_text(
            f"{ce('megaphone')} <b>ADD PROMO CHANNEL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Send the channel link or @username.\n"
            f"Examples:\n<code>https://t.me/examplechannel</code>\n"
            f"<code>@examplechannel</code>\n\n"
            f"<b>Private invite links:</b> Telegram does not expose the numeric "
            f"chat ID from an invite hash. After sending the link, you will be "
            f"asked for the numeric chat ID (e.g. <code>-1001234567890</code>).\n\n"
            f"Make sure the bot is an administrator in the channel.",
            reply_markup=admin_kb(), parse_mode=ParseMode.HTML,
        )
    elif data == "adm_ch_list":
        await q.answer()
        await show_channels(update, context)
    elif data == "adm_settings":
        await q.answer()
        text = (
            f"{ce('settings')} <b>BOT SETTINGS</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 Referral Reward: <b>{money(get_setting('referral_reward', '2'))}</b>\n"
            f"💸 Min Withdrawal: <b>{money(get_setting('min_withdrawal', '10'))}</b>\n"
            f"🏦 Payment Methods: <b>{html.escape(get_setting('payment_methods'))}</b>\n"
            f"🆘 Support: <b>{html.escape(get_setting('support_username'))}</b>\n"
            f"🔗 Referrals Enabled: <b>{get_setting('referrals_enabled', '1')}</b>\n"
            f"💸 Withdrawals Enabled: <b>{get_setting('withdrawals_enabled', '1')}</b>\n\n"
            f"Use the website dashboard to edit settings."
        )
        await q.message.edit_text(
            text, reply_markup=admin_kb(), parse_mode=ParseMode.HTML
        )


async def show_pending_withdrawals(update, context):
    q = update.callback_query
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM withdrawals WHERE status='PENDING' ORDER BY id ASC LIMIT 10"
        ).fetchall()
    if not rows:
        await q.message.edit_text(
            "✅ No pending withdrawal requests.",
            reply_markup=admin_kb(), parse_mode=ParseMode.HTML,
        )
        return
    text = f"{ce('withdraw')} <b>PENDING WITHDRAWALS</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    kb_rows = []
    for w in rows:
        text += (
            f"#{w['id']} • <code>{w['tx_id']}</code>\n"
            f"User: <code>{w['user_id']}</code> • {money(w['amount'])}\n"
            f"{html.escape(w['method'])}: <code>{html.escape(w['details'])}</code>\n\n"
        )
        kb_rows.append([
            InlineKeyboardButton(f"✅ APPROVE #{w['id']}",
                                 callback_data=f"adm_wd:approve:{w['id']}"),
            InlineKeyboardButton(f"❌ REJECT #{w['id']}",
                                 callback_data=f"adm_wd:reject:{w['id']}"),
        ])
    kb_rows.append([InlineKeyboardButton("🏠 ADMIN PANEL", callback_data="adm_dashboard")])
    await q.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.HTML
    )


async def cb_admin_wd(update, context):
    q = update.callback_query
    if not is_bot_admin(update.effective_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True)
        return
    _, action, wid = q.data.split(":")
    wid = int(wid)
    w, err = process_withdrawal_action(wid, action, f"by {update.effective_user.id}")
    if err:
        await q.answer(f"Error: {err}", show_alert=True)
        return
    await q.answer(f"Withdrawal {action}d")
    try:
        status_text = {
            "approve": "✅ Your withdrawal has been approved and is being processed.",
            "reject": "❌ Your withdrawal was rejected. The amount has been returned to your balance.",
            "paid": "💸 Your withdrawal has been marked as PAID.",
        }[action]
        await context.bot.send_message(
            w["user_id"],
            f"{ce('wallet')} <b>WITHDRAWAL UPDATE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Amount: <b>{money(w['amount'])}</b>\n"
            f"Transaction: <code>{w['tx_id']}</code>\n\n{status_text}",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
    await show_pending_withdrawals(update, context)


async def show_channels(update, context):
    q = update.callback_query
    with db() as conn:
        rows = conn.execute("SELECT * FROM promo_channels ORDER BY id").fetchall()
    if not rows:
        await q.message.edit_text(
            "No promotional channels configured.",
            reply_markup=admin_kb(), parse_mode=ParseMode.HTML,
        )
        return
    text = f"{ce('megaphone')} <b>PROMO CHANNELS</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    kb_rows = []
    for ch in rows:
        status = "🟢 ACTIVE" if ch["is_active"] else "🔴 DISABLED"
        text += (
            f"<b>{html.escape(ch['title'] or 'Untitled')}</b> • {status}\n"
            f"chat_id: <code>{ch['chat_id']}</code> • "
            f"@{ch['username'] or '—'}\n\n"
        )
        kb_rows.append([
            InlineKeyboardButton(
                f"{'🔴 DISABLE' if ch['is_active'] else '🟢 ENABLE'} {ch['id']}",
                callback_data=f"adm_ch:toggle:{ch['id']}",
            ),
            InlineKeyboardButton(
                f"🗑 DELETE {ch['id']}", callback_data=f"adm_ch:del:{ch['id']}"
            ),
            InlineKeyboardButton(
                f"🔍 CHECK {ch['id']}", callback_data=f"adm_ch:check:{ch['id']}"
            ),
        ])
    kb_rows.append([InlineKeyboardButton("🏠 ADMIN PANEL", callback_data="adm_dashboard")])
    await q.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode=ParseMode.HTML
    )


async def cb_admin_ch(update, context):
    q = update.callback_query
    if not is_bot_admin(update.effective_user.id):
        await q.answer("⛔ Unauthorized", show_alert=True)
        return
    _, action, cid = q.data.split(":")
    cid = int(cid)
    if action == "toggle":
        with db() as conn:
            conn.execute(
                "UPDATE promo_channels SET is_active=1-is_active WHERE id=?", (cid,)
            )
        await q.answer("Channel toggled")
        await show_channels(update, context)
    elif action == "del":
        with db() as conn:
            conn.execute("DELETE FROM promo_channels WHERE id=?", (cid,))
        await q.answer("Channel deleted")
        await show_channels(update, context)
    elif action == "check":
        with db() as conn:
            ch = conn.execute(
                "SELECT * FROM promo_channels WHERE id=?", (cid,)
            ).fetchone()
        if not ch or not ch["chat_id"]:
            await q.answer("No numeric chat_id configured", show_alert=True)
            return
        try:
            chat = await context.bot.get_chat(ch["chat_id"])
            me = await context.bot.get_me()
            member = await context.bot.get_chat_member(ch["chat_id"], me.id)
            ok = member.status == "administrator"
            await q.answer(
                f"Resolved: {chat.title}\nBot admin: {ok}", show_alert=True
            )
        except Exception as exc:
            await q.answer(f"Cannot verify: {exc}", show_alert=True)


# ══════════════════════════════════════════════════════════════════
# TEXT INPUT / STATE MACHINE
# ══════════════════════════════════════════════════════════════════


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    state = context.user_data.get("state")

    if text == "/cancel":
        context.user_data.pop("state", None)
        await update.message.reply_text(
            "Cancelled.", reply_markup=main_menu_kb()
        )
        return

    # ── User withdrawal ─────────────────────────────────────
    if state == "wd_amount":
        try:
            amount = round(float(text), 2)
        except ValueError:
            await update.message.reply_text("Send a valid number.")
            return
        minimum = float(get_setting("min_withdrawal", "10"))
        u = get_user(user.id)
        if amount < minimum:
            await update.message.reply_text(
                f"Minimum withdrawal is {money(minimum)}."
            )
            return
        if amount > float(u["balance"]):
            await update.message.reply_text(
                f"Amount exceeds available balance ({money(u['balance'])})."
            )
            return
        context.user_data["wd_amount"] = amount
        methods = payment_methods()
        rows = [
            [InlineKeyboardButton(f"💳 {m}", callback_data=f"wd_method:{m}")]
            for m in methods
        ]
        context.user_data["state"] = "wd_method"
        await update.message.reply_text(
            f"Choose payment method for {money(amount)}:",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    if state == "wd_details":
        amount = context.user_data.get("wd_amount")
        method = context.user_data.get("wd_method")
        if not amount or not method:
            context.user_data.pop("state", None)
            await update.message.reply_text("Session expired. Start again.")
            return
        w = create_withdrawal(user.id, amount, method, text[:400])
        context.user_data.pop("state", None)
        if not w:
            await update.message.reply_text("Could not create request. Try again.")
            return
        await update.message.reply_text(
            f"{ce('check')} <b>WITHDRAWAL REQUEST CREATED</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Amount: <b>{money(w['amount'])}</b>\n"
            f"Method: <b>{html.escape(w['method'])}</b>\n"
            f"Details: <code>{html.escape(w['details'])}</code>\n"
            f"Transaction ID: <code>{w['tx_id']}</code>\n"
            f"Status: <b>PENDING</b>\n\n"
            f"{ce('info')} Admin will review your request.",
            reply_markup=main_menu_kb(), parse_mode=ParseMode.HTML,
        )
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"{ce('withdraw')} <b>NEW WITHDRAWAL REQUEST</b>\n"
                    f"User: <code>{user.id}</code>\n"
                    f"Amount: <b>{money(w['amount'])}</b>\n"
                    f"Method: {html.escape(w['method'])}\n"
                    f"Details: <code>{html.escape(w['details'])}</code>\n"
                    f"TX: <code>{w['tx_id']}</code>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        return

    # ── Admin channel add ──────────────────────────────────
    if state == "adm_ch_link":
        if not is_bot_admin(user.id):
            return
        context.user_data["ch_pending_link"] = text
        parsed = parse_channel_link(text)
        if parsed.get("private"):
            context.user_data["state"] = "adm_ch_chatid"
            await update.message.reply_text(
                f"{ce('info')} Private invite link detected.\n\n"
                f"Telegram does not reveal the numeric channel ID from an "
                f"invite hash. Send the numeric chat ID "
                f"(e.g. <code>-1001234567890</code>), or /cancel.",
                parse_mode=ParseMode.HTML,
            )
            return
        await add_channel_from_parsed(update, context, parsed)
        return

    if state == "adm_ch_chatid":
        if not is_bot_admin(user.id):
            return
        if not text.lstrip("-").isdigit():
            await update.message.reply_text("Send a valid numeric chat ID.")
            return
        parsed = {"chat_id": int(text)}
        await add_channel_from_parsed(update, context, parsed)
        return

    # ── Broadcast ──────────────────────────────────────────
    if state == "adm_broadcast":
        if not is_bot_admin(user.id):
            return
        context.user_data.pop("state", None)
        await run_broadcast(update, context, text=text)
        return

    # Default
    await update.message.reply_text(
        "Use the menu below.", reply_markup=main_menu_kb()
    )


def parse_channel_link(text):
    t = text.strip()
    if t.startswith("@"):
        return {"username": t[1:]}
    if "t.me/" in t:
        part = t.split("t.me/", 1)[1].split("?", 1)[0].strip("/")
        if part.startswith("+") or part.startswith("joinchat"):
            return {"private": True}
        return {"username": part}
    if t.lstrip("-").isdigit():
        return {"chat_id": int(t)}
    return {"username": t}


async def add_channel_from_parsed(update, context, parsed):
    user = update.effective_user
    link = context.user_data.pop("ch_pending_link", "")
    try:
        if parsed.get("chat_id"):
            chat = await context.bot.get_chat(parsed["chat_id"])
        else:
            chat = await context.bot.get_chat("@" + parsed["username"])
    except Exception as exc:
        context.user_data.pop("state", None)
        await update.message.reply_text(
            f"{ce('cross')} Could not resolve channel:\n<code>{html.escape(str(exc))}</code>\n\n"
            f"Make sure the bot is an administrator in the channel.",
            parse_mode=ParseMode.HTML,
        )
        return

    bot_admin = False
    try:
        me = await context.bot.get_me()
        m = await context.bot.get_chat_member(chat.id, me.id)
        bot_admin = m.status == "administrator"
    except Exception:
        pass

    invite = chat.invite_link or (
        f"https://t.me/{chat.username}" if chat.username else link
    )
    with db() as conn:
        conn.execute(
            "INSERT INTO promo_channels(chat_id, username, title, invite_link, added_by) "
            "VALUES(?,?,?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, "
            "username=excluded.username, invite_link=excluded.invite_link, is_active=1",
            (chat.id, chat.username or "", chat.title or "",
             invite, user.id),
        )
    context.user_data.pop("state", None)
    warning = "" if bot_admin else (
        "\n\n⚠️ <b>Warning:</b> the bot is not an administrator in this channel. "
        "Membership verification will fail until you add it as admin with "
        "“Invite Users” permission."
    )
    await update.message.reply_text(
        f"{ce('check')} <b>CHANNEL ADDED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Title: <b>{html.escape(chat.title or '')}</b>\n"
        f"Chat ID: <code>{chat.id}</code>\n"
        f"Username: @{chat.username or '—'}\n"
        f"Invite: {html.escape(invite or '—')}{warning}",
        reply_markup=admin_kb(), parse_mode=ParseMode.HTML,
    )


async def run_broadcast(update, context, text, photo=None):
    with db() as conn:
        users = [r["user_id"] for r in conn.execute("SELECT user_id FROM users")]
    sent = failed = 0
    await update.message.reply_text(f"Broadcasting to {len(users)} users…")
    for uid in users:
        try:
            if photo:
                await context.bot.send_photo(
                    uid, photo=photo, caption=text,
                    parse_mode=ParseMode.HTML
                )
            else:
                await context.bot.send_message(
                    uid, text, parse_mode=ParseMode.HTML
                )
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await update.message.reply_text(
        f"{ce('check')} Broadcast complete.\n✅ Sent: {sent}\n❌ Failed: {failed}"
    )


async def handle_photo(update, context):
    if not is_bot_admin(update.effective_user.id):
        return
    if context.user_data.get("state") == "adm_broadcast":
        context.user_data.pop("state", None)
        photo = update.message.photo[-1].file_id
        caption = update.message.caption or ""
        await run_broadcast(update, context, text=caption, photo=photo)


# ══════════════════════════════════════════════════════════════════
# JOIN REQUEST HANDLER
# ══════════════════════════════════════════════════════════════════


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    with db() as conn:
        ch = conn.execute(
            "SELECT * FROM promo_channels WHERE chat_id=?", (req.chat.id,)
        ).fetchone()
    if not ch:
        log.info("Ignoring join request for unconfigured chat %s", req.chat.id)
        return
    if not ch["auto_approve"]:
        return
    try:
        await context.bot.approve_chat_join_request(
            chat_id=req.chat.id, user_id=req.from_user.id
        )
        log.info("Approved join request %s -> %s", req.from_user.id, req.chat.id)
        try:
            await context.bot.send_message(
                req.from_user.id,
                f"{ce('check')} Your request to join "
                f"<b>{html.escape(ch['title'] or 'the channel')}</b> was approved.\n\n"
                f"Return to the bot and tap <b>VERIFY JOIN</b>.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    except Exception as exc:
        log.warning("Could not approve join request: %s", exc)


# ══════════════════════════════════════════════════════════════════
# FLASK WEB DASHBOARD
# ══════════════════════════════════════════════════════════════════

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=WEBHOOK_URL.startswith("https"),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(32)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def csrf_protect():
    if request.path.startswith("/webhook") or request.path == "/health":
        return
    if request.method == "POST":
        token = session.get("_csrf")
        if not token or token != request.form.get("_csrf"):
            abort(400)


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("admin_user"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        with db() as conn:
            admin = conn.execute(
                "SELECT * FROM admins WHERE username=?", (username,)
            ).fetchone()
        if admin and check_password_hash(admin["password_hash"], password):
            session.clear()
            session["admin_user"] = admin["username"]
            session["admin_id"] = admin["user_id"]
            session.permanent = True
            return redirect(url_for("overview"))
        flash("Invalid username or password", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def overview():
    s = global_stats()
    with db() as conn:
        days = conn.execute(
            "SELECT date(created_at) d, COUNT(*) c FROM referrals "
            "WHERE rewarded=1 AND created_at >= date('now','-6 days') "
            "GROUP BY d ORDER BY d"
        ).fetchall()
        wdays = conn.execute(
            "SELECT date(created_at) d, COUNT(*) c FROM withdrawals "
            "WHERE created_at >= date('now','-6 days') GROUP BY d ORDER BY d"
        ).fetchall()
    return render_template(
        "overview.html", s=s,
        ref_labels=[r["d"] for r in days],
        ref_values=[r["c"] for r in days],
        wd_labels=[r["d"] for r in wdays],
        wd_values=[r["c"] for r in wdays],
    )


@app.route("/users")
@login_required
def users():
    with db() as conn:
        rows = conn.execute(
            "SELECT u.*, "
            "(SELECT COUNT(*) FROM referrals r WHERE r.referrer_id=u.user_id "
            "AND r.rewarded=1) refs "
            "FROM users u ORDER BY u.created_at DESC LIMIT 500"
        ).fetchall()
    return render_template("users.html", users=rows)


@app.route("/referrals")
@login_required
def referrals():
    with db() as conn:
        rows = conn.execute(
            "SELECT r.*, u.first_name, u.username FROM referrals r "
            "LEFT JOIN users u ON u.user_id=r.referrer_id "
            "ORDER BY r.id DESC LIMIT 500"
        ).fetchall()
    return render_template("referrals.html", referrals=rows)


@app.route("/withdrawals")
@login_required
def withdrawals():
    with db() as conn:
        rows = conn.execute(
            "SELECT w.*, u.first_name, u.username FROM withdrawals w "
            "LEFT JOIN users u ON u.user_id=w.user_id "
            "ORDER BY w.id DESC LIMIT 500"
        ).fetchall()
    return render_template("withdrawals.html", withdrawals=rows)


@app.route("/withdrawals/<int:wid>/<action>", methods=["POST"])
@login_required
def withdrawal_action(wid, action):
    if action not in ("approve", "reject", "paid"):
        abort(400)
    w, err = process_withdrawal_action(wid, action, f"web:{session['admin_user']}")
    if err:
        flash(err, "error")
    else:
        flash(f"Withdrawal #{wid} {action}d.", "success")
        notify_user(
            w["user_id"],
            f"{ce('wallet')} <b>WITHDRAWAL UPDATE</b>\n"
            f"Amount: <b>{money(w['amount'])}</b>\n"
            f"TX: <code>{w['tx_id']}</code>\n"
            f"Status: <b>{w['status']}</b>",
        )
    return redirect(url_for("withdrawals"))


@app.route("/channels")
@login_required
def channels():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM promo_channels ORDER BY id"
        ).fetchall()
    return render_template("channels.html", channels=rows)


@app.route("/channels/add", methods=["POST"])
@login_required
def channel_add():
    chat_id = request.form.get("chat_id", "").strip()
    username = request.form.get("username", "").strip().lstrip("@")
    title = request.form.get("title", "").strip()
    invite = request.form.get("invite_link", "").strip()
    if not chat_id.lstrip("-").isdigit():
        flash("Numeric chat_id is required for reliable verification.", "error")
        return redirect(url_for("channels"))
    with db() as conn:
        conn.execute(
            "INSERT INTO promo_channels(chat_id, username, title, invite_link, added_by) "
            "VALUES(?,?,?,?,1) ON CONFLICT(chat_id) DO UPDATE SET "
            "username=excluded.username, title=excluded.title, "
            "invite_link=excluded.invite_link, is_active=1",
            (int(chat_id), username, title, invite or (
                f"https://t.me/{username}" if username else ""
            )),
        )
    flash("Channel saved.", "success")
    return redirect(url_for("channels"))


@app.route("/channels/<int:cid>/toggle", methods=["POST"])
@login_required
def channel_toggle(cid):
    with db() as conn:
        conn.execute(
            "UPDATE promo_channels SET is_active=1-is_active WHERE id=?", (cid,)
        )
    return redirect(url_for("channels"))


@app.route("/channels/<int:cid>/delete", methods=["POST"])
@login_required
def channel_delete(cid):
    with db() as conn:
        conn.execute("DELETE FROM promo_channels WHERE id=?", (cid,))
    return redirect(url_for("channels"))


@app.route("/transactions")
@login_required
def transactions():
    with db() as conn:
        rows = conn.execute(
            "SELECT t.*, u.first_name FROM transactions t "
            "LEFT JOIN users u ON u.user_id=t.user_id "
            "ORDER BY t.id DESC LIMIT 500"
        ).fetchall()
    return render_template("transactions.html", transactions=rows)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        for key in (
            "referral_reward", "min_withdrawal", "payment_methods",
            "support_username", "bot_name", "currency_symbol",
            "withdrawals_enabled", "referrals_enabled",
        ):
            if key in request.form:
                set_setting(key, request.form[key].strip())
        flash("Settings saved.", "success")
        return redirect(url_for("settings"))
    data = {k: get_setting(k, v) for k, v in DEFAULT_SETTINGS.items()}
    return render_template("settings.html", data=data)


@app.route("/health")
def health():
    return {"status": "ok", "service": "xyven", "time": datetime.utcnow().isoformat()}


# ══════════════════════════════════════════════════════════════════
# WEBHOOK
# ══════════════════════════════════════════════════════════════════


@app.post("/webhook/<secret>")
def webhook(secret):
    if secret != WEBHOOK_SECRET:
        abort(403)
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != WEBHOOK_SECRET:
        abort(403)
    data = request.get_json(force=True, silent=True)
    if not data:
        abort(400)
    update = Update.de_json(data, BOT)
    if LOOP is None:
        abort(503)
    future = asyncio.run_coroutine_threadsafe(
        BOT.update_queue.put(update), LOOP
    )
    try:
        future.result(timeout=10)
    except Exception:
        abort(503)
    return "OK"


def notify_user(user_id, text):
    """Thread-safe notification from Flask route to Telegram."""
    if not BOT or not LOOP:
        return
    async def _send():
        try:
            await BOT.send_message(user_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass
    asyncio.run_coroutine_threadsafe(_send(), LOOP)


# ══════════════════════════════════════════════════════════════════
# TEMPLATES
# ══════════════════════════════════════════════════════════════════

BASE_CSS = """
:root{--bg:#070b14;--panel:rgba(18,26,43,.72);--line:rgba(120,160,255,.14);
--text:#e8eefc;--muted:#8ea0c4;--green:#2ee6a8;--blue:#4f8cff;--red:#ff5b6e;
--gold:#ffcf6a}
*{box-sizing:border-box}
body{margin:0;font-family:'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:radial-gradient(1200px 700px at 15% -10%,rgba(79,140,255,.18),transparent 60%),
radial-gradient(900px 600px at 110% 20%,rgba(46,230,168,.12),transparent 60%),var(--bg);
color:var(--text);min-height:100vh}
a{color:var(--blue);text-decoration:none}
.layout{display:flex;min-height:100vh}
.sidebar{width:250px;padding:28px 18px;border-right:1px solid var(--line);
background:rgba(9,14,24,.85);backdrop-filter:blur(18px);position:sticky;top:0;height:100vh}
.brand{font-weight:800;font-size:19px;letter-spacing:.5px;margin-bottom:4px}
.brand span{color:var(--green)}
.tag{font-size:11px;color:var(--muted);letter-spacing:1.5px;margin-bottom:28px}
.nav a{display:flex;gap:10px;align-items:center;padding:11px 13px;border-radius:11px;
color:var(--muted);font-size:14px;margin-bottom:4px;transition:.18s}
.nav a:hover,.nav a.active{background:rgba(79,140,255,.12);color:#fff}
.main{flex:1;padding:30px 34px;max-width:calc(100vw - 250px)}
.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:26px;gap:16px}
h1{font-size:24px;margin:0;font-weight:750}
.sub{color:var(--muted);font-size:13px;margin-top:5px}
.btn{display:inline-flex;align-items:center;gap:7px;padding:9px 15px;border-radius:10px;
border:1px solid var(--line);background:rgba(255,255,255,.04);color:var(--text);
font-size:13px;cursor:pointer;transition:.18s}
.btn:hover{background:rgba(255,255,255,.09)}
.btn.green{background:rgba(46,230,168,.14);border-color:rgba(46,230,168,.35);color:var(--green)}
.btn.red{background:rgba(255,91,110,.13);border-color:rgba(255,91,110,.3);color:var(--red)}
.btn.blue{background:rgba(79,140,255,.15);border-color:rgba(79,140,255,.35);color:#9dc0ff}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:16px;margin-bottom:24px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px;
backdrop-filter:blur(20px);box-shadow:0 0 0 1px rgba(255,255,255,.02) inset,
0 18px 50px rgba(0,0,0,.28)}
.card .label{font-size:11.5px;color:var(--muted);letter-spacing:1.2px;text-transform:uppercase}
.card .value{font-size:25px;font-weight:800;margin-top:8px}
.card .hint{font-size:12px;color:var(--muted);margin-top:5px}
.card.green .value{color:var(--green)}.card.blue .value{color:#7aa7ff}
.card.gold .value{color:var(--gold)}.card.red .value{color:var(--red)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:20px;
backdrop-filter:blur(20px);overflow:auto}
.panel h2{font-size:15px;margin:0 0 14px;font-weight:700}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:600;padding:10px 8px;
border-bottom:1px solid var(--line);font-size:11px;letter-spacing:1px;text-transform:uppercase}
td{padding:11px 8px;border-bottom:1px solid rgba(255,255,255,.05)}
tr:hover td{background:rgba(255,255,255,.025)}
.pill{display:inline-block;padding:3px 9px;border-radius:999px;font-size:10.5px;font-weight:700}
.pill.PENDING{background:rgba(255,207,106,.13);color:var(--gold)}
.pill.APPROVED{background:rgba(79,140,255,.15);color:#8fb6ff}
.pill.PAID{background:rgba(46,230,168,.14);color:var(--green)}
.pill.REJECTED{background:rgba(255,91,110,.13);color:var(--red)}
.flash{padding:12px 16px;border-radius:11px;margin-bottom:16px;font-size:13px}
.flash.success{background:rgba(46,230,168,.12);border:1px solid rgba(46,230,168,.3);color:var(--green)}
.flash.error{background:rgba(255,91,110,.12);border:1px solid rgba(255,91,110,.3);color:var(--red)}
input,select{width:100%;padding:10px 12px;border-radius:10px;border:1px solid var(--line);
background:rgba(0,0,0,.25);color:var(--text);font-size:13px;margin-bottom:12px}
label{font-size:11px;color:var(--muted);letter-spacing:1px;text-transform:uppercase}
.chart-row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:#b9c8e6}
.login-wrap{min-height:100vh;display:grid;place-items:center;padding:20px}
.login-card{width:100%;max-width:390px;padding:34px;border-radius:22px;
background:var(--panel);border:1px solid var(--line);backdrop-filter:blur(25px);
box-shadow:0 30px 90px rgba(0,0,0,.45)}
.login-card h1{font-size:23px;margin-bottom:6px}
@media(max-width:900px){.layout{flex-direction:column}
.sidebar{width:100%;height:auto;position:relative;padding:18px}
.nav{display:flex;overflow:auto;gap:6px}.nav a{white-space:nowrap}
.main{max-width:100%;padding:20px}.chart-row{grid-template-columns:1fr}}
"""

TEMPLATES = {
    "base.html": """
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XYVEN Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>""" + BASE_CSS + """</style></head><body>
<div class="layout">
  <aside class="sidebar">
    <div class="brand">XYVEN <span>PREMIUM</span></div>
    <div class="tag">REFER &amp; EARN CONTROL</div>
    <nav class="nav">
      <a href="/" class="{{ 'active' if active=='overview' }}">📊 Overview</a>
      <a href="/users" class="{{ 'active' if active=='users' }}">👥 Users</a>
      <a href="/referrals" class="{{ 'active' if active=='referrals' }}">🔗 Referrals</a>
      <a href="/withdrawals" class="{{ 'active' if active=='withdrawals' }}">💸 Withdrawals</a>
      <a href="/channels" class="{{ 'active' if active=='channels' }}">📢 Channels</a>
      <a href="/transactions" class="{{ 'active' if active=='transactions' }}">💰 Transactions</a>
      <a href="/settings" class="{{ 'active' if active=='settings' }}">⚙️ Settings</a>
      <a href="/logout">🚪 Logout</a>
    </nav>
  </aside>
  <main class="main">
    {% with msgs = get_flashed_messages(with_categories=true) %}
      {% for cat, msg in msgs %}<div class="flash {{ cat }}">{{ msg }}</div>{% endfor %}
    {% endwith %}
    {{ content|safe }}
  </main>
</div></body></html>
""",
    "login.html": """
<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>XYVEN Admin Login</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>""" + BASE_CSS + """</style></head><body>
<div class="login-wrap"><div class="login-card">
  <div class="brand">XYVEN <span>PREMIUM</span></div>
  <div class="tag">ADMIN ACCESS</div>
  <h1>Welcome back</h1>
  <p class="sub" style="margin-bottom:22px">Sign in to manage referrals, withdrawals and channels.</p>
  {% with msgs = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in msgs %}<div class="flash {{ cat }}">{{ msg }}</div>{% endfor %}
  {% endwith %}
  <form method="post">
    <input type="hidden" name="_csrf" value="{{ csrf_token() }}">
    <label>Username</label><input name="username" autocomplete="username" required>
    <label>Password</label><input name="password" type="password" autocomplete="current-password" required>
    <button class="btn blue" style="width:100%;justify-content:center;margin-top:6px">Sign in</button>
  </form>
</div></div></body></html>
""",
    "overview.html": """
{% extends "base.html" %}{% set active='overview' %}
{% block %}{% endblock %}
"""
}

# Jinja blocks need a proper parent. Rebuild templates without extends.
TEMPLATES["overview.html"] = """
<div class="topbar"><div><h1>Overview</h1><div class="sub">Live platform performance</div></div>
<a class="btn green" href="/withdrawals">Review withdrawals</a></div>
<div class="grid">
  <div class="card blue"><div class="label">Total Users</div><div class="value">{{ s.users }}</div><div class="hint">Registered accounts</div></div>
  <div class="card green"><div class="label">Successful Referrals</div><div class="value">{{ s.referrals }}</div><div class="hint">Rewarded referrals</div></div>
  <div class="card gold"><div class="label">Reward Paid</div><div class="value">₹{{ '%.2f'|format(s.reward_paid) }}</div><div class="hint">Referral bonuses</div></div>
  <div class="card red"><div class="label">Pending Withdrawals</div><div class="value">{{ s.pending_count }}</div><div class="hint">₹{{ '%.2f'|format(s.pending_wd) }} waiting</div></div>
  <div class="card blue"><div class="label">Approved Withdrawals</div><div class="value">₹{{ '%.2f'|format(s.approved_wd) }}</div><div class="hint">Awaiting payout</div></div>
  <div class="card green"><div class="label">Available User Balance</div><div class="value">₹{{ '%.2f'|format(s.available) }}</div><div class="hint">Across all users</div></div>
  <div class="card gold"><div class="label">Active Channels</div><div class="value">{{ s.channels }}</div><div class="hint">Force-join channels</div></div>
</div>
<div class="chart-row">
  <div class="panel"><h2>Referrals — last 7 days</h2><canvas id="refChart" height="190"></canvas></div>
  <div class="panel"><h2>Withdrawals — last 7 days</h2><canvas id="wdChart" height="190"></canvas></div>
</div>
<script>
const grid={color:'rgba(255,255,255,.06)'}, tick={color:'#8ea0c4'};
new Chart(document.getElementById('refChart'),{type:'line',data:{labels:{{ ref_labels|tojson }},datasets:[{data:{{ ref_values|tojson }},borderColor:'#2ee6a8',backgroundColor:'rgba(46,230,168,.14)',fill:true,tension:.4,pointRadius:3}]},options:{plugins:{legend:{display:false}},scales:{x:{ticks:tick,grid:grid},y:{ticks:tick,grid:grid,beginAtZero:true}}}});
new Chart(document.getElementById('wdChart'),{type:'bar',data:{labels:{{ wd_labels|tojson }},datasets:[{data:{{ wd_values|tojson }},backgroundColor:'rgba(79,140,255,.55)',borderRadius:6}]},options:{plugins:{legend:{display:false}},scales:{x:{ticks:tick,grid:grid},y:{ticks:tick,grid:grid,beginAtZero:true}}}});
</script>
"""

TEMPLATES["users.html"] = """
<div class="topbar"><div><h1>Users</h1><div class="sub">{{ users|length }} most recent accounts</div></div></div>
<div class="panel"><table><thead><tr><th>ID</th><th>Name</th><th>Username</th><th>Balance</th><th>Reserved</th><th>Earned</th><th>Refs</th><th>Joined</th></tr></thead><tbody>
{% for u in users %}<tr><td class="mono">{{ u.user_id }}</td><td>{{ u.first_name or '—' }}</td><td>@{{ u.username or '—' }}</td><td>₹{{ '%.2f'|format(u.balance) }}</td><td>₹{{ '%.2f'|format(u.reserved) }}</td><td>₹{{ '%.2f'|format(u.total_earned) }}</td><td>{{ u.refs }}</td><td class="mono">{{ u.created_at[:16] }}</td></tr>{% endfor %}
</tbody></table></div>
"""

TEMPLATES["referrals.html"] = """
<div class="topbar"><div><h1>Referrals</h1><div class="sub">Persistent referral records</div></div></div>
<div class="panel"><table><thead><tr><th>ID</th><th>Referrer</th><th>Referred User</th><th>Reward</th><th>Status</th><th>Created</th></tr></thead><tbody>
{% for r in referrals %}<tr><td class="mono">{{ r.id }}</td><td>{{ r.first_name or r.referrer_id }} <span class="mono">({{ r.referrer_id }})</span></td><td class="mono">{{ r.referred_id }}</td><td>₹{{ '%.2f'|format(r.reward) }}</td><td>{% if r.rewarded %}<span class="pill PAID">CREDITED</span>{% else %}<span class="pill PENDING">PENDING</span>{% endif %}</td><td class="mono">{{ r.created_at[:16] }}</td></tr>{% endfor %}
</tbody></table></div>
"""

TEMPLATES["withdrawals.html"] = """
<div class="topbar"><div><h1>Withdrawals</h1><div class="sub">Approve, reject and settle payout requests</div></div></div>
<div class="panel"><table><thead><tr><th>ID</th><th>User</th><th>Amount</th><th>Method / Details</th><th>Status</th><th>TX</th><th>Actions</th></tr></thead><tbody>
{% for w in withdrawals %}<tr><td class="mono">{{ w.id }}</td><td>{{ w.first_name or w.user_id }}<br><span class="mono">{{ w.user_id }}</span></td><td><b>₹{{ '%.2f'|format(w.amount) }}</b></td><td>{{ w.method }}<br><span class="mono">{{ w.details }}</span></td><td><span class="pill {{ w.status }}">{{ w.status }}</span></td><td class="mono">{{ w.tx_id }}</td><td>
{% if w.status=='PENDING' %}
<form method="post" action="/withdrawals/{{ w.id }}/approve" style="display:inline"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><button class="btn green">Approve</button></form>
<form method="post" action="/withdrawals/{{ w.id }}/reject" style="display:inline"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><button class="btn red">Reject</button></form>
{% elif w.status=='APPROVED' %}
<form method="post" action="/withdrawals/{{ w.id }}/paid" style="display:inline"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><button class="btn blue">Mark Paid</button></form>
<form method="post" action="/withdrawals/{{ w.id }}/reject" style="display:inline"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><button class="btn red">Reject</button></form>
{% else %}—{% endif %}
</td></tr>{% endfor %}
</tbody></table></div>
"""

TEMPLATES["channels.html"] = """
<div class="topbar"><div><h1>Promotional Channels</h1><div class="sub">Force-join channels and join-request approval</div></div></div>
<div class="panel" style="margin-bottom:18px"><h2>Add channel</h2>
<form method="post" action="/channels/add">
<input type="hidden" name="_csrf" value="{{ csrf_token() }}">
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
<div><label>Numeric Chat ID *</label><input name="chat_id" placeholder="-1001234567890" required></div>
<div><label>Username</label><input name="username" placeholder="examplechannel"></div>
<div><label>Title</label><input name="title" placeholder="Example Channel"></div>
<div><label>Invite Link</label><input name="invite_link" placeholder="https://t.me/examplechannel"></div>
</div>
<button class="btn green">Save channel</button>
<p class="sub">Private invite links do not reveal numeric IDs; enter the chat ID explicitly. The bot must be a channel administrator.</p>
</form></div>
<div class="panel"><table><thead><tr><th>ID</th><th>Title</th><th>Chat ID</th><th>Username</th><th>Status</th><th>Actions</th></tr></thead><tbody>
{% for c in channels %}<tr><td class="mono">{{ c.id }}</td><td>{{ c.title or '—' }}</td><td class="mono">{{ c.chat_id }}</td><td>@{{ c.username or '—' }}</td><td>{% if c.is_active %}<span class="pill PAID">ACTIVE</span>{% else %}<span class="pill REJECTED">DISABLED</span>{% endif %}</td><td>
<form method="post" action="/channels/{{ c.id }}/toggle" style="display:inline"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><button class="btn">Toggle</button></form>
<form method="post" action="/channels/{{ c.id }}/delete" style="display:inline"><input type="hidden" name="_csrf" value="{{ csrf_token() }}"><button class="btn red">Delete</button></form>
</td></tr>{% endfor %}
</tbody></table></div>
"""

TEMPLATES["transactions.html"] = """
<div class="topbar"><div><h1>Transactions</h1><div class="sub">Every balance movement is recorded</div></div></div>
<div class="panel"><table><thead><tr><th>ID</th><th>User</th><th>Type</th><th>Amount</th><th>Description</th><th>Reference</th><th>Time</th></tr></thead><tbody>
{% for t in transactions %}<tr><td class="mono">{{ t.id }}</td><td>{{ t.first_name or t.user_id }}<br><span class="mono">{{ t.user_id }}</span></td><td>{{ t.type }}</td><td style="color:{{ '#2ee6a8' if t.amount>=0 else '#ff5b6e' }}">{{ '+' if t.amount>=0 else '−' }}₹{{ '%.2f'|format(t.amount|abs) }}</td><td>{{ t.description or '—' }}</td><td class="mono">{{ t.reference or '—' }}</td><td class="mono">{{ t.created_at[:16] }}</td></tr>{% endfor %}
</tbody></table></div>
"""

TEMPLATES["settings.html"] = """
<div class="topbar"><div><h1>Bot Settings</h1><div class="sub">Changes apply to bot and dashboard immediately</div></div></div>
<div class="panel" style="max-width:760px"><h2>Platform configuration</h2>
<form method="post">
<input type="hidden" name="_csrf" value="{{ csrf_token() }}">
<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
<div><label>Bot Name</label><input name="bot_name" value="{{ data.bot_name }}"></div>
<div><label>Currency Symbol</label><input name="currency_symbol" value="{{ data.currency_symbol }}"></div>
<div><label>Referral Reward</label><input name="referral_reward" value="{{ data.referral_reward }}"></div>
<div><label>Minimum Withdrawal</label><input name="min_withdrawal" value="{{ data.min_withdrawal }}"></div>
<div><label>Payment Methods (comma separated)</label><input name="payment_methods" value="{{ data.payment_methods }}"></div>
<div><label>Support Username</label><input name="support_username" value="{{ data.support_username }}"></div>
<div><label>Referrals Enabled (1/0)</label><input name="referrals_enabled" value="{{ data.referrals_enabled }}"></div>
<div><label>Withdrawals Enabled (1/0)</label><input name="withdrawals_enabled" value="{{ data.withdrawals_enabled }}"></div>
</div>
<button class="btn green" style="margin-top:8px">Save settings</button>
</form></div>
"""

# Simple block-less template rendering: inject content into base shell
SHELL = TEMPLATES["base.html"]


def render_page(template_name, **ctx):
    content = app.jinja_env.from_string(TEMPLATES[template_name]).render(**ctx)
    shell = app.jinja_env.from_string(SHELL)
    return shell.render(content=content, **ctx)


# Override Flask render_template to use our shell for page templates
_original_render = render_template


def render_template(template_name, **ctx):
    if template_name == "login.html":
        return app.jinja_env.from_string(TEMPLATES["login.html"]).render(**ctx)
    return render_page(template_name, **ctx)


# ══════════════════════════════════════════════════════════════════
# BOT APPLICATION + MAIN
# ══════════════════════════════════════════════════════════════════


async def post_init(application: Application):
    global BOT_USERNAME, BOT
    me = await application.bot.get_me()
    BOT_USERNAME = me.username
    BOT = application.bot
    log.info("Bot @%s ready", BOT_USERNAME)


def build_application():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .updater(None)
        .post_init(post_init)
        .build()
    )
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("admin", cmd_admin))
    application.add_handler(ChatJoinRequestHandler(on_join_request))

    application.add_handler(CallbackQueryHandler(cb_verify_join, pattern="^verify_join$"))
    application.add_handler(CallbackQueryHandler(cb_main_menu, pattern="^main_menu$"))
    application.add_handler(CallbackQueryHandler(cb_account, pattern="^menu_account$"))
    application.add_handler(CallbackQueryHandler(cb_refer, pattern="^menu_refer$"))
    application.add_handler(CallbackQueryHandler(cb_balance, pattern="^menu_balance$"))
    application.add_handler(CallbackQueryHandler(cb_withdraw, pattern="^menu_withdraw$"))
    application.add_handler(CallbackQueryHandler(cb_stats, pattern="^menu_stats$"))
    application.add_handler(CallbackQueryHandler(cb_how, pattern="^menu_how$"))
    application.add_handler(CallbackQueryHandler(cb_support, pattern="^menu_support$"))
    application.add_handler(CallbackQueryHandler(wd_choose_method, pattern="^wd_method:"))
    application.add_handler(CallbackQueryHandler(cb_admin, pattern="^adm_"))
    application.add_handler(CallbackQueryHandler(cb_admin_wd, pattern="^adm_wd:"))
    application.add_handler(CallbackQueryHandler(cb_admin_ch, pattern="^adm_ch:"))

    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    return application


async def main_async():
    global LOOP
    LOOP = asyncio.get_running_loop()
    init_db()

    application = build_application()
    await application.initialize()
    await application.start()

    webhook_url = f"{WEBHOOK_URL}/webhook/{WEBHOOK_SECRET}"
    await application.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )
    log.info("Webhook set: %s", webhook_url)

    asgi_app = WsgiToAsgi(app)
    config = uvicorn.Config(
        asgi_app, host="0.0.0.0", port=PORT,
        log_level="info", lifespan="off",
    )
    server = uvicorn.Server(config)
    try:
        await server.serve()
    finally:
        log.info("Shutting down…")
        try:
            await application.bot.delete_webhook()
        except Exception:
            pass
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set")
    if not ADMIN_IDS:
        log.warning("ADMIN_IDS is empty — bot admin panel will be inaccessible")
    asyncio.run(main_async())
