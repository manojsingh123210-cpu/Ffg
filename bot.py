import asyncio, html, re, logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton as B
)

import db, ui
from config import (
    BOT_TOKEN, ADMIN_IDS, SUPPORT_ID, VALIDATE_EMOJI, REFER_REWARD, MIN_WITHDRAW
)

logging.basicConfig(level=logging.INFO)
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp  = Dispatcher(storage=MemoryStorage())

# ═══════════════════════ STATES ═══════════════════════
class WD(StatesGroup):
    upi = State()

class Admin(StatesGroup):
    add_channel = State()
    broadcast   = State()
    give_bal    = State()
    find_user   = State()
    set_reward  = State()
    set_min     = State()

# ═══════════════════════ HELPERS ═══════════════════════
def is_admin(uid): return uid in ADMIN_IDS

async def first_not_joined(user_id):
    if (await db.get_setting("force_join", "1")) != "1":
        return None
    chans = await db.get_channels()
    for ch in chans:
        try:
            m = await bot.get_chat_member(chat_id=ch["chat_id"], user_id=user_id)
            if m.status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
                return ch
        except Exception:
            continue
    return None

async def gate(event, uid):
    """Returns True if user can proceed."""
    ch = await first_not_joined(uid)
    if ch:
        chans = await db.get_channels()
        text  = ui.join_text(chans)
        kb    = ui.join_kb(chans)
        if isinstance(event, CallbackQuery):
            await event.message.answer(text, reply_markup=kb, disable_web_page_preview=True)
            await event.answer()
        else:
            await event.answer(text, reply_markup=kb, disable_web_page_preview=True)
        return False
    return True

def ref_link(uid, bot_username):
    return f"https://t.me/{bot_username}?start=ref_{uid}"

# ═══════════════════════ /start ═══════════════════════
@dp.message(CommandStart())
async def start(m: Message):
    args = m.text.split(maxsplit=1)
    ref_by = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            rid = int(args[1][4:])
            if rid != m.from_user.id:
                ref_by = rid
        except ValueError:
            pass

    await db.create_user(m.from_user.id, m.from_user.username,
                         m.from_user.first_name, ref_by)

    ch = await first_not_joined(m.from_user.id)
    if ch:
        chans = await db.get_channels()
        await m.answer(ui.join_text(chans), reply_markup=ui.join_kb(chans),
                       disable_web_page_preview=True)
        return

    await show_main(m.from_user.id, m)

async def show_main(uid, m):
    user = await db.get_user(uid)
    me   = await bot.get_me()
    link = ref_link(uid, me.username)
    await m.answer(ui.main_menu_text(user, link),
                   reply_markup=ui.main_menu_kb())

# ═══════════════════════ VERIFY ═══════════════════════
@dp.callback_query(F.data == "check_join")
async def cb_verify(cb: CallbackQuery):
    ch = await first_not_joined(cb.from_user.id)
    if ch:
        await cb.answer("❌ ᴘᴇʜʟᴇ sᴀᴀʀᴇ ᴄʜᴀɴɴᴇʟs ᴊᴏɪɴ ᴋᴀʀᴇ!", show_alert=True)
        return

    user = await db.get_user(cb.from_user.id)
    if not user:
        await db.create_user(cb.from_user.id, cb.from_user.username, cb.from_user.first_name)
        user = await db.get_user(cb.from_user.id)

    if not user["verified"]:
        await db.set_verified(cb.from_user.id)
        if user["referred_by"]:
            ok = await db.credit_refer(user["referred_by"], cb.from_user.id)
            if ok:
                reward = await db.get_setting_float("refer_reward", REFER_REWARD)
                try:
                    await bot.send_message(
                        user["referred_by"],
                        f"{ui.DIV}\n  <b>[PE: 62] ʀᴇғᴇʀ ʙᴏɴᴜs</b>\n{ui.DIV}\n\n"
                        f"  [PE: 63] +₹{reward:.0f} ᴄʀᴇᴅɪᴛᴇᴅ\n"
                        f"  [PE: 64] ɴᴇᴡ ʀᴇғᴇʀ ᴠᴇʀɪғɪᴇᴅ ✓\n{ui.DIV}"
                    )
                except Exception:
                    pass

    user = await db.get_user(cb.from_user.id)
    me   = await bot.get_me()
    link = ref_link(cb.from_user.id, me.username)

    await cb.message.edit_text(ui.main_menu_text(user, link),
                               reply_markup=ui.main_menu_kb())
    await cb.answer("✓ ᴠᴇʀɪғɪᴇᴅ")

