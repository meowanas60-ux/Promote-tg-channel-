import asyncio, html, logging, os, re, sqlite3, time
from contextlib import closing
from aiohttp import web
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Channel
load_dotenv(); logging.basicConfig(level=logging.INFO,format='%(asctime)s | %(levelname)s | %(message)s'); log=logging.getLogger('main')
API_ID=int(os.getenv('API_ID','0')); API_HASH=os.getenv('API_HASH',''); SESSION=os.getenv('SESSION_STRING',''); STORAGE=int(os.getenv('STORAGE_CHANNEL_ID','0')); PORT=int(os.getenv('PORT','10000')); DB=os.getenv('DATABASE_PATH','visual_prompt_ai.db'); BASE=os.getenv('PUBLIC_BASE_URL','https://promote-tg-channel.onrender.com').rstrip('/'); BOTNAME=os.getenv('BOT_USERNAME','VisualPromptAIBot').lstrip('@')
TARGETS=[x.strip() for x in os.getenv('PUBLISHED_CHANNELS','').split(',') if x.strip()]
SMART='https://www.profitableratecpmnetwork.com/herywwsc?key=a8803ae52732f8b9dc5b4aaf1ba40e0a'
POP='<script src="https://pl31392175.profitableratecpmnetwork.com/24/9e/8f/249e8ffb48623ecc2f8419c35b6bef1b.js"></script>'
SOCIAL='<script src="https://pl31392177.profitableratecpmnetwork.com/e8/1f/77/e81f77dcaabfb52998ffb6fe2e50a4b8.js"></script>'
NATIVE='<script async="async" data-cfasync="false" src="https://pl31392178.profitableratecpmnetwork.com/c5399e7ba5336815e27f57a310183960/invoke.js"></script><div id="container-c5399e7ba5336815e27f57a310183960"></div>'
BANNER="""<script>atOptions={'key':'27f7adc1905b29d75422693fb24c5c27','format':'iframe','height':250,'width':300,'params':{}};</script><script src='https://www.highrevenueformat.com/27f7adc1905b29d75422693fb24c5c27/invoke.js'></script>"""
WORDS=('prompt','negative prompt','midjourney','stable diffusion','flux','leonardo','ideogram','firefly','dall-e','dalle','veo','runway','kling','hailuo','image to video','text to image','ai art','cinematic prompt','video prompt','comfyui','sora','pika','seed','steps','aspect ratio')
client=None

def conn():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init_db():
 with closing(conn()) as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS contents(id INTEGER PRIMARY KEY AUTOINCREMENT,source_chat TEXT,source_msg INTEGER,storage_msg INTEGER,kind TEXT,prompt TEXT,title TEXT,created INTEGER,published INTEGER,UNIQUE(source_chat,source_msg)); CREATE TABLE IF NOT EXISTS publications(content_id INTEGER,channel TEXT,message_id INTEGER,status TEXT,error TEXT,PRIMARY KEY(content_id,channel));'''); c.commit()

def text(m): return re.sub(r'\s+',' ',m or '').strip()
def target_names(): return {x.lower() for x in TARGETS}
def excluded(e):
 u=getattr(e,'username',None); u=('@'+u).lower() if u else ''
 return u in target_names() or str(getattr(e,'id','')) in {str(STORAGE),str(abs(STORAGE))}
def valid(m): return bool((m.photo or m.video) and len(text(m.message))>=15 and any(w in text(m.message).lower() for w in WORDS))
def kind(m): return 'video' if m.video else 'photo'
def title(p,k): return (text(p).split('\n')[0][:100] or ('AI Video Prompt' if k=='video' else 'AI Image Prompt'))
def landing(cid): return f'{BASE}/content/{cid}'
def deeplink(cid): return f'https://t.me/{BOTNAME}?start=content_{cid}'

def page(r):
 cid=r['id']; p=r['prompt']; k=r['kind']; t=r['title']; media=f'<video class="media" controls playsinline src="/media/{cid}"></video>' if k=='video' else f'<img class="media" src="/media/{cid}" alt="AI image preview">'
 return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(t)} | PromptCraft Studio</title>{POP}<style>*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at top,#213d5c,#07101c 60%);color:#f8fafc;font-family:Arial,sans-serif}}.wrap{{max-width:740px;width:calc(100% - 26px);margin:auto;padding:22px 0 45px}}.head{{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:18px}}.brand{{font-weight:800;font-size:20px}}.tag{{font-size:12px;border:1px solid #7055c7;background:#35266b;padding:7px 10px;border-radius:30px}}.card{{background:#102238;border:1px solid #ffffff1c;border-radius:22px;padding:18px;box-shadow:0 20px 55px #0005}}h1{{font-size:clamp(24px,5vw,38px);margin:8px 0 10px}}.muted{{color:#aebdd0;line-height:1.6;font-size:14px}}.media{{display:block;width:100%;max-height:540px;object-fit:contain;background:#050a10;border-radius:15px;margin:18px 0;border:1px solid #ffffff18}}.ad{{display:flex;justify-content:center;overflow:hidden;margin:18px 0;min-height:80px}}.box{{background:#07111e;border:1px solid #ffffff18;border-radius:15px;padding:15px;margin-top:16px}}.label{{font-size:11px;text-transform:uppercase;letter-spacing:1.4px;color:#b9a8ff;font-weight:bold;margin-bottom:9px}}.prompt{{white-space:pre-wrap;word-break:break-word;font-size:14px;line-height:1.65;color:#e5edf7}}button,a{{width:100%;min-height:52px;border:0;border-radius:14px;display:flex;align-items:center;justify-content:center;text-decoration:none;font-weight:800;font-size:15px;cursor:pointer}}button{{background:linear-gradient(100deg,#8b5cf6,#6366f1);color:white}}a{{background:linear-gradient(100deg,#8b5cf6,#6366f1);color:white;display:none}}.copy{{background:#1d334d;color:#dbeafe;margin-top:10px;border:1px solid #ffffff18}}.note{{font-size:12px;color:#9aabc0;text-align:center;line-height:1.5;margin-top:12px}}</style></head><body><main class="wrap"><div class="head"><div class="brand">✦ PromptCraft Studio</div><div class="tag">AI Prompt Library</div></div><section class="card"><div class="muted">{'AI VIDEO PROMPT' if k=='video' else 'AI IMAGE PROMPT'}</div><h1>{html.escape(t)}</h1><div class="muted">Unlock the complete prompt and tutorial.</div>{media}<div class="ad">{BANNER}</div><div class="ad">{NATIVE}</div><div class="box"><div class="label">Prompt preview</div><div class="prompt">{html.escape(p[:700])}{'…' if len(p)>700 else ''}</div></div><div style="margin-top:18px"><button id="unlock">🔓 Unlock Full Prompt</button><a id="go" href="{deeplink(cid)}">✈️ Continue to Telegram</a><button class="copy" id="copy">📋 Copy Preview</button></div><div class="note" id="note">First tap opens the sponsor page. Return here, then continue to Telegram.</div></section><div class="ad">{SOCIAL}</div></main><script>const key='unlock_{cid}';const u=document.getElementById('unlock'),g=document.getElementById('go'),n=document.getElementById('note');function ready(){{u.style.display='none';g.style.display='flex';n.textContent='Sponsor page opened. Tap Continue to Telegram to receive the exact content.'}}if(sessionStorage.getItem(key)==='1')ready();u.onclick=()=>{{window.open({SMART!r},'_blank','noopener,noreferrer');sessionStorage.setItem(key,'1');ready()}};document.getElementById('copy').onclick=async()=>{{try{{await navigator.clipboard.writeText({p[:700]!r});document.getElementById('copy').textContent='✓ Copied'}}catch(e){{document.getElementById('copy').textContent='Select the prompt text manually'}}}};</script></body></html>'''

