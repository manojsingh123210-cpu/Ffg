import aiosqlite
from datetime import datetime, timedelta
from config import DB_PATH

def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

# ───────────────────────── INIT ─────────────────────────
async def init():
    async with aiosqlite.connect(DB_PATH) as c:
        await c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            user_id      INTEGER PRIMARY KEY,
            username     TEXT,
            first_name   TEXT,
            balance      REAL DEFAULT 0,
            total_earned REAL DEFAULT 0,
            ref_count    INTEGER DEFAULT 0,
            referred_by  INTEGER,
            verified     INTEGER DEFAULT 0,
            joined_at    TEXT
        );
        CREATE TABLE IF NOT EXISTS channels(
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id  TEXT UNIQUE,
            title    TEXT,
            link     TEXT,
            added_at TEXT
        );
        CREATE TABLE IF NOT EXISTS withdrawals(
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER,
            upi          TEXT,
            amount       REAL,
            status       TEXT DEFAULT 'pending',
            created_at   TEXT,
            processed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings(
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        await c.commit()

    # default settings
    await set_setting_default("refer_reward", "2")
    await set_setting_default("min_withdraw", "10")
    await set_setting_default("force_join",   "1")

    # default force-join channel
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT COUNT(*) FROM channels")
        (cnt,) = await cur.fetchone()
        if cnt == 0:
            await c.execute(
                "INSERT OR IGNORE INTO channels(chat_id,title,link,added_at) VALUES(?,?,?,?)",
                ("@whymeyarrr", "ᴡʜʏ ᴍᴇ ʏᴀʀʀʀ", "https://t.me/whymeyarrr", now()),
            )
            await c.commit()

# ───────────────────────── SETTINGS ─────────────────────────
async def set_setting_default(key, value):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, value))
        await c.commit()

async def get_setting(key, default=None):
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
    return row[0] if row else default

async def get_setting_float(key, default=0.0):
    v = await get_setting(key)
    return float(v) if v is not None else default

async def set_setting(key, value):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
        await c.commit()

# ───────────────────────── USERS ─────────────────────────
async def get_user(uid):
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM users WHERE user_id=?", (uid,))
        return await cur.fetchone()

async def create_user(uid, username, first_name, referred_by=None):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute(
            "INSERT OR IGNORE INTO users(user_id,username,first_name,referred_by,joined_at) "
            "VALUES(?,?,?,?,?)",
            (uid, username, first_name, referred_by, now()),
        )
        await c.commit()

async def set_verified(uid):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("UPDATE users SET verified=1 WHERE user_id=?", (uid,))
        await c.commit()

async def update_balance(uid, amount):
    """amount can be negative"""
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
        await c.commit()

async def credit_refer(referrer_id, new_user_id):
    """₹2 refer reward — sirf ek baar"""
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT referred_by FROM users WHERE user_id=?", (new_user_id,))
        row = await cur.fetchone()
        if not row or row["referred_by"] is None:
            return False

        cur = await c.execute("SELECT * FROM users WHERE user_id=?", (referrer_id,))
        ref = await cur.fetchone()
        if not ref:
            return False

        reward = await get_setting_float("refer_reward", 2.0)
        await c.execute(
            "UPDATE users SET balance=balance+?, total_earned=total_earned+?, ref_count=ref_count+1 "
            "WHERE user_id=?",
            (reward, reward, referrer_id),
        )
        await c.execute("UPDATE users SET referred_by=NULL WHERE user_id=?", (new_user_id,))
        await c.commit()
        return True

async def count_users():
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT COUNT(*) FROM users")
        return (await cur.fetchone())[0]

async def count_verified():
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT COUNT(*) FROM users WHERE verified=1")
        return (await cur.fetchone())[0]

async def all_user_ids():
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT user_id FROM users WHERE verified=1")
        return [r[0] for r in await cur.fetchall()]

async def top_referrers(limit=10):
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(
            "SELECT * FROM users ORDER BY ref_count DESC LIMIT ?", (limit,)
        )
        return await cur.fetchall()

async def find_user_by_id(uid):
    return await get_user(uid)

# ───────────────────────── CHANNELS ─────────────────────────
async def get_channels():
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM channels ORDER BY id ASC")
        return await cur.fetchall()

async def add_channel(chat_id, title, link):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute(
            "INSERT OR IGNORE INTO channels(chat_id,title,link,added_at) VALUES(?,?,?,?)",
            (str(chat_id), title, link, now()),
        )
        await c.commit()

async def del_channel(cid):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute("DELETE FROM channels WHERE id=?", (cid,))
        await c.commit()

# ───────────────────────── WITHDRAWALS ─────────────────────────
async def create_withdrawal(uid, upi, amount):
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute(
            "INSERT INTO withdrawals(user_id,upi,amount,status,created_at) VALUES(?,?,?,?,?)",
            (uid, upi, amount, "pending", now()),
        )
        await c.commit()
        return cur.lastrowid

async def get_withdrawal(wid):
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute("SELECT * FROM withdrawals WHERE id=?", (wid,))
        return await cur.fetchone()

async def set_withdrawal_status(wid, status):
    async with aiosqlite.connect(DB_PATH) as c:
        await c.execute(
            "UPDATE withdrawals SET status=?, processed_at=? WHERE id=?",
            (status, now(), wid),
        )
        await c.commit()

async def pending_withdrawals():
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(
            "SELECT * FROM withdrawals WHERE status='pending' ORDER BY id ASC"
        )
        return await cur.fetchall()

async def pending_count():
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'")
        return (await cur.fetchone())[0]

async def user_pending_withdrawals(uid):
    async with aiosqlite.connect(DB_PATH) as c:
        c.row_factory = aiosqlite.Row
        cur = await c.execute(
            "SELECT * FROM withdrawals WHERE user_id=? AND status='pending'", (uid,)
        )
        return await cur.fetchall()

async def total_paid():
    async with aiosqlite.connect(DB_PATH) as c:
        cur = await c.execute(
            "SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE status='approved'"
        )
        return (await cur.fetchone())[0]

# ───────────────────────── WEB STATS ─────────────────────────
async def stats_summary():
    return {
        "total_users":     await count_users(),
        "verified_users":  await count_verified(),
        "pending_wd":      await pending_count(),
        "total_paid":      await total_paid(),
        "channels":        len(await get_channels()),
    }