# ═══════════════════════ MAIN MENU ═══════════════════════
@dp.callback_query(F.data == "m:home")
async def cb_home(cb: CallbackQuery):
    if not await gate(cb, cb.from_user.id): return
    user = await db.get_user(cb.from_user.id)
    me   = await bot.get_me()
    await cb.message.edit_text(ui.main_menu_text(user, ref_link(cb.from_user.id, me.username)),
                               reply_markup=ui.main_menu_kb())
    await cb.answer()

@dp.callback_query(F.data == "m:profile")
async def cb_profile(cb: CallbackQuery):
    if not await gate(cb, cb.from_user.id): return
    user = await db.get_user(cb.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[B(text="‹  ʙᴀᴄᴋ", callback_data="m:home")]])
    await cb.message.edit_text(ui.profile_text(user), reply_markup=kb)
    await cb.answer()

@dp.callback_query(F.data == "m:refer")
async def cb_refer(cb: CallbackQuery):
    if not await gate(cb, cb.from_user.id): return
    user = await db.get_user(cb.from_user.id)
    me   = await bot.get_me()
    reward = await db.get_setting_float("refer_reward", REFER_REWARD)
    link = ref_link(cb.from_user.id, me.username)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [B(text="⟡  sʜᴀʀᴇ ʟɪɴᴋ", url=f"https://t.me/share/url?url={link}&text=ᴊᴏɪɴ ᴋᴀʀᴏ ᴀᴜʀ ₹{reward:.0f} ᴋᴀᴍᴀᴏ")],
        [B(text="‹  ʙᴀᴄᴋ", callback_data="m:home")],
    ])
    await cb.message.edit_text(ui.refer_text(user, link, reward), reply_markup=kb,
                               disable_web_page_preview=True)
    await cb.answer()

@dp.callback_query(F.data == "m:help")
async def cb_help(cb: CallbackQuery):
    if not await gate(cb, cb.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [B(text="⟡  sᴜᴘᴘᴏʀᴛ", url=f"https://t.me/{SUPPORT_ID.lstrip('@')}")],
        [B(text="‹  ʙᴀᴄᴋ", callback_data="m:home")],
    ])
    await cb.message.edit_text(ui.help_text(SUPPORT_ID), reply_markup=kb)
    await cb.answer()

@dp.callback_query(F.data == "m:tools")
async def cb_tools(cb: CallbackQuery):
    if not await gate(cb, cb.from_user.id): return
    await cb.message.edit_text(ui.tools_text(), reply_markup=ui.tools_kb())
    await cb.answer()

@dp.callback_query(F.data.startswith("tool:"))
async def cb_tool(cb: CallbackQuery):
    tool = cb.data.split(":")[1]
    if tool == "emoji":
        await cb.message.edit_text(ui.tool_prompt("emoji"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="‹  ʙᴀᴄᴋ", callback_data="m:tools")]]))
    else:
        await cb.message.edit_text(ui.tool_prompt("font"),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="‹  ʙᴀᴄᴋ", callback_data="m:tools")]]))
    await cb.answer()

# ═══════════════════════ EMOJI EXTRACTOR ═══════════════════════
@dp.message(F.text)
async def emoji_extract(m: Message):
    ents = [e for e in (m.entities or []) if e.type == "custom_emoji"]
    if not ents:
        return
    eid = ents[0].custom_emoji_id
    valid = False
    fallback = "✨"
    if VALIDATE_EMOJI:
        try:
            stickers = await bot.get_custom_emoji_stickers([eid])
            valid = bool(stickers)
            if stickers and stickers[0].emoji:
                fallback = stickers[0].emoji
        except Exception:
            valid = False
    await m.answer(ui.emoji_success(eid, valid, fallback),
                   reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                       [B(text="‹  ᴛᴏᴏʟs", callback_data="m:tools")]
                   ]))

# ═══════════════════════ WITHDRAW ═══════════════════════
@dp.callback_query(F.data == "m:withdraw")
async def cb_withdraw(cb: CallbackQuery):
    if not await gate(cb, cb.from_user.id): return
    user = await db.get_user(cb.from_user.id)
    minwd = await db.get_setting_float("min_withdraw", MIN_WITHDRAW)
    pend = await db.user_pending_withdrawals(cb.from_user.id)
    await cb.message.edit_text(ui.withdraw_text(user, minwd, pend),
                               reply_markup=ui.withdraw_kb())
    await cb.answer()

