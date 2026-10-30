"""
╔══════════════════════════════════════════════════════════╗
║   ᴄʏᴛᴜɴ ʀᴇғᴇʀ — All-in-One Bot                          ║
║   Run: python bot.py                                     ║
╚══════════════════════════════════════════════════════════╝
"""

import os, re, html, asyncio, sqlite3, threading, time
from datetime import datetime

import aiosqlite
from flask import Flask, jsonify, render_template_string
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton as B,
    ReplyKeyboardMarkup, KeyboardButton
)

load_dotenv()

BOT_TOKEN      = (os.getenv("BOT_TOKEN", "") or "").strip()
ADMIN_IDS      = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x]
SUPPORT_ID     = os.getenv("SUPPORT_ID", "@cytunn")
DB_PATH        = os.getenv("DB_PATH", "bot.db")
VALIDATE_EMOJI = int(os.getenv("VALIDATE_EMOJI", "1"))
SITE_NAME      = os.getenv("SITE_NAME", "ᴄʏᴛᴜɴ ʀᴇғᴇʀ sᴛᴀᴛs")

REFER_REWARD = 2.0
MIN_WITHDRAW = 10.0
BOT_NAME     = "ᴄʏᴛᴜɴ ʀᴇғᴇʀ"

DIV  = "✦ ━━━━━━━━━━━━━━━━━ ✦"
LINE = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

def esc(t): return html.escape(str(t or ""))

# ═══════════════════════════════════════════════════════════
#              PREMIUM EMOJI (25 IDs)
# ═══════════════════════════════════════════════════════════
PREMIUM_EMOJIS = [
    ("5357592447557848986", "✨"), # 1
    ("5258387666616994756", "👋"), # 2
    ("5391118489824015979", "🆔"), # 3
    ("5334665104677941170", "💰"), # 4
    ("5289862389552919154", "📊"), # 5
    ("5397730656400714154", "👥"), # 6
    ("5301275719681190738", "🎯"), # 7
    ("5301096984617166561", "🔒"), # 8
    ("5386521874089914548", "📢"), # 9
    ("5332423642850536254", "✅"), # 10
    ("5264892613630111886", "👤"), # 11
    ("5258113901106580375", "📝"), # 12
    ("5258212320282168974", "🔖"), # 13
    ("5258274739041883702", "🆔"), # 14
    ("5258457030338844822", "💳"), # 15
    ("5260373152688540294", "🏆"), # 16
    ("5258420785109830474", "🎁"), # 17
    ("5258178411515382761", "📅"), # 18
    ("5260691173541970181", "🎁"), # 19
    ("6014620343883273557", "💎"), # 20
    ("6015104451122042405", "👥"), # 21
    ("6104794084205925773", "📈"), # 22
    ("6104675564583392962", "🔗"), # 23
    ("6107015024679592166", "📤"), # 24
    ("6120548140211770562", "💬"), # 25
]

def _pe_html(eid, fb):
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'

def render(text):
    def repl(m):
        n = int(m.group(1))
        eid, fb = PREMIUM_EMOJIS[(n - 1) % len(PREMIUM_EMOJIS)]
        return _pe_html(eid, fb)
    return re.sub(r"\[PE:\s*(\d+)\]", repl, text)

# ═══════════════════════════════════════════════════════════
#                     DB LAYER
# ═══════════════════════════════════════════════════════════
def now(): return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

