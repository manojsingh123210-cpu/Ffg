import html

# ───────── Decoration ─────────
DIV  = "✦ ━━━━━━━━━━━━━━━━━ ✦"
LINE = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"

def esc(t):
    return html.escape(str(t or ""))

# ───────── WELCOME / MAIN MENU ─────────
def main_menu_text(u, ref_link):
    return (
        f"{DIV}\n"
        f"     <b>[PE: 1] ᴘʀᴇᴍɪᴜᴍ ᴍᴜʟᴛɪ-ᴛᴏᴏʟ ʙᴏᴛ</b>\n"
        f"{DIV}\n\n"
        f"  [PE: 2] ʜᴇʏ <b>{esc(u['first_name'])}</b>\n"
        f"  [PE: 3] ɪᴅ › <code>{u['user_id']}</code>\n\n"
        f"{LINE}\n"
        f"  [PE: 4] ʙᴀʟᴀɴᴄᴇ      ›  <b>₹{u['balance']:.2f}</b>\n"
        f"  [PE: 5] ᴛᴏᴛᴀʟ ᴇᴀʀɴᴇᴅ ›  ₹{u['total_earned']:.2f}\n"
        f"  [PE: 6] ʀᴇғᴇʀs       ›  {u['ref_count']}\n"
        f"{LINE}\n\n"
        f"  [PE: 7] <b>sᴇʟᴇᴄᴛ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ</b>\n"
        f"{DIV}"
    )

def main_menu_kb():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as B
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="◈  ᴘʀᴏғɪʟᴇ",         callback_data="m:profile"),
         B(text="⟡  ʀᴇғᴇʀ & ᴇᴀʀɴ",    callback_data="m:refer")],
        [B(text="◇  ᴡɪᴛʜᴅʀᴀᴡ",        callback_data="m:withdraw"),
         B(text="✦  ʜᴇʟᴘ",            callback_data="m:help")],
        [B(text="⟢  ᴀᴅᴠᴀɴᴄᴇᴅ ᴛᴏᴏʟs", callback_data="m:tools")],
    ])
    # 🔵 profile · 🟢 refer · 🔴 withdraw · ✦ help · ⟢ tools
    # Note: Telegram buttons premium emoji support nahi karte,
    #       isliye yahan sleek unicode symbols use kiye gaye hain.

# ───────── FORCE JOIN ─────────
def join_text(channels, not_joined_ids=None):
    rows = ""
    for i, ch in enumerate(channels, 1):
        mark = "✓" if (not_joined_ids and ch["chat_id"] in not_joined_ids) else "›"
        rows += f"  {mark} [PE: 1{i}] <a href='{ch['link']}'>{esc(ch['title'])}</a>\n"
    return (
        f"{DIV}\n"
        f"     <b>[PE: 8] ᴊᴏɪɴ ʀᴇǫᴜɪʀᴇᴅ</b>\n"
        f"{DIV}\n\n"
        f"  [PE: 9] ʙᴏᴛ ᴜsᴇ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ\n"
        f"  ɴɪᴄʜᴇ ᴅɪʏᴇ ɢᴀʏᴇ ᴄʜᴀɴɴᴇʟs ᴊᴏɪɴ ᴋᴀʀᴇ\n\n"
        f"{LINE}\n{rows}{LINE}\n\n"
        f"  [PE: 10] ᴊᴏɪɴ ᴋᴇ ʙᴀᴀᴅ <b>ᴠᴇʀɪғʏ</b> ᴘʀᴇss ᴋᴀʀᴇ\n"
        f"{DIV}"
    )