@dp.callback_query(F.data == "wd:new")
async def cb_wd_new(cb: CallbackQuery, state: FSMContext):
    if not await gate(cb, cb.from_user.id): return
    user = await db.get_user(cb.from_user.id)
    minwd = await db.get_setting_float("min_withdraw", MIN_WITHDRAW)

    if user["balance"] < minwd:
        await cb.answer(f"❌ ᴍɪɴɪᴍᴜᴍ ₹{minwd:.0f} ʙᴀʟᴀɴᴄᴇ ᴄʜᴀʜɪʏᴇ", show_alert=True)
        return

    pend = await db.user_pending_withdrawals(cb.from_user.id)
    if pend:
        await cb.answer("⏳ ᴇᴋ ʀᴇǫᴜᴇsᴛ ᴀʟʀᴇᴀᴅʏ ᴘᴇɴᴅɪɴɢ ʜᴀɪ", show_alert=True)
        return

    await state.set_state(WD.upi)
    await cb.message.edit_text(
        f"{ui.DIV}\n  <b>[PE: 65] ᴜᴘɪ ᴇɴᴛᴇʀ</b>\n{ui.DIV}\n\n"
        f"  [PE: 66] ᴀᴘɴᴀ ᴜᴘɪ ɪᴅ sᴇɴᴅ ᴋᴀʀᴇ\n"
        f"  [PE: 67] ᴇx › <code>name@upi</code>\n\n"
        f"{ui.LINE}\n  [PE: 68] ʀᴇǫᴜᴇsᴛ ʙʜᴇᴊɴᴇ ᴘᴀʀ ᴀᴍᴏᴜɴᴛ ᴅᴇᴅᴜᴄᴛ ʜᴏɢᴀ\n"
        f"{ui.DIV}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [B(text="✕  ᴄᴀɴᴄᴇʟ", callback_data="m:withdraw")]
        ]),
    )
    await cb.answer()

@dp.message(WD.upi)
async def wd_get_upi(m: Message, state: FSMContext):
    upi = m.text.strip()
    if not re.match(r"^[\w.\-]{2,}@[\w]{2,}$", upi):
        await m.answer(
            f"{ui.DIV}\n  [PE: 69] ɪɴᴠᴀʟɪᴅ ᴜᴘɪ\n  [PE: 70] ғᴏʀᴍᴀᴛ › name@upi\n{ui.DIV}"
        )
        return

    user  = await db.get_user(m.from_user.id)
    minwd = await db.get_setting_float("min_withdraw", MIN_WITHDRAW)
    amount = user["balance"]

    if amount < minwd:
        await state.clear()
        await m.answer(f"❌ ʙᴀʟᴀɴᴄᴇ ɪɴsᴜғғɪᴄɪᴇɴᴛ (ᴍɪɴ ₹{minwd:.0f})")
        return

    # deduct immediately
    await db.update_balance(m.from_user.id, -amount)
    wid = await db.create_withdrawal(m.from_user.id, upi, amount)
    await state.clear()

    # notify user
    await m.answer(
        f"{ui.DIV}\n   <b>[PE: 71] ʀᴇǫᴜᴇsᴛ sᴜʙᴍɪᴛᴛᴇᴅ</b>\n{ui.DIV}\n\n"
        f"  [PE: 72] ʀᴇǫ ᴏᴅ  ›  #{wid}\n"
        f"  [PE: 73] ᴀᴍᴏᴜɴᴛ  ›  ₹{amount:.2f}\n"
        f"  [PE: 74] ᴜᴘɪ    ›  <code>{html.escape(upi)}</code>\n\n"
        f"{ui.LINE}\n  [PE: 75] ᴀᴅᴍɪɴ 24ʜ ᴍᴇ ᴘʀᴏᴄᴇss ᴋᴀʀᴇɢᴀ\n{ui.DIV}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="‹  ʜᴏᴍᴇ", callback_data="m:home")]])
    )

    # notify admins
    uname = f"@{m.from_user.username}" if m.from_user.username else "—"
    txt = (
        f"{ui.DIV}\n   <b>[PE: 76] ɴᴇᴡ ᴡɪᴛʜᴅʀᴀᴡ ʀᴇǫᴜᴇsᴛ</b>\n{ui.DIV}\n\n"
        f"  [PE: 77] ʀᴇǫ ɪᴅ  ›  #{wid}\n"
        f"  [PE: 78] ᴜsᴇʀ    ›  {html.escape(m.from_user.first_name)}\n"
        f"  [PE: 79] ᴜsᴇʀɴᴀᴍᴇ›  {uname}\n"
        f"  [PE: 80] ᴛɢ ɪᴅ   ›  <code>{m.from_user.id}</code>\n"
        f"  [PE: 81] ᴀᴍᴏᴜɴᴛ  ›  ₹{amount:.2f}\n"
        f"  [PE: 82] ᴜᴘɪ    ›  <code>{html.escape(upi)}</code>\n"
        f"{ui.DIV}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        B(text="✓ ᴀᴄᴄᴇᴘᴛ",  callback_data=f"wd:ok:{wid}"),
        B(text="✕ ʀᴇᴊᴇᴄᴛ", callback_data=f"wd:no:{wid}"),
    ]])
    for a in ADMIN_IDS:
        try: await bot.send_message(a, txt, reply_markup=kb)
        except Exception: pass