async def db_init():
    async with aiosqlite.connect(DB_PATH) as c:
        await c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            balance REAL DEFAULT 0, total_earned REAL DEFAULT 0,
            ref_count INTEGER DEFAULT 0, referred_by INTEGER,
            verified INTEGER DEFAULT 0, joined_at TEXT);
        CREATE TABLE IF NOT EXISTS channels(
            id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT UNIQUE,
            title TEXT, link TEXT, added_at TEXT);
        CREATE TABLE IF NOT EXISTS withdrawals(
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
            upi TEXT, amount REAL, status TEXT DEFAULT 'pending',
            created_at TEXT, processed_at TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        """)
        await c.commit()
    for k, v in [("refer_reward","2"),("min_withdraw","10"),("force_join","1")]:
        await set_setting(k, v, overwrite=False)
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT COUNT(*) FROM channels")
        if (await cur.fetchone())[0] == 0:
            await c.execute(
                "INSERT OR IGNORE INTO channels(chat_id,title,link,added_at) VALUES(?,?,?,?)",
                ("@whymeyarrr", "ᴡʜʏ ᴍᴇ ʏᴀʀʀʀ", "https://t.me/whymeyarrr", now()))
            await c.commit()

async def get_setting(k, d=None):
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT value FROM settings WHERE key=?", (k,))
        r = await cur.fetchone()
    return r[0] if r else d

async def get_setting_float(k, d=0.0):
    v = await get_setting(k)
    return float(v) if v is not None else d

async def set_setting(k, v, overwrite=True):
    async with aiosqlite.connect(DB_PATH) as c:
        if overwrite:
            await c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, str(v)))
        else:
            await c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, str(v)))
        await c.commit()

async def get_user(uid):
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        return await cur.fetchone()

async def create_user(uid, un, fn, ref=None):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute(
            "INSERT OR IGNORE INTO users(user_id,username,first_name,referred_by,joined_at) "
            "VALUES(?,?,?,?,?)", (uid, un, fn, ref, now()))
        await c.commit()

async def set_verified(uid):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("UPDATE users SET verified=1 WHERE user_id=?", (uid,))
        await c.commit()

async def update_balance(uid, amt):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (amt, uid))
        await c.commit()

async def credit_refer(ref_id, new_id):
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT referred_by FROM users WHERE user_id=?", (new_id,))
        row = await cur.fetchone()
        if not row or row["referred_by"] is None: return False
        cur = await c.execute("SELECT * FROM users WHERE user_id=?", (ref_id,))
        if not await cur.fetchone(): return False
        rw = await get_setting_float("refer_reward", 2.0)
        await c.execute(
            "UPDATE users SET balance=balance+?,total_earned=total_earned+?,ref_count=ref_count+1 "
            "WHERE user_id=?", (rw, rw, ref_id))
        await c.execute("UPDATE users SET referred_by=NULL WHERE user_id=?", (new_id,))
        await c.commit()
        return True

async def count_users():
    async with aiosqlite.connect(DB_PATH) as c:
        return (await (await c.execute("SELECT COUNT(*) FROM users")).fetchone())[0]

async def count_verified():
    async with aiosqlite.connect(DB_PATH) as c:
        return (await (await c.execute("SELECT COUNT(*) FROM users WHERE verified=1")).fetchone())[0]

async def all_verified_ids():
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT user_id FROM users WHERE verified=1")
        return [r[0] for r in await cur.fetchall()]

async def top_referrers(limit=10):
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM users ORDER BY ref_count DESC LIMIT ?", (limit,))
        return await cur.fetchall()

async def get_channels():
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM channels ORDER BY id ASC")
        return await cur.fetchall()

async def add_channel(cid, title, link):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("INSERT OR IGNORE INTO channels(chat_id,title,link,added_at) VALUES(?,?,?,?)",
                        (str(cid), title, link, now()))
        await c.commit()

async def del_channel(cid):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("DELETE FROM channels WHERE id=?", (cid,))
        await c.commit()

async def create_withdrawal(uid, upi, amt):
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute(
            "INSERT INTO withdrawals(user_id,upi,amount,status,created_at) VALUES(?,?,?,?,?)",
            (uid, upi, amt, "pending", now()))
        await c.commit()
        return cur.lastrowid

async def get_withdrawal(wid):
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM withdrawals WHERE id=?", (wid,))
        return await cur.fetchone()

async def set_withdrawal_status(wid, st):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("UPDATE withdrawals SET status=?, processed_at=? WHERE id=?",
                        (st, now(), wid))
        await c.commit()

async def pending_withdrawals():
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM withdrawals WHERE status='pending' ORDER BY id ASC")
        return await cur.fetchall()

async def pending_count():
    async with aiosqlite.connect(DB_PATH) as c:
        return (await (await c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")).fetchone())[0]

async def user_pending_wd(uid):
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM withdrawals WHERE user_id=? AND status='pending'", (uid,))
        return await cur.fetchall()

async def total_paid():
    async with aiosqlite.connect(DB_PATH) as c:
        return (await (await c.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE status='approved'")).fetchone())[0]

# ═══════════════════════════════════════════════════════════
#                     UI TEXTS & KEYBOARDS
# ═══════════════════════════════════════════════════════════

def main_reply_kb(is_admin_flag=False):
    """Yeh Reply Keyboard hai jisme Premium Emoji IDs lagenge."""
    kb = [
        [KeyboardButton(text="Profile", icon_custom_emoji_id="5264892613630111886"),
         KeyboardButton(text="Refer & Earn", icon_custom_emoji_id="5260691173541970181")],
        [KeyboardButton(text="Withdraw", icon_custom_emoji_id="5258457030338844822"),
         KeyboardButton(text="Help", icon_custom_emoji_id="6120548140211770562")],
        [KeyboardButton(text="Emoji ID", icon_custom_emoji_id="5357592447557848986")]
    ]
    if is_admin_flag:
        kb.append([KeyboardButton(text="Admin Panel", icon_custom_emoji_id="5301096984617166561")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def main_menu_text(u, link):
    return render(
        f"{DIV}\n     <b>[PE: 1] {BOT_NAME}</b>\n{DIV}\n\n"
        f"  [PE: 2] ʜᴇʏ <b>{esc(u['first_name'])}</b>\n"
        f"  [PE: 3] ɪᴅ › <code>{u['user_id']}</code>\n\n"
        f"{LINE}\n"
        f"  [PE: 4] ʙᴀʟᴀɴᴄᴇ      ›  <b>₹{u['balance']:.2f}</b>\n"
        f"  [PE: 5] ᴛᴏᴛᴀʟ ᴇᴀʀɴᴇᴅ ›  ₹{u['total_earned']:.2f}\n"
        f"  [PE: 6] ʀᴇғᴇʀs       ›  {u['ref_count']}\n"
        f"{LINE}\n\n  [PE: 7] <b>sᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ</b>\n{DIV}"
    )

def join_text(chans):
    rows = "".join([f"  › [PE: {((i-1)%25)+1}] <a href='{c['link']}'>{esc(c['title'])}</a>\n"
                    for i, c in enumerate(chans, 1)])
    return render(
        f"{DIV}\n     <b>[PE: 8] ᴊᴏɪɴ ʀᴇǫᴜɪʀᴇᴅ</b>\n{DIV}\n\n"
        f"  [PE: 9] ʙᴏᴛ ᴜsᴇ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ɴɪᴄʜᴇ ᴅɪʏᴇ\n"
        f"  ᴄʜᴀɴɴᴇʟs ᴊᴏɪɴ ᴋᴀʀᴇ\n\n{LINE}\n{rows}{LINE}\n\n"
        f"  [PE: 10] ᴊᴏɪɴ ᴋᴇ ʙᴀᴀᴅ <b>ᴠᴇʀɪғʏ</b> ᴘʀᴇss ᴋᴀʀᴇ\n{DIV}"
    )

def join_kb(chans):
    rows = [[B(text=f"📢 ᴊᴏɪɴ ›  {c['title']}", url=c["link"])] for c in chans]
    rows.append([B(text="✅ ᴠᴇʀɪғʏ", callback_data="check_join")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def profile_text(u):
    return render(
        f"{DIV}\n       <b>[PE: 11] ᴘʀᴏғɪʟᴇ</b>\n{DIV}\n\n"
        f"  [PE: 12] ɴᴀᴍᴇ      ›  {esc(u['first_name'])}\n"
        f"  [PE: 13] ᴜsᴇʀɴᴀᴍᴇ  ›  @{esc(u['username'] or 'ɴᴏɴᴇ')}\n"
        f"  [PE: 14] ɪᴅ        ›  <code>{u['user_id']}</code>\n\n{LINE}\n"
        f"  [PE: 15] ʙᴀʟᴀɴᴄᴇ      ›  <b>₹{u['balance']:.2f}</b>\n"
        f"  [PE: 16] ᴛᴏᴛᴀʟ ᴇᴀʀɴᴇᴅ ›  ₹{u['total_earned']:.2f}\n"
        f"  [PE: 17] ʀᴇғᴇʀs       ›  {u['ref_count']}\n"
        f"  [PE: 18] ᴊᴏɪɴᴇᴅ       ›  {u['joined_at']}\n{DIV}"
    )

def refer_text(u, link, rw):
    return render(
        f"{DIV}\n     <b>[PE: 19] ʀᴇғᴇʀ & ᴇᴀʀɴ</b>\n{DIV}\n\n"
        f"  [PE: 20] ᴘᴇʀ ʀᴇғᴇʀ  ›  <b>₹{rw:.0f}</b>\n"
        f"  [PE: 21] ʏᴏᴜʀ ʀᴇғs ›  <b>{u['ref_count']}</b>\n"
        f"  [PE: 22] ᴇᴀʀɴɪɴɢs  ›  ₹{u['total_earned']:.2f}\n\n{LINE}\n"
        f"  [PE: 23] ʏᴏᴜʀ ɪɴᴠɪᴛᴇ ʟɪɴᴋ\n  <code>{link}</code>\n{LINE}\n\n"
        f"  [PE: 24] ʟɪɴᴋ sʜᴀʀᴇ ᴋᴀʀᴇ › ғʀɪᴇɴᴅ ᴊᴏɪɴ ᴋᴀʀᴇ\n"
        f"  › ᴠᴇʀɪғʏ ᴋᴀʀᴇ › ₹{rw:.0f} ᴍɪʟᴇɢᴀ\n{DIV}"
    )

def withdraw_text(u, mw, pend):
    body = "\n".join([f"  ┄ #{w['id']}  ₹{w['amount']:.2f}  ›  {w['status']}" for w in pend]) or "  ┄ ᴋᴏɪ ᴘᴇɴᴅɪɴɢ ɴᴀʜɪ"
    return render(
        f"{DIV}\n      <b>[PE: 15] ᴡɪᴛʜᴅʀᴀᴡ</b>\n{DIV}\n\n"
        f"  [PE: 15] ʙᴀʟᴀɴᴄᴇ ›  <b>₹{u['balance']:.2f}</b>\n"
        f"  [PE: 14] ᴍɪɴ    ›  ₹{mw:.0f}\n\n{LINE}\n  ᴘᴇɴᴅɪɴɢ\n{body}\n{LINE}\n\n"
        f"  [PE: 4] ʀᴇǫᴜᴇsᴛ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ʙᴜᴛᴛᴏɴ ᴘʀᴇss ᴋᴀʀᴇ\n{DIV}"
    )

def withdraw_kb():
    # Inline buttons yaha colorful indicator ke sath
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="🔴 ʀᴇǫᴜᴇsᴛ ᴡɪᴛʜᴅʀᴀᴡ", callback_data="wd:new")],
        [B(text="🔵 ʙᴀᴄᴋ", callback_data="m:home")],
    ])

def help_text(sup):
    return render(
        f"{DIV}\n       <b>[PE: 25] ʜᴇʟᴘ</b>\n{DIV}\n\n"
        f"  [PE: 1] ʀᴇғᴇʀ  ›  ₹2 ᴘᴇʀ ʀᴇғᴇʀ\n"
        f"  [PE: 2] ᴡɪᴛʜᴅʀᴀᴡ ›  ᴍɪɴ ₹10 · ᴜᴘɪ\n"
        f"  [PE: 3] ᴘᴀʏᴍᴇɴᴛ ›  24ʜ ᴡɪᴛʜɪɴ\n\n{LINE}\n"
        f"  [PE: 4] sᴜᴘᴘᴏʀᴛ ›  {sup}\n{DIV}"
    )

def emoji_prompt():
    return render(
        f"{DIV}\n   <b>[PE: 1] ᴇᴍᴏᴊɪ ɪᴅ ᴇxᴛʀᴀᴄᴛᴏʀ</b>\n{DIV}\n\n"
        f"  [PE: 2] ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ ᴡᴀʟᴀ ᴍᴇssᴀɢᴇ ʙʜᴇᴊᴇ\n"
        f"  [PE: 3] ʙᴏᴛ ᴜsᴋᴀ ɪᴅ ᴅᴇ ᴅᴇɢᴀ\n\n{LINE}\n{DIV}"
    )

def emoji_success(eid, valid, fb):
    st = "ᴠᴀʟɪᴅ ✓" if valid else "ᴜɴᴠᴇʀɪғɪᴇᴅ"
    return render(
        f"{DIV}\n    <b>[PE: 1] ᴇᴍᴏᴊɪ ɪᴅ ᴇxᴛʀᴀᴄᴛᴇᴅ</b>\n{DIV}\n\n"
        f"  [PE: 2] ᴇᴍᴏᴊɪ  ›  {fb}\n  [PE: 3] sᴛᴀᴛᴜs ›  {st}\n\n{LINE}\n"
        f"  [PE: 4] ɪᴅ\n  <code>{eid}</code>\n{LINE}\n\n"
        f"  [PE: 5] ᴜsᴇ › <code>&lt;tg-emoji emoji-id=\"{eid}\"&gt;✨&lt;/tg-emoji&gt;</code>\n{DIV}"
    )

def admin_text(s, sup):
    return render(
        f"{DIV}\n      <b>[PE: 1] ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b>\n{DIV}\n\n"
        f"  [PE: 2] ᴀᴅᴍɪɴ {sup}\n\n{LINE}\n"
        f"  [PE: 3] ᴜsᴇʀs      ›  {s['total_users']}\n"
        f"  [PE: 4] ᴠᴇʀɪғɪᴇᴅ   ›  {s['verified_users']}\n"
        f"  [PE: 5] ᴘᴇɴᴅɪɴɢ   ›  {s['pending_wd']}\n"
        f"  [PE: 6] ᴄʜᴀɴɴᴇʟs  ›  {s['channels']}\n"
        f"  [PE: 7] ᴘᴀɪᴅ      ›  ₹{s['total_paid']:.2f}\n{LINE}\n\n"
        f"  [PE: 8] ᴀᴄᴛɪᴏɴ sᴇʟᴇᴄᴛ ᴋᴀʀᴇ\n{DIV}"
    )

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="📊 sᴛᴀᴛs",       callback_data="a:stats"),
         B(text="👥 ᴜsᴇʀs",       callback_data="a:users")],
        [B(text="💳 ᴡɪᴛʜᴅʀᴀᴡᴀʟs", callback_data="a:wd"),
         B(text="📢 ʙʀᴏᴀᴅᴄᴀsᴛ",  callback_data="a:broadcast")],
        [B(text="🔗 ᴄʜᴀɴɴᴇʟs",    callback_data="a:channels"),
         B(text="⚙️ sᴇᴛᴛɪɴɢs",    callback_data="a:settings")],
        [B(text="💰 ɢɪᴠᴇ ʙᴀʟᴀɴᴄᴇ", callback_data="a:give"),
         B(text="🔍 ғɪɴᴅ ᴜsᴇʀ",   callback_data="a:find")],
        [B(text="❌ ᴄʟᴏsᴇ",       callback_data="a:close")],
    ])

def channels_kb(chans):
    rows = [[B(text=f"❌  {c['title']}", callback_data=f"a:delch:{c['id']}")] for c in chans]
    rows.append([B(text="➕ ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ", callback_data="a:addch")])
    rows.append([B(text="◀ ʙᴀᴄᴋ", callback_data="a:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def channels_text(chans):
    body = "\n".join([f"  {i}. {esc(c['title'])}\n     └ <code>{c['chat_id']}</code>"
                      for i, c in enumerate(chans, 1)]) or "  ᴋᴏɪ ᴄʜᴀɴɴᴇʟ ɴᴀʜɪ"
    return render(f"{DIV}\n   <b>[PE: 9] ғᴏʀᴄᴇ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟs</b>\n{DIV}\n\n"
                  f"{body}\n\n{LINE}\n  [PE: 6] ᴛᴀᴘ ᴛᴏ ʀᴇᴍᴏᴠᴇ\n{DIV}")

def settings_text(fj, rw, mn):
    return render(f"{DIV}\n     <b>[PE: 1] sᴇᴛᴛɪɴɢs</b>\n{DIV}\n\n"
                  f"  [PE: 8] ғᴏʀᴄᴇ ᴊᴏɪɴ ›  {'ᴏɴ ✓' if fj else 'ᴏғғ ✕'}\n"
                  f"  [PE: 20] ʀᴇғᴇʀ ʀᴡ ›  ₹{rw:.0f}\n"
                  f"  [PE: 15] ᴍɪɴ ᴡᴅ    ›  ₹{mn:.0f}\n\n"
                  f"{LINE}\n  [PE: 7] ᴄʜᴀɴɢᴇ ᴋᴀʀᴇ\n{DIV}")

def settings_kb(fj):
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text=("🔴 ᴛᴜʀɴ ᴏғғ ғᴊ" if fj else "🟢 ᴛᴜʀɴ ᴏɴ ғᴊ"), callback_data="a:toggle_fj")],
        [B(text="🟢 sᴇᴛ ʀᴇғᴇʀ ʀᴇᴡᴀʀᴅ", callback_data="a:set_reward")],
        [B(text="🔴 sᴇᴛ ᴍɪɴ ᴡɪᴛʜᴅʀᴀᴡ", callback_data="a:set_min")],
        [B(text="◀ ʙᴀᴄᴋ", callback_data="a:home")],
    ])

# ═══════════════════════════════════════════════════════════
#                     BOT SETUP
# ═══════════════════════════════════════════════════════════
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp  = Dispatcher(storage=MemoryStorage())

class WD(StatesGroup): upi = State()
class AdminS(StatesGroup):
    add_channel = State()
    broadcast   = State()
    give_bal    = State()
    find_user   = State()
    set_reward  = State()
    set_min     = State()

def is_admin(uid): return uid in ADMIN_IDS

async def not_joined_first(uid):
    if (await get_setting("force_join", "1")) != "1": return None
    for ch in await get_channels():
        try:
            m = await bot.get_chat_member(chat_id=ch["chat_id"], user_id=uid)
            if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                return ch
        except Exception: continue
    return None

async def gate(event, uid):
    if await not_joined_first(uid):
        chans = await get_channels()
        txt, kb = join_text(chans), join_kb(chans)
        if isinstance(event, CallbackQuery):
            await event.message.answer(txt, reply_markup=kb, disable_web_page_preview=True)
            await event.answer()
        else:
            await event.answer(txt, reply_markup=kb, disable_web_page_preview=True)
        return False
    return True

def ref_link(uid, un): return f"https://t.me/{un}?start=ref_{uid}"

# ═══════════════════════════════════════════════════════════
#                     USER HANDLERS
# ═══════════════════════════════════════════════════════════
@dp.message(CommandStart())
async def start(m: Message):
    a = m.text.split(maxsplit=1)
    ref = None
    if len(a) > 1 and a[1].startswith("ref_"):
        try:
            r = int(a[1][4:])
            if r != m.from_user.id: ref = r
        except: pass
    await create_user(m.from_user.id, m.from_user.username, m.from_user.first_name, ref)

    if await not_joined_first(m.from_user.id):
        chans = await get_channels()
        return await m.answer(join_text(chans), reply_markup=join_kb(chans),
                              disable_web_page_preview=True)

    u = await get_user(m.from_user.id)
    me = await bot.get_me()
    # Ab yaha ReplyKeyboard jayega jisme premium emojis hain
    await m.answer(main_menu_text(u, ref_link(m.from_user.id, me.username)),
                   reply_markup=main_reply_kb(is_admin(m.from_user.id)))

@dp.message(Command("myid"))
async def myid(m: Message):
    await m.answer(render(
        f"{DIV}\n  <b>[PE: 3] ʏᴏᴜʀ ɪᴅ</b>\n{DIV}\n\n"
        f"  <code>{m.from_user.id}</code>\n\n"
        f"  ᴀᴅᴍɪɴ ʜᴀɪ? › {'✓ ʏᴇs' if is_admin(m.from_user.id) else '✕ ɴᴏ'}\n{DIV}"
    ))

@dp.callback_query(F.data == "check_join")
async def cb_verify(cb: CallbackQuery):
    if await not_joined_first(cb.from_user.id):
        return await cb.answer("❌ ᴘᴇʜʟᴇ sᴀᴀʀᴇ ᴄʜᴀɴɴᴇʟs ᴊᴏɪɴ ᴋᴀʀᴇ!", show_alert=True)
    u = await get_user(cb.from_user.id)
    if not u:
        await create_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
        u = await get_user(cb.from_user.id)
    if not u["verified"]:
        await set_verified(cb.from_user.id)
        if u["referred_by"]:
            if await credit_refer(u["referred_by"], cb.from_user.id):
                rw = await get_setting_float("refer_reward", 2.0)
                try:
                    await bot.send_message(u["referred_by"], render(
                        f"{DIV}\n  [PE: 17] ʀᴇғᴇʀ ʙᴏɴᴜs\n  [PE: 4] +₹{rw:.0f} ᴄʀᴇᴅɪᴛᴇᴅ ✓\n{DIV}"))
                except: pass
    u = await get_user(cb.from_user.id)
    me = await bot.get_me()
    # Delete old join message and send new menu
    await cb.message.delete()
    await cb.message.answer(main_menu_text(u, ref_link(cb.from_user.id, me.username)),
                            reply_markup=main_reply_kb(is_admin(cb.from_user.id)))
    await cb.answer("✓ ᴠᴇʀɪғɪᴇᴅ")

@dp.callback_query(F.data == "m:home")
async def cb_home(cb: CallbackQuery):
    if not await gate(cb, cb.from_user.id): return
    u = await get_user(cb.from_user.id)
    me = await bot.get_me()
    await cb.message.edit_text(main_menu_text(u, ref_link(cb.from_user.id, me.username)))
    await cb.answer()

# ═══════════════ TEXT HANDLERS (For Reply Keyboard) ═══════════════

@dp.message(F.text == "Profile")
async def m_profile(m: Message):
    if not await gate(m, m.from_user.id): return
    u = await get_user(m.from_user.id)
    await m.answer(profile_text(u),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="◀ ʙᴀᴄᴋ", callback_data="m:home")]]))

@dp.message(F.text == "Refer & Earn")
async def m_refer(m: Message):
    if not await gate(m, m.from_user.id): return
    u = await get_user(m.from_user.id)
    me = await bot.get_me()
    rw = await get_setting_float("refer_reward", 2.0)
    link = ref_link(m.from_user.id, me.username)
    await m.answer(refer_text(u, link, rw), disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [B(text="🟢 sʜᴀʀᴇ ʟɪɴᴋ", url=f"https://t.me/share/url?url={link}&text=ᴊᴏɪɴ ᴋᴀʀᴏ ₹{rw:.0f} ᴋᴀᴍᴀᴏ")],
            [B(text="◀ ʙᴀᴄᴋ", callback_data="m:home")],
        ]))

@dp.message(F.text == "Help")
async def m_help(m: Message):
    if not await gate(m, m.from_user.id): return
    await m.answer(help_text(SUPPORT_ID),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [B(text="🔵 sᴜᴘᴘᴏʀᴛ", url=f"https://t.me/{SUPPORT_ID.lstrip('@')}")],
            [B(text="◀ ʙᴀᴄᴋ", callback_data="m:home")],
        ]))

@dp.message(F.text == "Emoji ID")
async def m_emoji(m: Message):
    if not await gate(m, m.from_user.id): return
    await m.answer(emoji_prompt(),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="◀ ʙᴀᴄᴋ", callback_data="m:home")]]))

@dp.message(F.text == "Withdraw")
async def m_withdraw(m: Message):
    if not await gate(m, m.from_user.id): return
    u = await get_user(m.from_user.id)
    mw = await get_setting_float("min_withdraw", MIN_WITHDRAW)
    pend = await user_pending_wd(m.from_user.id)
    await m.answer(withdraw_text(u, mw, pend), reply_markup=withdraw_kb())

@dp.message(F.text == "Admin Panel")
async def m_admin_panel(m: Message):
    if not is_admin(m.from_user.id):
        return await m.answer("❌ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ")
    await m.answer(admin_text(await stats_summary(), SUPPORT_ID), reply_markup=admin_kb())

@dp.message(F.text)
async def emoji_extract(m: Message):
    ents = [e for e in (m.entities or []) if e.type == "custom_emoji"]
    if not ents: return
    eid = ents[0].custom_emoji_id
    valid, fb = False, "✨"
    if VALIDATE_EMOJI:
        try:
            st = await bot.get_custom_emoji_stickers([eid])
            valid = bool(st)
            if st and st[0].emoji: fb = st[0].emoji
        except: pass
    await m.answer(emoji_success(eid, valid, fb),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="◀ ʙᴀᴄᴋ", callback_data="m:home")]]))

# ═══════════════════════════════════════════════════════════
#                     WITHDRAW FLOW
# ═══════════════════════════════════════════════════════════
@dp.callback_query(F.data == "wd:new")
async def cb_wd_new(cb: CallbackQuery, state: FSMContext):
    if not await gate(cb, cb.from_user.id): return
    u = await get_user(cb.from_user.id)
    mw = await get_setting_float("min_withdraw", MIN_WITHDRAW)
    if u["balance"] < mw:
        return await cb.answer(f"❌ ᴍɪɴ ₹{mw:.0f} ʙᴀʟᴀɴᴄᴇ ᴄʜᴀʜɪʏᴇ", show_alert=True)
    if await user_pending_wd(cb.from_user.id):
        return await cb.answer("⏳ ᴇᴋ ʀᴇǫᴜᴇsᴛ ᴘᴇɴᴅɪɴɢ ʜᴀɪ", show_alert=True)
    await state.set_state(WD.upi)
    await cb.message.edit_text(render(
        f"{DIV}\n  <b>[PE: 15] ᴜᴘɪ ᴇɴᴛᴇʀ</b>\n{DIV}\n\n"
        f"  [PE: 2] ᴀᴘɴᴀ ᴜᴘɪ ɪᴅ sᴇɴᴅ ᴋᴀʀᴇ\n  [PE: 3] ᴇx › <code>name@upi</code>\n\n"
        f"{LINE}\n  [PE: 4] ʀᴇǫᴜᴇsᴛ ʙʜᴇᴊɴᴇ ᴘᴀʀ ᴀᴍᴏᴜɴᴛ ᴅᴇᴅᴜᴄᴛ\n{DIV}"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="🔴 ᴄᴀɴᴄᴇʟ", callback_data="m:home")]]))
    await cb.answer()

@dp.message(WD.upi)
async def wd_upi(m: Message, state: FSMContext):
    upi = m.text.strip()
    if not re.match(r"^[\w.\-]{2,}@[\w]{2,}$", upi):
        return await m.answer(render(f"{DIV}\n  [PE: 1] ɪɴᴠᴀʟɪᴅ ᴜᴘɪ\n  [PE: 2] ғᴏʀᴍᴀᴛ › name@upi\n{DIV}"))
    u = await get_user(m.from_user.id)
    mw = await get_setting_float("min_withdraw", MIN_WITHDRAW)
    amt = u["balance"]
    if amt < mw:
        await state.clear()
        return await m.answer(f"❌ ʙᴀʟᴀɴᴄᴇ ɪɴsᴜғғɪᴄɪᴇɴᴛ (ᴍɪɴ ₹{mw:.0f})")
    await update_balance(m.from_user.id, -amt)
    wid = await create_withdrawal(m.from_user.id, upi, amt)
    await state.clear()
    await m.answer(render(
        f"{DIV}\n   <b>[PE: 10] ʀᴇǫᴜᴇsᴛ sᴜʙᴍɪᴛᴛᴇᴅ</b>\n{DIV}\n\n"
        f"  [PE: 3] ʀᴇǫ  ›  #{wid}\n  [PE: 15] ᴀᴍᴛ  ›  ₹{amt:.2f}\n"
        f"  [PE: 14] ᴜᴘɪ  ›  <code>{esc(upi)}</code>\n\n{LINE}\n"
        f"  [PE: 7] ᴀᴅᴍɪɴ 24ʜ ᴍᴇ ᴘʀᴏᴄᴇss ᴋᴀʀᴇɢᴀ\n{DIV}"))
    un = f"@{m.from_user.username}" if m.from_user.username else "—"
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        B(text="🟢 ᴀᴄᴄᴇᴘᴛ",  callback_data=f"wd:ok:{wid}"),
        B(text="🔴 ʀᴇᴊᴇᴄᴛ", callback_data=f"wd:no:{wid}")]])
    for a in ADMIN_IDS:
        try:
            await bot.send_message(a, render(
                f"{DIV}\n   <b>[PE: 15] ɴᴇᴡ ᴡɪᴛʜᴅʀᴀᴡ</b>\n{DIV}\n\n"
                f"  [PE: 3] ʀᴇǫ ›  #{wid}\n"
                f"  [PE: 11] ᴜsᴇʀ ›  {esc(m.from_user.first_name)}\n"
                f"  [PE: 13] ᴜɴ  ›  {un}\n"
                f"  [PE: 14] ɪᴅ  ›  <code>{m.from_user.id}</code>\n"
                f"  [PE: 15] ᴀᴍᴛ ›  ₹{amt:.2f}\n"
                f"  [PE: 16] ᴜᴘɪ ›  <code>{esc(upi)}</code>\n{DIV}"), reply_markup=kb)
        except: pass

@dp.callback_query(F.data.startswith("wd:ok:"))
async def wd_ok(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    wid = int(cb.data.split(":")[2])
    w = await get_withdrawal(wid)
    if not w or w["status"] != "pending":
        return await cb.answer("⚠️ ᴀʟʀᴇᴀᴅʏ ᴘʀᴏᴄᴇssᴇᴅ", show_alert=True)
    await set_withdrawal_status(wid, "approved")
    await cb.message.edit_text(cb.message.html_text + "\n\n✅ <b>ᴀᴘᴘʀᴏᴠᴇᴅ</b>")
    try:
        await bot.send_message(w["user_id"], render(
            f"{DIV}\n  <b>[PE: 10] ᴀᴘᴘʀᴏᴠᴇᴅ ✓</b>\n  [PE: 15] #{wid} › ₹{w['amount']:.2f}\n"
            f"  [PE: 4] ᴘᴀʏᴍᴇɴᴛ 24ʜ ᴡɪᴛʜɪɴ\n{DIV}"))
    except: pass
    await cb.answer("✓")

@dp.callback_query(F.data.startswith("wd:no:"))
async def wd_no(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    wid = int(cb.data.split(":")[2])
    w = await get_withdrawal(wid)
    if not w or w["status"] != "pending":
        return await cb.answer("⚠️ ᴀʟʀᴇᴀᴅʏ ᴘʀᴏᴄᴇssᴇᴅ", show_alert=True)
    await set_withdrawal_status(wid, "rejected")
    await update_balance(w["user_id"], w["amount"])
    await cb.message.edit_text(cb.message.html_text + "\n\n❌ <b>ʀᴇᴊᴇᴄᴛᴇᴅ</b>")
    try:
        await bot.send_message(w["user_id"], render(
            f"{DIV}\n  <b>[PE: 5] ʀᴇᴊᴇᴄᴛᴇᴅ</b>\n  [PE: 15] #{wid} › ₹{w['amount']:.2f}\n"
            f"  [PE: 4] ʀᴇғᴜɴᴅᴇᴅ ✓\n{DIV}"))
    except: pass
    await cb.answer("✕")

# ═══════════════════════════════════════════════════════════
#                     ADMIN HANDLERS (Inline UI)
# ═══════════════════════════════════════════════════════════
async def stats_summary():
    return {
        "total_users": await count_users(),
        "verified_users": await count_verified(),
        "pending_wd": await pending_count(),
        "total_paid": await total_paid(),
        "channels": len(await get_channels()),
    }

@dp.message(Command("admin"))
async def admin_cmd(m: Message):
    if not is_admin(m.from_user.id):
        return await m.answer(render(
            f"{DIV}\n  [PE: 8] ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ\n\n"
            f"  [PE: 3] ʏᴏᴜʀ ɪᴅ › <code>{m.from_user.id}</code>\n"
            f"  [PE: 7] /myid sᴇ ᴀᴘɴᴀ ɪᴅ ᴠᴇʀɪғʏ ᴋᴀʀᴇ\n{DIV}"))
    await m.answer(admin_text(await stats_summary(), SUPPORT_ID), reply_markup=admin_kb())

@dp.callback_query(F.data == "a:home")
async def a_home(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await cb.message.edit_text(admin_text(await stats_summary(), SUPPORT_ID), reply_markup=admin_kb())
    await cb.answer()

@dp.callback_query(F.data == "a:close")
async def a_close(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await cb.message.delete()
    await cb.answer()

@dp.callback_query(F.data == "a:stats")
async def a_stats(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    s = await stats_summary()
    await cb.message.edit_text(render(
        f"{DIV}\n   <b>[PE: 5] sᴛᴀᴛs</b>\n{DIV}\n\n"
        f"  [PE: 6] ᴜsᴇʀs    ›  <b>{s['total_users']}</b>\n"
        f"  [PE: 10] ᴠᴇʀɪғɪᴇᴅ ›  {s['verified_users']}\n"
        f"  [PE: 15] ᴘᴇɴᴅɪɴɢ ›  {s['pending_wd']}\n"
        f"  [PE: 4] ᴘᴀɪᴅ    ›  ₹{s['total_paid']:.2f}\n"
        f"  [PE: 9] ᴄʜᴀɴɴᴇʟs ›  {s['channels']}\n{DIV}"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="🔵 ʙᴀᴄᴋ", callback_data="a:home")]]))
    await cb.answer()

@dp.callback_query(F.data == "a:users")
async def a_users(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    top = await top_referrers(10)
    body = "\n".join([f"  {i}. {esc(t['first_name'])} › ₹{t['balance']:.0f} › {t['ref_count']} ʀᴇғs"
                      for i, t in enumerate(top, 1)]) or "  —"
    await cb.message.edit_text(render(f"{DIV}\n  <b>[PE: 6] ᴛᴏᴘ ᴜsᴇʀs</b>\n{DIV}\n\n{body}\n{DIV}"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="🔵 ʙᴀᴄᴋ", callback_data="a:home")]]))
    await cb.answer()

@dp.callback_query(F.data == "a:wd")
async def a_wd(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    pend = await pending_withdrawals()
    if not pend:
        await cb.message.edit_text(render(f"{DIV}\n  [PE: 5] ᴋᴏɪ ᴘᴇɴᴅɪɴɢ ɴᴀʜɪ\n{DIV}"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="🔵 ʙᴀᴄᴋ", callback_data="a:home")]]))
        return await cb.answer()
    for w in pend:
        u = await get_user(w["user_id"])
        await cb.message.answer(render(
            f"{DIV}\n  <b>[PE: 15] ᴡɪᴛʜᴅʀᴀᴡ #{w['id']}</b>\n{DIV}\n\n"
            f"  [PE: 11] ᴜsᴇʀ ›  {esc(u['first_name'] if u else '?')}\n"
            f"  [PE: 14] ɪᴅ  ›  <code>{w['user_id']}</code>\n"
            f"  [PE: 15] ᴀᴍᴛ ›  ₹{w['amount']:.2f}\n"
            f"  [PE: 16] ᴜᴘɪ ›  <code>{esc(w['upi'])}</code>\n{DIV}"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                B(text="🟢 ᴀᴄᴄᴇᴘᴛ",  callback_data=f"wd:ok:{w['id']}"),
                B(text="🔴 ʀᴇᴊᴇᴄᴛ", callback_data=f"wd:no:{w['id']}")]]))
    await cb.answer()

@dp.callback_query(F.data == "a:channels")
async def a_channels(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    chans = await get_channels()
    await cb.message.edit_text(channels_text(chans), reply_markup=channels_kb(chans))
    await cb.answer()

@dp.callback_query(F.data == "a:addch")
async def a_addch(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(AdminS.add_channel)
    await cb.message.edit_text(render(
        f"{DIV}\n  <b>[PE: 9] ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ</b>\n{DIV}\n\n"
        f"  [PE: 2] @ᴜsᴇʀɴᴀᴍᴇ / -100xxx / ʟɪɴᴋ sᴇɴᴅ\n"
        f"  [PE: 8] ʙᴏᴛ ᴄʜᴀɴɴᴇʟ ᴀᴅᴍɪɴ ʜᴏɴᴀ ᴄʜᴀʜɪʏᴇ\n\n"
        f"{LINE}\n  [PE: 3] ᴇx › <code>@mychannel</code>\n{DIV}"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="🔴 ᴄᴀɴᴄᴇʟ", callback_data="a:channels")]]))
    await cb.answer()

@dp.message(AdminS.add_channel)
async def a_addch_in(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    raw = m.text.strip().replace("https://t.me/", "@").replace("t.me/", "@")
    if raw.startswith("https://"): raw = "@" + raw.split("/")[-1].lstrip("@")
    try:
        chat = await bot.get_chat(raw)
        me = await bot.get_me()
        mem = await bot.get_chat_member(chat.id, me.id)
        if mem.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            return await m.answer("❌ ʙᴏᴛ ᴄʜᴀɴɴᴇʟ ᴀᴅᴍɪɴ ʙᴀɴᴀᴏ")
        link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else None)
        if not link: return await m.answer("❌ ɪɴᴠɪᴛᴇ ʟɪɴᴋ ɴᴀʜɪ ᴍɪʟᴀ")
        await add_channel(chat.id, chat.title, link)
        await state.clear()
        chans = await get_channels()
        await m.answer(f"✅ <b>{esc(chat.title)}</b> ᴀᴅᴅᴇᴅ\n\n" + channels_text(chans),
                       reply_markup=channels_kb(chans))
    except Exception as e:
        await m.answer(f"❌ ᴇʀʀᴏʀ › <code>{esc(str(e))}</code>")

@dp.callback_query(F.data.startswith("a:delch:"))
async def a_delch(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await del_channel(int(cb.data.split(":")[2]))
    chans = await get_channels()
    await cb.message.edit_text(channels_text(chans), reply_markup=channels_kb(chans))
    await cb.answer("✓")

@dp.callback_query(F.data == "a:settings")
async def a_settings(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    fj = (await get_setting("force_join", "1")) == "1"
    rw = await get_setting_float("refer_reward", 2.0)
    mn = await get_setting_float("min_withdraw", 10.0)
    await cb.message.edit_text(settings_text(fj, rw, mn), reply_markup=settings_kb(fj))
    await cb.answer()

@dp.callback_query(F.data == "a:toggle_fj")
async def a_toggle_fj(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    cur = await get_setting("force_join", "1")
    await set_setting("force_join", "0" if cur == "1" else "1")
    fj = (await get_setting("force_join", "1")) == "1"
    rw = await get_setting_float("refer_reward", 2.0)
    mn = await get_setting_float("min_withdraw", 10.0)
    await cb.message.edit_text(settings_text(fj, rw, mn), reply_markup=settings_kb(fj))
    await cb.answer("✓")

@dp.callback_query(F.data == "a:set_reward")
async def a_set_rw(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(AdminS.set_reward)
    await cb.message.edit_text(render(f"{DIV}\n  [PE: 20] ɴᴇᴡ ʀᴇғᴇʀ ʀᴇᴡᴀʀᴅ (₹) sᴇɴᴅ\n{DIV}"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="🔴 ᴄᴀɴᴄᴇʟ", callback_data="a:settings")]]))
    await cb.answer()

@dp.message(AdminS.set_reward)
async def a_set_rw_in(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    try:
        v = float(m.text.strip())
        await set_setting("refer_reward", v)
        await state.clear()
        await m.answer(f"✅ ʀᴇғᴇʀ ʀᴇᴡᴀʀᴅ › ₹{v:.0f}")
    except: await m.answer("❌ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ")

@dp.callback_query(F.data == "a:set_min")
async def a_set_min(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(AdminS.set_min)
    await cb.message.edit_text(render(f"{DIV}\n  [PE: 15] ɴᴇᴡ ᴍɪɴ ᴡɪᴛʜᴅʀᴀᴡ (₹) sᴇɴᴅ\n{DIV}"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="🔴 ᴄᴀɴᴄᴇʟ", callback_data="a:settings")]]))
    await cb.answer()

@dp.message(AdminS.set_min)
async def a_set_min_in(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    try:
        v = float(m.text.strip())
        await set_setting("min_withdraw", v)
        await state.clear()
        await m.answer(f"✅ ᴍɪɴ ᴡɪᴛʜᴅʀᴀᴡ › ₹{v:.0f}")
    except: await m.answer("❌ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ")

@dp.callback_query(F.data == "a:broadcast")
async def a_bc(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(AdminS.broadcast)
    await cb.message.edit_text(render(f"{DIV}\n  [PE: 24] ʙʀᴏᴀᴅᴄᴀsᴛ ᴍsɢ sᴇɴᴅ\n{DIV}"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="🔴 ᴄᴀɴᴄᴇʟ", callback_data="a:home")]]))
    await cb.answer()

@dp.message(AdminS.broadcast)
async def a_bc_send(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    await state.clear()
    ids = await all_verified_ids()
    ok = fail = 0
    st = await m.answer(f"⏳ sᴇɴᴅɪɴɢ ᴛᴏ {len(ids)}...")
    for uid in ids:
        try:
            await m.copy_to(uid); ok += 1
            await asyncio.sleep(0.05)
        except: fail += 1
    await st.edit_text(f"✅ ᴅᴏɴᴇ\n✅ sᴇɴᴛ: {ok}\n❌ ғᴀɪʟ: {fail}")

@dp.callback_query(F.data == "a:give")
async def a_give(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(AdminS.give_bal)
    await cb.message.edit_text(render(
        f"{DIV}\n  [PE: 4] ғᴏʀᴍᴀᴛ › <code>USER_ID AMOUNT</code>\n"
        f"  [PE: 5] ᴇx › <code>123456789 50</code>\n{DIV}"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="🔴 ᴄᴀɴᴄᴇʟ", callback_data="a:home")]]))
    await cb.answer()

@dp.message(AdminS.give_bal)
async def a_give_in(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    try:
        uid_s, amt_s = m.text.split()
        uid, amt = int(uid_s), float(amt_s)
        if not await get_user(uid):
            return await m.answer("❌ ᴜsᴇʀ ɴᴀʜɪ ᴍɪʟᴀ")
        await update_balance(uid, amt)
        await state.clear()
        await m.answer(f"✅ ₹{amt:.2f} ɢɪᴠᴇɴ ᴛᴏ <code>{uid}</code>")
        try:
            await bot.send_message(uid, render(
                f"{DIV}\n  [PE: 17] ᴀᴅᴍɪɴ ʙᴏɴᴜs\n  [PE: 4] +₹{amt:.2f} ✓\n{DIV}"))
        except: pass
    except: await m.answer("❌ ғᴏʀᴍᴀᴛ › <code>USER_ID AMOUNT</code>")

@dp.callback_query(F.data == "a:find")
async def a_find(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(AdminS.find_user)
    await cb.message.edit_text(render(f"{DIV}\n  [PE: 3] ᴜsᴇʀ ɪᴅ sᴇɴᴅ\n{DIV}"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="🔴 ᴄᴀɴᴄᴇʟ", callback_data="a:home")]]))
    await cb.answer()

@dp.message(AdminS.find_user)
async def a_find_in(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    try: uid = int(m.text.strip())
    except: return await m.answer("❌ ɪɴᴠᴀʟɪᴅ ɪᴅ")
    u = await get_user(uid)
    await state.clear()
    if not u: return await m.answer("❌ ᴜsᴇʀ ɴᴀʜɪ ᴍɪʟᴀ")
    await m.answer(profile_text(u))

# ═══════════════════════════════════════════════════════════
#                     FLASK WEBSITE
# ═══════════════════════════════════════════════════════════
app = Flask(__name__)

WEB_TPL = """
<!DOCTYPE html><html><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ site }}</title><meta http-equiv="refresh" content="30">
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,'Segoe UI',sans-serif}
body{background:#08080c;color:#e8e8f0;min-height:100vh;padding:32px 16px;
background-image:radial-gradient(circle at 20% 0%,rgba(120,80,255,.18),transparent 55%),
radial-gradient(circle at 90% 100%,rgba(0,200,255,.12),transparent 55%)}
.wrap{max-width:1080px;margin:0 auto}
h1{text-align:center;font-size:clamp(22px,4vw,34px);letter-spacing:4px;
background:linear-gradient(90deg,#b08cff,#6ee7ff,#b08cff);
-webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:6px}
.sub{text-align:center;color:#6a6a85;letter-spacing:3px;font-size:12px;margin-bottom:36px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-bottom:36px}
.card{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);
border-radius:18px;padding:24px 18px;text-align:center;backdrop-filter:blur(8px);transition:.3s}
.card:hover{border-color:rgba(150,110,255,.5);transform:translateY(-3px)}
.card .label{color:#7a7a95;font-size:11px;letter-spacing:2px;margin-bottom:12px}
.card .value{font-size:32px;font-weight:700;
background:linear-gradient(90deg,#c4a6ff,#6ee7ff);
-webkit-background-clip:text;background-clip:text;color:transparent}
.panel{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.07);
border-radius:20px;padding:24px;margin-bottom:24px}
.panel h2{font-size:13px;letter-spacing:3px;color:#8a8aa5;margin-bottom:20px;font-weight:500}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:#6a6a85;font-size:10px;letter-spacing:2px;padding:10px 8px;
border-bottom:1px solid rgba(255,255,255,.06);font-weight:500}
td{padding:12px 8px;border-bottom:1px solid rgba(255,255,255,.04);color:#c8c8dc}
.foot{text-align:center;color:#4a4a60;font-size:11px;letter-spacing:2px;margin-top:28px}
</style></head><body><div class="wrap">
<h1>{{ site }}</h1>
<div class="sub">ʟɪᴠᴇ ᴅᴀsʜʙᴏᴀʀᴅ · ᴀᴜᴛᴏ ʀᴇғʀᴇsʜ 30s</div>
<div class="grid">
<div class="card"><div class="label">ᴛᴏᴛᴀʟ ᴜsᴇʀs</div><div class="value">{{ s.total_users }}</div></div>
<div class="card"><div class="label">ᴠᴇʀɪғɪᴇᴅ</div><div class="value">{{ s.verified_users }}</div></div>
<div class="card"><div class="label">ᴘᴇɴᴅɪɴɢ ᴡᴅ</div><div class="value">{{ s.pending_wd }}</div></div>
<div class="card"><div class="label">ᴛᴏᴛᴀʟ ᴘᴀɪᴅ</div><div class="value">₹{{ "%.0f"|format(s.total_paid) }}</div></div>
<div class="card"><div class="label">ᴄʜᴀɴɴᴇʟs</div><div class="value">{{ s.channels }}</div></div>
</div>
<div class="panel"><h2>ʀᴇᴄᴇɴᴛ ᴜsᴇʀs</h2>
<table><tr><th>NAME</th><th>USERNAME</th><th>BALANCE</th><th>REFS</th><th>JOINED</th></tr>
{% for u in recent %}
<tr><td>{{ u[0] or '—' }}</td><td>{{ '@' + u[1] if u[1] else '—' }}</td>
<td>₹{{ "%.2f"|format(u[2]) }}</td><td>{{ u[3] }}</td><td>{{ u[4] or '—' }}</td></tr>
{% endfor %}</table></div>
<div class="foot">✦ ━━━━━━━━ ✦</div>
</div></body></html>
"""

def web_q(sql, args=()):
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor(); cur.execute(sql, args)
        r = cur.fetchall(); conn.close(); return r
    except sqlite3.OperationalError:
        return []

def q1(sql, args=()):
    r = web_q(sql, args)
    return r[0][0] if r else 0

@app.route("/")
def index():
    s = {
        "total_users":    q1("SELECT COUNT(*) FROM users"),
        "verified_users": q1("SELECT COUNT(*) FROM users WHERE verified=1"),
        "pending_wd":     q1("SELECT COUNT(*) FROM withdrawals WHERE status='pending'"),
        "total_paid":     q1("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE status='approved'"),
        "channels":       q1("SELECT COUNT(*) FROM channels"),
    }
    recent = web_q("SELECT first_name,username,balance,ref_count,joined_at FROM users ORDER BY rowid DESC LIMIT 10")
    return render_template_string(WEB_TPL, site=SITE_NAME, s=s, recent=recent)

@app.route("/api/stats")
def api():
    return jsonify({
        "total_users":    q1("SELECT COUNT(*) FROM users"),
        "verified_users": q1("SELECT COUNT(*) FROM users WHERE verified=1"),
        "pending_wd":     q1("SELECT COUNT(*) FROM withdrawals WHERE status='pending'"),
    })

@app.route("/healthz")
def healthz(): return "ok", 200

# ═══════════════════════════════════════════════════════════
#                     STARTUP
# ═══════════════════════════════════════════════════════════
async def _poll():
    print(f"🤖 {BOT_NAME} started...")
    print(f"👤 ADMIN_IDS = {ADMIN_IDS}")
    await dp.start_polling(bot, handle_signals=False)

def _bot_thread():
    asyncio.run(_poll())

if __name__ == "__main__":
    if not BOT_TOKEN or " " in BOT_TOKEN:
        raise SystemExit("❌ BOT_TOKEN missing or contains spaces. Fix env.")

    asyncio.run(db_init())
    print("✓ DB ready")

    threading.Thread(target=_bot_thread, daemon=True).start()
    time.sleep(2)

    port = int(os.getenv("PORT", "5000"))
    print(f"🌐 Web on :{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
