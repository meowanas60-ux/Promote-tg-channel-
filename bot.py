import asyncio, html, logging, os, sqlite3
from contextlib import closing
from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from dotenv import load_dotenv
load_dotenv(); logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s'); log=logging.getLogger('bot')
TOKEN=os.getenv('BOT_TOKEN',''); OWNER=int(os.getenv('OWNER_ID','0')); STORAGE=int(os.getenv('STORAGE_CHANNEL_ID','0')); DB=os.getenv('DATABASE_PATH','visual_prompt_ai.db'); TARGETS=[x.strip() for x in os.getenv('PUBLISHED_CHANNELS','').split(',') if x.strip()]
bot=None; router=Router(); lock=asyncio.Lock()
def conn(): c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def row(cid):
 with closing(conn()) as c:return c.execute('select * from contents where id=?',(cid,)).fetchone()
def pub(cid,ch):
 with closing(conn()) as c:return c.execute('select * from publications where content_id=? and channel=?',(cid,ch)).fetchone()
def savepub(cid,ch,mid,status='published',err=''):
 with closing(conn()) as c:c.execute('insert into publications values(?,?,?,?,?) on conflict(content_id,channel) do update set message_id=excluded.message_id,status=excluded.status,error=excluded.error',(cid,ch,mid,status,err[:800]));c.execute('update contents set published=? where id=?',(int(__import__('time').time()),cid));c.commit()
def keyboard(cid): return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='🔓 GET PROMPT + TUTORIAL',url=f'{os.getenv("PUBLIC_BASE_URL").rstrip("/")}/content/{cid}')]])
def join_kb(cid):
 rows=[[InlineKeyboardButton(text=f'➕ Join {x}',url=f'https://t.me/{x.lstrip("@")}')] for x in TARGETS];rows.append([InlineKeyboardButton(text='✅ Check Membership',callback_data=f'check:{cid}')]);return InlineKeyboardMarkup(inline_keyboard=rows)
async def member(ch,uid):
 try:return (await bot.get_chat_member(ch,uid)).status in {'member','administrator','creator'}
 except Exception as e:log.warning('Membership %s failed: %s',ch,e);return False
async def deliver(m,cid):
 r=row(cid)
 if not r:return await m.answer('❌ Content not found.')
 if not all([await member(ch,m.from_user.id) for ch in TARGETS]):return await m.answer('🔒 আগে ৩টি published channel-এ join করুন।',reply_markup=join_kb(cid))
 try:
  await bot.copy_message(m.chat.id,STORAGE,r['storage_msg']); await m.answer('📝 <b>Full Prompt</b>\n\n<code>'+html.escape(r['prompt'])+'</code>\n\nPrompt copy করতে text-এ tap করে ধরে রাখুন।')
 except Exception:log.exception('Delivery failed');await m.answer('❌ Delivery failed. Please try again.')
@router.message(CommandStart())
async def start(m:Message):
 a=(m.text or '').split(maxsplit=1)
 if len(a)==2 and a[1].startswith('content_'):
  try:await deliver(m,int(a[1].split('_')[1]))
  except ValueError:await m.answer('❌ Invalid content link.')
 else:await m.answer('👋 Published channel-এর GET PROMPT button থেকে আসুন।')
@router.callback_query(F.data.startswith('check:'))
async def check(q:CallbackQuery):
 await q.answer();cid=int(q.data.split(':')[1]);await deliver(q.message,cid)
@router.message(Command('alive'))
async def alive(m):await m.answer('✅ Bot is online.')
@router.message(Command('status'))
async def status(m):
 if m.from_user.id!=OWNER:return
 with closing(conn()) as c:n=c.execute('select count(*) n from contents').fetchone()['n'];p=c.execute("select count(*) n from publications where status='published'").fetchone()['n'];e=c.execute("select count(*) n from publications where status='error'").fetchone()['n']
 await m.answer(f'Contents: {n}\nPublished: {p}\nErrors: {e}')
async def publish_content(cid):
 r=row(cid)
 if not r:return
 async with lock:
  for ch in TARGETS:
   if pub(cid,ch) and pub(cid,ch)['status']=='published':continue
   try:
    log.info('📤 Publishing #%s to %s',cid,ch);x=await bot.copy_message(ch,STORAGE,r['storage_msg'],reply_markup=keyboard(cid));savepub(cid,ch,x.message_id);log.info('✅ Published #%s to %s',cid,ch)
   except Exception as e:log.exception('❌ Publish failed #%s to %s',cid,ch);savepub(cid,ch,0,'error',str(e))
async def main():
 global bot
 if not TOKEN:raise RuntimeError('BOT_TOKEN missing')
 bot=Bot(TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML));dp=Dispatcher();dp.include_router(router);log.info('🤖 Bot polling started');await dp.start_polling(bot)
if __name__=='__main__':asyncio.run(main())