def join_kb(channels):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as B
    rows = [[B(text=f"⟢  ᴊᴏɪɴ ›  {ch['title']}", url=ch["link"])] for ch in channels]
    rows.append([B(text="✓  ᴠᴇʀɪғʏ", callback_data="check_join")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ───────── PROFILE ─────────
def profile_text(u):
    return (
        f"{DIV}\n"
        f"       <b>[PE: 11] ᴘʀᴏғɪʟᴇ</b>\n"
        f"{DIV}\n\n"
        f"  [PE: 12] ɴᴀᴍᴇ      ›  {esc(u['first_name'])}\n"
        f"  [PE: 13] ᴜsᴇʀɴᴀᴍᴇ  ›  @{esc(u['username'] or 'ɴᴏɴᴇ')}\n"
        f"  [PE: 14] ɪᴅ        ›  <code>{u['user_id']}</code>\n\n"
        f"{LINE}\n"
        f"  [PE: 15] ʙᴀʟᴀɴᴄᴇ      ›  <b>₹{u['balance']:.2f}</b>\n"
        f"  [PE: 16] ᴛᴏᴛᴀʟ ᴇᴀʀɴᴇᴅ ›  ₹{u['total_earned']:.2f}\n"
        f"  [PE: 17] ʀᴇғᴇʀs       ›  {u['ref_count']}\n"
        f"  [PE: 18] ᴊᴏɪɴᴇᴅ       ›  {u['joined_at']}\n"
        f"{DIV}"
    )

# ───────── REFER & EARN ─────────
def refer_text(u, link, reward):
    return (
        f"{DIV}\n"
        f"     <b>[PE: 19] ʀᴇғᴇʀ & ᴇᴀʀɴ</b>\n"
        f"{DIV}\n\n"
        f"  [PE: 20] ᴘᴇʀ ʀᴇғᴇʀ ʀᴇᴡᴀʀᴅ  ›  <b>₹{reward:.0f}</b>\n"
        f"  [PE: 21] ʏᴏᴜʀ ʀᴇғᴇʀs       ›  <b>{u['ref_count']}</b>\n"
        f"  [PE: 22] ʀᴇғ ᴇᴀʀɴɪɴɢs     ›  ₹{u['total_earned']:.2f}\n\n"
        f"{LINE}\n"
        f"  [PE: 23] ʏᴏᴜʀ ɪɴᴠɪᴛᴇ ʟɪɴᴋ\n"
        f"  <code>{link}</code>\n"
        f"{LINE}\n\n"
        f"  [PE: 24] ʟɪɴᴋ sʜᴀʀᴇ ᴋᴀʀᴇ › ғʀɪᴇɴᴅ ᴊᴏɪɴ ᴋᴀʀᴇ\n"
        f"  › ᴠᴇʀɪғʏ ᴋᴀʀᴇ › ᴀᴀᴘᴋᴏ ₹{reward:.0f} ᴍɪʟᴇɢᴀ\n"
        f"{DIV}"
    )

# ───────── WITHDRAW ─────────
def withdraw_text(u, min_wd, pending_list):
    pend = "\n".join(
        [f"  ┄ #{w['id']}  ₹{w['amount']:.2f}  ›  {w['status']}" for w in pending_list]
    ) or "  ┄ ᴋᴏɪ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛ ɴᴀʜɪ"
    return (
        f"{DIV}\n"
        f"      <b>[PE: 25] ᴡɪᴛʜᴅʀᴀᴡ</b>\n"
        f"{DIV}\n\n"
        f"  [PE: 26] ᴀᴠᴀɪʟᴀʙʟᴇ ʙᴀʟᴀɴᴄᴇ ›  <b>₹{u['balance']:.2f}</b>\n"
        f"  [PE: 27] ᴍɪɴɪᴍᴜᴍ ᴡɪᴛʜᴅʀᴀᴡ  ›  ₹{min_wd:.0f}\n\n"
        f"{LINE}\n  ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs\n{pend}\n{LINE}\n\n"
        f"  [PE: 28] ᴡɪᴛʜᴅʀᴀᴡ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ɴɪᴄʜᴇ ʙᴜᴛᴛᴏɴ ᴘʀᴇss ᴋᴀʀᴇ\n"
        f"{DIV}"
    )

def withdraw_kb():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as B
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="◇  ʀᴇǫᴜᴇsᴛ ᴡɪᴛʜᴅʀᴀᴡ", callback_data="wd:new")],
        [B(text="‹  ʙᴀᴄᴋ", callback_data="m:home")],
    ])

# ───────── HELP ─────────
def help_text(support):
    return (
        f"{DIV}\n"
        f"       <b>[PE: 29] ʜᴇʟᴘ</b>\n"
        f"{DIV}\n\n"
        f"  [PE: 30] ʀᴇғᴇʀ  ›  ₹2 ᴘᴇʀ sᴜᴄᴄᴇssғᴜʟ ʀᴇғᴇʀ\n"
        f"  [PE: 31] ᴡɪᴛʜᴅʀᴀᴡ ›  ᴍɪɴ ₹10 · ᴜᴘɪ ᴏɴʟʏ\n"
        f"  [PE: 32] ᴘᴀʏᴍᴇɴᴛ  ›  24 ʜᴏᴜʀs ᴡɪᴛʜɪɴ\n\n"
        f"{LINE}\n"
        f"  [PE: 33] sᴜᴘᴘᴏʀᴛ ›  {support}\n"
        f"{DIV}"
    )