@dp.callback_query(F.data.startswith("wd:ok:"))
async def wd_accept(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    wid = int(cb.data.split(":")[2])
    w = await db.get_withdrawal(wid)
    if not w or w["status"] != "pending":
        return await cb.answer("⚠️ ᴀʟʀᴇᴀᴅʏ ᴘʀᴏᴄᴇssᴇᴅ", show_alert=True)

    await db.set_withdrawal_status(wid, "approved")
    await cb.message.edit_text(cb.message.html_text + "\n\n✓ <b>ᴀᴘᴘʀᴏᴠᴇᴅ</b>")
    try:
        await bot.send_message(w["user_id"],
            f"{ui.DIV}\n  <b>[PE: 83] ᴡɪᴛʜᴅʀᴀᴡ ᴀᴘᴘʀᴏᴠᴇᴅ ✓</b>\n{ui.DIV}\n\n"
            f"  [PE: 84] ʀᴇǫ #{wid}  ›  ₹{w['amount']:.2f}\n"
            f"  [PE: 85] ᴜᴘɪ  ›  <code>{html.escape(w['upi'])}</code>\n"
            f"  [PE: 86] ᴘᴀʏᴍᴇɴᴛ 24ʜ ᴍᴇ ᴀᴀʏᴇɢɪ\n{ui.DIV}")
    except Exception: pass
    await cb.answer("✓ Approved")

@dp.callback_query(F.data.startswith("wd:no:"))
async def wd_reject(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    wid = int(cb.data.split(":")[2])
    w = await db.get_withdrawal(wid)
    if not w or w["status"] != "pending":
        return await cb.answer("⚠️ ᴀʟʀᴇᴀᴅʏ ᴘʀᴏᴄᴇssᴇᴅ", show_alert=True)

    await db.set_withdrawal_status(wid, "rejected")
    await db.update_balance(w["user_id"], w["amount"])  # refund
    await cb.message.edit_text(cb.message.html_text + "\n\n✕ <b>ʀᴇᴊᴇᴄᴛᴇᴅ</b>")
    try:
        await bot.send_message(w["user_id"],
            f"{ui.DIV}\n  <b>[PE: 87] ᴡɪᴛʜᴅʀᴀᴡ ʀᴇᴊᴇᴄᴛᴇᴅ</b>\n{ui.DIV}\n\n"
            f"  [PE: 88] ʀᴇǫ #{wid}  ›  ₹{w['amount']:.2f}\n"
            f"  [PE: 89] ᴀᴍᴏᴜɴᴛ ʀᴇғᴜɴᴅᴇᴅ ✓\n{ui.DIV}")
    except Exception: pass
    await cb.answer("✕ Rejected")

# ═══════════════════════ ADMIN ═══════════════════════
@dp.message(Command("admin"))
async def admin_cmd(m: Message):
    if not is_admin(m.from_user.id):
        return await m.answer("❌ ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ")
    stats = await db.stats_summary()
    await m.answer(ui.admin_text(stats, SUPPORT_ID), reply_markup=ui.admin_kb())

@dp.callback_query(F.data == "a:home")
async def a_home(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    stats = await db.stats_summary()
    await cb.message.edit_text(ui.admin_text(stats, SUPPORT_ID), reply_markup=ui.admin_kb())
    await cb.answer()

@dp.callback_query(F.data == "a:close")
async def a_close(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await cb.message.delete()
    await cb.answer()

@dp.callback_query(F.data == "a:stats")
async def a_stats(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    s = await db.stats_summary()
    txt = (
        f"{ui.DIV}\n   <b>[PE: 90] sᴛᴀᴛs</b>\n{ui.DIV}\n\n"
        f"  [PE: 91] ᴛᴏᴛᴀʟ ᴜsᴇʀs  ›  <b>{s['total_users']}</b>\n"
        f"  [PE: 92] ᴠᴇʀɪғɪᴇᴅ    ›  {s['verified_users']}\n"
        f"  [PE: 93] ᴘᴇɴᴅɪɴɢ ᴡᴅ  ›  {s['pending_wd']}\n"
        f"  [PE: 94] ᴛᴏᴛᴀʟ ᴘᴀɪᴅ  ›  ₹{s['total_paid']:.2f}\n"
        f"  [PE: 95] ᴄʜᴀɴɴᴇʟs   ›  {s['channels']}\n"
        f"{ui.DIV}"
    )
    await cb.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="‹  ʙᴀᴄᴋ", callback_data="a:home")]]))
    await cb.answer()