async def process(event):
 global client
 m=event.message; e=await event.get_chat()
 if not isinstance(e,Channel) or excluded(e) or not valid(m): return
 sid=str(e.id); p=text(m.message); k=kind(m)
 with closing(conn()) as c:
  old=c.execute('select id from contents where source_chat=? and source_msg=?',(sid,m.id)).fetchone()
  if old: return
  stored=await client.forward_messages(STORAGE,m.id,from_peer=e)
  if isinstance(stored,list): stored=stored[0]
  c.execute('insert into contents(source_chat,source_msg,storage_msg,kind,prompt,title,created) values(?,?,?,?,?,?,?)',(sid,m.id,stored.id,k,p,title(p,k),int(time.time()))); c.commit(); cid=c.execute('select last_insert_rowid()').fetchone()[0]
 log.info('💾 Stored #%s from %s/%s',cid,sid,m.id)
 from bot import publish_content
 await publish_content(int(cid))

async def media(request):
 cid=int(request.match_info['cid'])
 with closing(conn()) as c:r=c.execute('select * from contents where id=?',(cid,)).fetchone()
 if not r: raise web.HTTPNotFound()
 m=await client.get_messages(STORAGE,ids=r['storage_msg']); data=await client.download_media(m,file=bytes)
 if not data: raise web.HTTPNotFound()
 return web.Response(body=data,content_type='video/mp4' if r['kind']=='video' else 'image/jpeg')
async def content(request):
 cid=int(request.match_info['cid'])
 with closing(conn()) as c:r=c.execute('select * from contents where id=?',(cid,)).fetchone()
 if not r: raise web.HTTPNotFound()
 return web.Response(text=page(r),content_type='text/html')
async def health(request): return web.json_response({'status':'ok','service':'Visual Prompt AI'})
async def webserver():
 app=web.Application(); app.router.add_get('/',health); app.router.add_get('/health',health); app.router.add_get('/content/{cid}',content); app.router.add_get('/media/{cid}',media); runner=web.AppRunner(app); await runner.setup(); await web.TCPSite(runner,'0.0.0.0',PORT).start(); log.info('🌍 Web server listening on %s',PORT)
 while True: await asyncio.sleep(3600)
async def monitor():
 global client
 if not (API_ID and API_HASH and SESSION): raise RuntimeError('API_ID/API_HASH/SESSION_STRING missing')
 client=TelegramClient(StringSession(SESSION),API_ID,API_HASH); await client.start(); me=await client.get_me(); log.info('✅ Telegram session online: %s',getattr(me,'id','unknown'))
 dialogs=await client.get_dialogs(); n=sum(1 for d in dialogs if isinstance(d.entity,Channel) and getattr(d.entity,'broadcast',False) and not excluded(d.entity)); log.info('📡 Monitoring %s joined source channels',n)
 @client.on(events.NewMessage)
 async def handler(e):
  try: await process(e)
  except Exception: log.exception('❌ Source processing failed')
 await client.run_until_disconnected()
async def main(): init_db(); await asyncio.gather(webserver(),monitor())
if __name__=='__main__': asyncio.run(main())