# ───────── ADVANCED TOOLS ─────────
def tools_text():
    return (
        f"{DIV}\n"
        f"   <b>[PE: 34] ᴀᴅᴠᴀɴᴄᴇᴅ ᴛᴏᴏʟs</b>\n"
        f"{DIV}\n\n"
        f"  [PE: 35] ᴇᴍᴏᴊɪ ɪᴅ ᴇxᴛʀᴀᴄᴛᴏʀ\n"
        f"  [PE: 36] ғᴏɴᴛ ɢᴇɴᴇʀᴀᴛᴏʀ\n"
        f"  [PE: 37] ɪᴅ ʟᴏᴏᴋᴜᴘ\n\n"
        f"{LINE}\n"
        f"  [PE: 38] sᴇʟᴇᴄᴛ ᴀ ᴛᴏᴏʟ ʙᴇʟᴏᴡ\n"
        f"{DIV}"
    )

def tools_kb():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as B
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="⟢  ᴇᴍᴏᴊɪ ɪᴅ ᴇxᴛʀᴀᴄᴛ", callback_data="tool:emoji")],
        [B(text="⟢  ғᴏɴᴛ ɢᴇɴᴇʀᴀᴛᴏʀ", callback_data="tool:font")],
        [B(text="‹  ʙᴀᴄᴋ", callback_data="m:home")],
    ])

def tool_prompt(tool):
    if tool == "emoji":
        return (
            f"{DIV}\n   <b>[PE: 39] ᴇᴍᴏᴊɪ ɪᴅ ᴇxᴛʀᴀᴄᴛᴏʀ</b>\n{DIV}\n\n"
            f"  [PE: 40] ᴋᴏɪ ʙʜɪ ᴘʀᴇᴍɪᴜᴍ ᴇᴍᴏᴊɪ ᴡᴀʟᴀ\n"
            f"  ᴍᴇssᴀɢᴇ ʙʜᴇᴊᴇ › ʙᴏᴛ ᴜsᴋᴀ ɪᴅ ᴅᴇ ᴅᴇɢᴀ\n\n"
            f"{LINE}\n  [PE: 41] ᴇxᴀᴍᴘʟᴇ  ›  ᴋᴏɪ sᴀ ᴇᴍᴏᴊɪ sᴇɴᴅ ᴋᴀʀᴇ\n{DIV}"
        )
    return f"{DIV}\n  [PE: 42] ᴊᴀʟᴅ ʜɪ ᴀᴀ ʀᴀʜᴀ ʜᴀɪ\n{DIV}"

# ───────── EMOJI SUCCESS ─────────
def emoji_success(emoji_id, valid, fallback):
    status = "ᴠᴀʟɪᴅ ✓" if valid else "ᴜɴᴠᴇʀɪғɪᴇᴅ"
    return (
        f"{DIV}\n"
        f"    <b>[PE: 43] ᴇᴍᴏᴊɪ ɪᴅ ᴇxᴛʀᴀᴄᴛᴇᴅ</b>\n"
        f"{DIV}\n\n"
        f"  [PE: 44] ᴇᴍᴏᴊɪ    ›  {fallback}\n"
        f"  [PE: 45] sᴛᴀᴛᴜs   ›  {status}\n\n"
        f"{LINE}\n"
        f"  [PE: 46] ᴇᴍᴏᴊɪ ɪᴅ\n"
        f"  <code>{emoji_id}</code>\n"
        f"{LINE}\n\n"
        f"  [PE: 47] ᴜsᴇ  ›  &lt;tg-emoji emoji-id=\"{emoji_id}\"&gt;✨&lt;/tg-emoji&gt;\n"
        f"{DIV}"
    )