@dp.callback_query(F.data == "a:users")
async def a_users(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    top = await db.top_referrers(10)
    body = "\n".join(
        [f"  {i}. {html.escape(t['first_name'])} › ₹{t['balance']:.0f} › {t['ref_count']} ʀᴇғs"
         for i, t in enumerate(top, 1)]
    ) or "  —"
    txt = (f"{ui.DIV}\n  <b>[PE: 96] ᴛᴏᴘ ᴜsᴇʀs</b>\n{ui.DIV}\n\n{body}\n{ui.DIV}")
    await cb.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="‹  ʙᴀᴄᴋ", callback_data="a:home")]]))
    await cb.answer()

@dp.callback_query(F.data == "a:wd")
async def a_wd(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    pend = await db.pending_withdrawals()
    if not pend:
        await cb.message.edit_text(
            f"{ui.DIV}\n  [PE: 97] ᴋᴏɪ ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛ ɴᴀʜɪ\n{ui.DIV}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="‹  ʙᴀᴄᴋ", callback_data="a:home")]]))
        return await cb.answer()

    for w in pend:
        u = await db.get_user(w["user_id"])
        txt = (
            f"{ui.DIV}\n  <b>[PE: 98] ᴡɪᴛʜᴅʀᴀᴡ #{w['id']}</b>\n{ui.DIV}\n\n"
            f"  [PE: 99] ᴜsᴇʀ   ›  {html.escape(u['first_name'] if u else '?')}\n"
            f"  [PE: 100] ᴛɢ ɪᴅ  ›  <code>{w['user_id']}</code>\n"
            f"  [PE: 101] ᴀᴍᴏᴜɴᴛ ›  ₹{w['amount']:.2f}\n"
            f"  [PE: 102] ᴜᴘɪ   ›  <code>{html.escape(w['upi'])}</code>\n"
            f"{ui.DIV}"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            B(text="✓ ᴀᴄᴄᴇᴘᴛ",  callback_data=f"wd:ok:{w['id']}"),
            B(text="✕ ʀᴇᴊᴇᴄᴛ", callback_data=f"wd:no:{w['id']}"),
        ]])
        await cb.message.answer(txt, reply_markup=kb)
    await cb.answer()

