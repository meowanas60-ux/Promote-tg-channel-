import os, asyncio, logging
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from aiogram.exceptions import TelegramAPIError

BOT_TOKEN=os.environ.get("BOT_TOKEN")
if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN environment variable is missing")
STORAGE_CHANNEL_ID=int(os.environ.get("STORAGE_CHANNEL_ID","-1003976996787"))
OWNER_ID=int(os.environ.get("OWNER_ID","8899691272"))

logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log=logging.getLogger("visual_prompt_bot")
bot=Bot(token=BOT_TOKEN); dp=Dispatcher()

@dp.message(CommandStart())
async def start(message: Message):
    if not message.text: return
    args=message.text.split(maxsplit=1)
    if len(args)==1:
        await message.answer("👋 Welcome to VisualPrompt AI!\n\n🎨 Use the Download button on a published photo/video post to receive the original media here.")
        return
    payload=args[1].strip()
    if not payload.startswith("dl_"):
        await message.answer("❌ Invalid download link. Please use the button from a published post."); return
    try:
        storage_id=int(payload[3:])
        if storage_id<=0: raise ValueError
    except (ValueError,TypeError):
        await message.answer("❌ Invalid download link."); return
    loading=await message.answer("⏳ Please wait...\n📦 Fetching the original media...")
    try:
        await bot.copy_message(message.chat.id,STORAGE_CHANNEL_ID,storage_id)
        await loading.delete()
    except TelegramAPIError:
        log.exception("Media delivery failed")
        await loading.edit_text("❌ Delivery failed. The media may be unavailable or the bot may not have access to the storage channel.")
    except Exception:
        log.exception("Unexpected delivery error")
        await loading.edit_text("❌ An unexpected error occurred. Please try again later.")

@dp.message(Command("stats"))
async def stats(message: Message):
    if not message.from_user or message.from_user.id!=OWNER_ID: return
    me=await bot.get_me()
    await message.answer(f"📊 VisualPrompt AI Bot\n\n🤖 @{me.username}\n🆔 {me.id}\n💾 Storage: {STORAGE_CHANNEL_ID}\n👤 Owner: {OWNER_ID}\n✅ Running!")

async def main():
    me=await bot.get_me()
    log.info("VisualPrompt AI bot started: @%s | storage=%s",me.username,STORAGE_CHANNEL_ID)
    try: await dp.start_polling(bot)
    finally: await bot.session.close()

if __name__=="__main__": asyncio.run(main())