# ───────── ADMIN PANEL ─────────
def admin_text(stats, support):
    return (
        f"{DIV}\n"
        f"      <b>[PE: 48] ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b>\n"
        f"{DIV}\n\n"
        f"  [PE: 49] ʜᴇʏ ᴀᴅᴍɪɴ {support}\n\n"
        f"{LINE}\n"
        f"  [PE: 50] ᴜsᴇʀs        ›  {stats['total_users']}\n"
        f"  [PE: 51] ᴠᴇʀɪғɪᴇᴅ     ›  {stats['verified_users']}\n"
        f"  [PE: 52] ᴘᴇɴᴅɪɴɢ ᴡᴅ   ›  {stats['pending_wd']}\n"
        f"  [PE: 53] ᴄʜᴀɴɴᴇʟs    ›  {stats['channels']}\n"
        f"  [PE: 54] ᴛᴏᴛᴀʟ ᴘᴀɪᴅ   ›  ₹{stats['total_paid']:.2f}\n"
        f"{LINE}\n\n"
        f"  [PE: 55] sᴇʟᴇᴄᴛ ᴀɴ ᴀᴄᴛɪᴏɴ\n"
        f"{DIV}"
    )

def admin_kb():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as B
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text="◈  sᴛᴀᴛs",       callback_data="a:stats"),
         B(text="◈  ᴜsᴇʀs",       callback_data="a:users")],
        [B(text="◇  ᴡɪᴛʜᴅʀᴀᴡᴀʟs", callback_data="a:wd"),
         B(text="✦  ʙʀᴏᴀᴅᴄᴀsᴛ",  callback_data="a:broadcast")],
        [B(text="⟢  ᴄʜᴀɴɴᴇʟs",    callback_data="a:channels"),
         B(text="⟢  sᴇᴛᴛɪɴɢs",    callback_data="a:settings")],
        [B(text="⟡  ɢɪᴠᴇ ʙᴀʟᴀɴᴄᴇ", callback_data="a:give"),
         B(text="⟡  ғɪɴᴅ ᴜsᴇʀ",   callback_data="a:find")],
        [B(text="✕  ᴄʟᴏsᴇ",       callback_data="a:close")],
    ])

def channels_kb(channels):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as B
    rows = [[B(text=f"✕  {ch['title']}", callback_data=f"a:delch:{ch['id']}")] for ch in channels]
    rows.append([B(text="+  ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ", callback_data="a:addch")])
    rows.append([B(text="‹  ʙᴀᴄᴋ", callback_data="a:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def channels_text(channels):
    body = "\n".join(
        [f"  {i}. [PE: 6{i}] {esc(c['title'])}\n     └ <code>{c['chat_id']}</code>"
         for i, c in enumerate(channels, 1)]
    ) or "  ᴋᴏɪ ᴄʜᴀɴɴᴇʟ ɴᴀʜɪ ʜᴀɪ"
    return (
        f"{DIV}\n   <b>[PE: 56] ғᴏʀᴄᴇ ᴊᴏɪɴ ᴄʜᴀɴɴᴇʟs</b>\n{DIV}\n\n"
        f"{body}\n\n{LINE}\n  ᴛᴀᴘ ᴛᴏ ʀᴇᴍᴏᴠᴇ ᴏʀ ᴀᴅᴅ\n{DIV}"
    )

def settings_text(fj, reward, minwd):
    return (
        f"{DIV}\n     <b>[PE: 57] sᴇᴛᴛɪɴɢs</b>\n{DIV}\n\n"
        f"  [PE: 58] ғᴏʀᴄᴇ ᴊᴏɪɴ   ›  {'ᴏɴ ✓' if fj else 'ᴏғғ ✕'}\n"
        f"  [PE: 59] ʀᴇғᴇʀ ʀᴇᴡᴀʀᴅ ›  ₹{reward:.0f}\n"
        f"  [PE: 60] ᴍɪɴ ᴡɪᴛʜᴅʀᴀᴡ  ›  ₹{minwd:.0f}\n\n"
        f"{LINE}\n  [PE: 61] sᴇʟᴇᴄᴛ ᴛᴏ ᴄʜᴀɴɢᴇ\n{DIV}"
    )

def settings_kb(fj):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton as B
    return InlineKeyboardMarkup(inline_keyboard=[
        [B(text=("✕  ᴛᴜʀɴ ᴏғғ ғᴏʀᴄᴇ ᴊᴏɪɴ" if fj else "✓  ᴛᴜʀɴ ᴏɴ ғᴏʀᴄᴇ ᴊᴏɪɴ"),
           callback_data="a:toggle_fj")],
        [B(text="⟡  sᴇᴛ ʀᴇғᴇʀ ʀᴇᴡᴀʀᴅ", callback_data="a:set_reward")],
        [B(text="⟡  sᴇᴛ ᴍɪɴ ᴡɪᴛʜᴅʀᴀᴡ", callback_data="a:set_min")],
        [B(text="‹  ʙᴀᴄᴋ", callback_data="a:home")],
    ])