@dp.callback_query(F.data == "a:channels")
async def a_channels(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    chans = await db.get_channels()
    await cb.message.edit_text(ui.channels_text(chans), reply_markup=ui.channels_kb(chans))
    await cb.answer()

@dp.callback_query(F.data == "a:addch")
async def a_addch(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(Admin.add_channel)
    await cb.message.edit_text(
        f"{ui.DIV}\n  <b>[PE: 103] ᴀᴅᴅ ᴄʜᴀɴɴᴇʟ</b>\n{ui.DIV}\n\n"
        f"  [PE: 104] ᴄʜᴀɴɴᴇʟ ɪᴅ / @ᴜsᴇʀɴᴀᴍᴇ / ʟɪɴᴋ sᴇɴᴅ ᴋᴀʀᴇ\n"
        f"  [PE: 105] ʙᴏᴛ ᴜs ᴄʜᴀɴɴᴇʟ ᴍᴇ ᴀᴅᴍɪɴ ʜᴏɴᴀ ᴄʜᴀʜɪʏᴇ\n\n"
        f"{ui.LINE}\n  [PE: 106] ᴇx › <code>@mychannel</code>  ᴏʀ  <code>-1001234567890</code>\n{ui.DIV}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="✕  ᴄᴀɴᴄᴇʟ", callback_data="a:channels")]]),
    )
    await cb.answer()

@dp.message(Admin.add_channel)
async def a_addch_input(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    raw = m.text.strip().replace("https://t.me/", "@").replace("t.me/", "@")
    if raw.startswith("https://"):
        raw = raw.split("/")[-1]
        raw = "@" + raw if not raw.startswith("@") else raw
    try:
        chat = await bot.get_chat(raw)
        member = await bot.get_chat_member(chat.id, (await bot.get_me()).id)
        if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            await m.answer("❌ ʙᴏᴛ ᴜs ᴄʜᴀɴɴᴇʟ ᴍᴇ ᴀᴅᴍɪɴ ʙᴀɴᴀᴏ")
            return
        link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else None)
        if not link:
            await m.answer("❌ ɪɴᴠɪᴛᴇ ʟɪɴᴋ ɴᴀʜɪ ᴍɪʟᴀ. ᴄʜᴀɴɴᴇʟ ᴘᴜʙʟɪᴄ ᴋᴀʀᴏ")
            return
        await db.add_channel(chat.id, chat.title, link)
        await state.clear()
        chans = await db.get_channels()
        await m.answer(f"✓ <b>{html.escape(chat.title)}</b> ᴀᴅᴅᴇᴅ\n\n" + ui.channels_text(chans),
                       reply_markup=ui.channels_kb(chans))
    except Exception as e:
        await m.answer(f"❌ ᴇʀʀᴏʀ › <code>{html.escape(str(e))}</code>")

@dp.callback_query(F.data.startswith("a:delch:"))
async def a_delch(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    cid = int(cb.data.split(":")[2])
    await db.del_channel(cid)
    chans = await db.get_channels()
    await cb.message.edit_text(ui.channels_text(chans), reply_markup=ui.channels_kb(chans))
    await cb.answer("✓ Removed")

@dp.callback_query(F.data == "a:settings")
async def a_settings(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    fj = (await db.get_setting("force_join", "1")) == "1"
    rw = await db.get_setting_float("refer_reward", REFER_REWARD)
    mn = await db.get_setting_float("min_withdraw", MIN_WITHDRAW)
    await cb.message.edit_text(ui.settings_text(fj, rw, mn), reply_markup=ui.settings_kb(fj))
    await cb.answer()

@dp.callback_query(F.data == "a:toggle_fj")
async def a_toggle_fj(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    cur = await db.get_setting("force_join", "1")
    await db.set_setting("force_join", "0" if cur == "1" else "1")
    fj = (await db.get_setting("force_join", "1")) == "1"
    rw = await db.get_setting_float("refer_reward", REFER_REWARD)
    mn = await db.get_setting_float("min_withdraw", MIN_WITHDRAW)
    await cb.message.edit_text(ui.settings_text(fj, rw, mn), reply_markup=ui.settings_kb(fj))
    await cb.answer("✓ Updated")

@dp.callback_query(F.data == "a:set_reward")
async def a_set_reward(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(Admin.set_reward)
    await cb.message.edit_text(
        f"{ui.DIV}\n  [PE: 107] ɴᴇᴡ ʀᴇғᴇʀ ʀᴇᴡᴀʀᴅ (₹) sᴇɴᴅ\n{ui.DIV}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="✕  ᴄᴀɴᴄᴇʟ", callback_data="a:settings")]]),
    )
    await cb.answer()

@dp.message(Admin.set_reward)
async def a_set_reward_input(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    try:
        v = float(m.text.strip())
        await db.set_setting("refer_reward", v)
        await state.clear()
        await m.answer(f"✓ ʀᴇғᴇʀ ʀᴇᴡᴀʀᴅ › ₹{v:.0f}")
    except ValueError:
        await m.answer("❌ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ sᴇɴᴅ ᴋᴀʀᴇ")

@dp.callback_query(F.data == "a:set_min")
async def a_set_min(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(Admin.set_min)
    await cb.message.edit_text(
        f"{ui.DIV}\n  [PE: 108] ɴᴇᴡ ᴍɪɴ ᴡɪᴛʜᴅʀᴀᴡ (₹) sᴇɴᴅ\n{ui.DIV}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="✕  ᴄᴀɴᴄᴇʟ", callback_data="a:settings")]]),
    )
    await cb.answer()

@dp.message(Admin.set_min)
async def a_set_min_input(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    try:
        v = float(m.text.strip())
        await db.set_setting("min_withdraw", v)
        await state.clear()
        await m.answer(f"✓ ᴍɪɴ ᴡɪᴛʜᴅʀᴀᴡ › ₹{v:.0f}")
    except ValueError:
        await m.answer("❌ ᴠᴀʟɪᴅ ɴᴜᴍʙᴇʀ sᴇɴᴅ ᴋᴀʀᴇ")

@dp.callback_query(F.data == "a:broadcast")
async def a_broadcast(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(Admin.broadcast)
    await cb.message.edit_text(
        f"{ui.DIV}\n  [PE: 109] ʙʀᴏᴀᴅᴄᴀsᴛ ᴍᴇssᴀɢᴇ sᴇɴᴅ ᴋᴀʀᴇ\n{ui.DIV}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="✕  ᴄᴀɴᴄᴇʟ", callback_data="a:home")]]),
    )
    await cb.answer()

@dp.message(Admin.broadcast)
async def a_broadcast_send(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    await state.clear()
    ids = await db.all_user_ids()
    ok = fail = 0
    status = await m.answer(f"⏳ sᴇɴᴅɪɴɢ ᴛᴏ {len(ids)} ᴜsᴇʀs...")
    for uid in ids:
        try:
            await m.copy_to(uid)
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1
    await status.edit_text(f"✓ ᴅᴏɴᴇ\n✓ sᴇɴᴛ: {ok}\n✕ ғᴀɪʟᴇᴅ: {fail}")

@dp.callback_query(F.data == "a:give")
async def a_give(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(Admin.give_bal)
    await cb.message.edit_text(
        f"{ui.DIV}\n  [PE: 110] ғᴏʀᴍᴀᴛ › <code>USER_ID AMOUNT</code>\n"
        f"  [PE: 111] ᴇx › <code>123456789 50</code>\n{ui.DIV}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="✕  ᴄᴀɴᴄᴇʟ", callback_data="a:home")]]),
    )
    await cb.answer()

@dp.message(Admin.give_bal)
async def a_give_input(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    try:
        uid_s, amt_s = m.text.split()
        uid, amt = int(uid_s), float(amt_s)
        u = await db.get_user(uid)
        if not u:
            return await m.answer("❌ ᴜsᴇʀ ɴᴀʜɪ ᴍɪʟᴀ")
        await db.update_balance(uid, amt)
        await db.set_setting("_ignore", "0")
        await state.clear()
        await m.answer(f"✓ ₹{amt:.2f} ɢɪᴠᴇɴ ᴛᴏ <code>{uid}</code>")
        try:
            await bot.send_message(uid,
                f"{ui.DIV}\n  [PE: 112] ᴀᴅᴍɪɴ ʙᴏɴᴜs\n"
                f"  [PE: 113] +₹{amt:.2f} ᴄʀᴇᴅɪᴛᴇᴅ\n{ui.DIV}")
        except Exception: pass
    except Exception:
        await m.answer("❌ ғᴏʀᴍᴀᴛ › <code>USER_ID AMOUNT</code>")

@dp.callback_query(F.data == "a:find")
async def a_find(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌", show_alert=True)
    await state.set_state(Admin.find_user)
    await cb.message.edit_text(
        f"{ui.DIV}\n  [PE: 114] ᴜsᴇʀ ɪᴅ sᴇɴᴅ ᴋᴀʀᴇ\n{ui.DIV}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[B(text="✕  ᴄᴀɴᴄᴇʟ", callback_data="a:home")]]),
    )
    await cb.answer()

@dp.message(Admin.find_user)
async def a_find_input(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id): return
    try:
        uid = int(m.text.strip())
    except ValueError:
        return await m.answer("❌ ɪɴᴠᴀʟɪᴅ ɪᴅ")
    u = await db.get_user(uid)
    await state.clear()
    if not u:
        return await m.answer("❌ ᴜsᴇʀ ɴᴀʜɪ ᴍɪʟᴀ")
    await m.answer(ui.profile_text(u))

# ═══════════════════════ RUN ═══════════════════════
async def main():
    await db.init()
    print("🤖 Bot started...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
