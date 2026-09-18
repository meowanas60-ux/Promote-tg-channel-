import asyncio
import os
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "8899691272"))
STORAGE_CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID", "-1003976996787"))
PUBLISHED_CHANNELS = [x.strip() for x in os.getenv(
    "PUBLISHED_CHANNELS",
    "@TheFramePromptOfficial,@NextGen_AI_Creates,@NextGenAICreates"
).split(",") if x.strip()]
REQUIRE_ALL_SUBSCRIPTIONS = os.getenv("REQUIRE_ALL_SUBSCRIPTIONS", "1") == "1"
DB_PATH = os.getenv("DB_PATH", "prompts.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def get_content(content_id):
    con = db()
    row = con.execute(
        "SELECT * FROM content WHERE content_id=?",
        (content_id,)
    ).fetchone()
    con.close()
    return row

async def is_subscribed(user_id: int, channel: str) -> bool:
    try:
        member = await bot.get_chat_member(channel, user_id)
        return member.status in {"creator", "administrator", "member"}
    except Exception:
        return False

async def subscription_status(user_id: int):
    results = []
    for ch in PUBLISHED_CHANNELS:
        results.append((ch, await is_subscribed(user_id, ch)))
    return results

def join_keyboard(content_id=None):
    rows = []
    for ch in PUBLISHED_CHANNELS:
        clean = ch.replace("@", "")
        rows.append([InlineKeyboardButton(text=f"Join @{clean}", url=f"https://t.me/{clean}")])
    callback = f"check_sub:{content_id}" if content_id else "check_sub"
    rows.append([InlineKeyboardButton(text="✅ Check Subscription", callback_data=callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def send_content(message: types.Message, content_id: str):
    row = get_content(content_id)
    if not row:
        await message.answer("❌ Content not found or no longer available.")
        return

    statuses = await subscription_status(message.from_user.id)
    ok = all(v for _, v in statuses) if REQUIRE_ALL_SUBSCRIPTIONS else any(v for _, v in statuses)

    if not ok:
        await message.answer(
            "🔒 Subscribe to the required channel(s) first, then tap Check Subscription.",
            reply_markup=join_keyboard(content_id)
        )
        return

    storage_msg_id = int(row["storage_msg_id"])
    await bot.copy_message(
        chat_id=message.chat.id,
        from_chat_id=STORAGE_CHANNEL_ID,
        message_id=storage_msg_id
    )
    tutorial = (row["tutorial"] or "").strip()
    if tutorial:
        text = (
            f"📝 <b>Prompt</b>\n{row['prompt']}\n\n"
            f"📚 <b>Tutorial / Guide</b>\n{tutorial}"
        )
    else:
        text = f"📝 <b>Prompt</b>\n{row['prompt']}"
    await message.answer(text, parse_mode="HTML")

@dp.message(CommandStart())
async def start(message: types.Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1:
        await message.answer(
            "👋 <b>Visual Prompt AI Bot</b>\n\n"
            "🟢 Bot is online.\n"
            "Open a published post and tap <b>Get Prompt & Tutorial</b> to receive the media + full prompt.\n\n"
            "Tutorial/guide is included when the source provides one.",
            parse_mode="HTML"
        )
        return
    payload = parts[1].strip()
    if payload.startswith("content_"):
        await send_content(message, payload[8:])
    else:
        await message.answer("Use the button from a published post.")

@dp.callback_query(lambda c: (c.data or "").startswith("check_sub:") or c.data == "check_sub")
async def check_sub(call: types.CallbackQuery):
    await call.answer()
    statuses = await subscription_status(call.from_user.id)
    ok = all(v for _, v in statuses) if REQUIRE_ALL_SUBSCRIPTIONS else any(v for _, v in statuses)
    data = call.data or ""
    content_id = data.split(":", 1)[1] if ":" in data else ""
    if ok:
        if content_id:
            await send_content(call.message, content_id)
        else:
            await call.message.answer("✅ Subscription verified.")
    else:
        await call.message.answer(
            "❌ Subscription is still missing. Please join the required channel(s).",
            reply_markup=join_keyboard(content_id or None)
        )

@dp.message(Command("alive"))
async def alive(message: types.Message):
    try:
        me = await bot.get_me()
        await message.answer(
            "🟢 <b>Visual Prompt AI Bot is Online!</b>\n\n"
            f"🤖 @{me.username}\n"
            "📡 Prompt delivery system: Online\n"
            "🔐 Subscription check: Online\n"
            "💾 Storage connection: Configured",
            parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"⚠️ Bot is running, but status check failed: {e}")


@dp.message(Command("stats"))
async def stats(message: types.Message):
    if message.from_user.id != OWNER_ID:
        return
    con = db()
    total = con.execute("SELECT COUNT(*) FROM content").fetchone()[0]
    tg = con.execute("SELECT COUNT(*) FROM content WHERE source_type='telegram'").fetchone()[0]
    web = con.execute("SELECT COUNT(*) FROM content WHERE source_type='web'").fetchone()[0]
    con.close()
    await message.answer(f"📊 Total: {total}\n📣 Telegram: {tg}\n🌐 Web: {web}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
