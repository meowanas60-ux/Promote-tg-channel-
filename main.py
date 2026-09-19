import os
import re
import asyncio
import logging
from html import escape as html_escape
from urllib.parse import quote
from aiohttp import web
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import FloodWaitError

API_ID=int(os.environ.get("API_ID","35317271"))
API_HASH=os.environ.get("API_HASH","")
SESSION_STRING=os.environ.get("SESSION_STRING")
if not SESSION_STRING: raise RuntimeError("SESSION_STRING environment variable is missing")

DOWNLOAD_BOT_USERNAME=os.environ.get("DOWNLOAD_BOT_USERNAME","VisualPromptAIBot").strip().lstrip("@")
PUBLIC_BASE_URL=os.environ.get("PUBLIC_BASE_URL","https://your-service.onrender.com").rstrip("/")
STORAGE_CHANNEL_ID=int(os.environ.get("STORAGE_CHANNEL_ID","-1003976996787"))
OWNER_ID=int(os.environ.get("OWNER_ID","8899691272"))
DEST_CHANNELS=[x.strip().lstrip("@") for x in os.environ.get("DEST_CHANNELS","TheFramePromptOfficial,NextGen_AI_Creates,NextGenAICreates").split(",") if x.strip()]
SOURCE_CHANNELS=[x.strip().lstrip("@") for x in os.environ.get("SOURCE_CHANNELS","").split(",") if x.strip()]
IGNORE_CHANNELS={x.lower() for x in DEST_CHANNELS}|{str(STORAGE_CHANNEL_ID)}
ADSTERRA_SMARTLINK=os.environ.get("ADSTERRA_SMARTLINK","").strip()
POST_INTERVAL_SECONDS=int(os.environ.get("POST_INTERVAL_SECONDS","1800"))
CHANNEL_DELAY_SECONDS=int(os.environ.get("CHANNEL_DELAY_SECONDS","5"))

logging.basicConfig(level=logging.INFO,format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log=logging.getLogger("visual_prompt_monitor")
client=TelegramClient(StringSession(SESSION_STRING),API_ID,API_HASH)

QUEUE=[]; SEEN=set(); PUBLISHED=set(); ME_ID=None
STATS={"sent":0,"queued":0,"duplicates":0,"storage_saved":0,"storage_failed":0,"send_failed":0,"photos":0,"videos":0}

BLOCKED_TERMS=("1xbet","aviator","casino","gambling","betting","melbet","baji","jeet","cricket365","deposit money","daily profit","hack and earn","investment guaranteed")

def clean_prompt(text):
    if not text: return ""
    text=re.sub(r"https?://\S+","",text)
    text=re.sub(r"t\.me/\S+","",text)
    text=re.sub(r"@\w+","",text)
    text=re.sub(r"\[([^\]]+)\]\([^)]+\)",r"\1",text)
    text=re.sub(r"\n{3,}","\n\n",text)
    return text.strip()

def blocked(text): return any(x in (text or "").lower() for x in BLOCKED_TERMS)

def media_kind(message):
    if getattr(message,"photo",None): return "Photo"
    if getattr(message,"video",None): return "Video"
    doc=getattr(message,"document",None)
    mime=getattr(doc,"mime_type",None) if doc else None
    if mime and mime.lower().startswith("video/"): return "Video"
    return None

def key(event): return f"{event.chat_id}:{event.id}"

async def allowed(event):
    chat=await event.get_chat()
    username=getattr(chat,"username",None)
    if username:
        u=username.lower()
        if u in IGNORE_CHANNELS: return False
        if SOURCE_CHANNELS: return u in {x.lower() for x in SOURCE_CHANNELS}
        return True
    if SOURCE_CHANNELS:
        vals={str(x).lstrip("-") for x in SOURCE_CHANNELS}
        return str(event.chat_id).lstrip("-") in vals
    return str(event.chat_id)!=str(STORAGE_CHANNEL_ID)

def landing_html(storage_id,title,kind,prompt):
    title=html_escape(title or "Visual Prompt"); kind=html_escape(kind or "Media"); prompt=html_escape(prompt or "Visual prompt")
    tg=f"https://t.me/{DOWNLOAD_BOT_USERNAME}?start=dl_{storage_id}"
    if ADSTERRA_SMARTLINK:
        href=ADSTERRA_SMARTLINK; label="Continue to Download"
        js=f"""const b=document.getElementById('b'),n=document.getElementById('n'),tg={tg!r},ad={ADSTERRA_SMARTLINK!r},k='vpai_{storage_id}';
function mode(){{b.href=tg;b.textContent='Get Original Media';n.textContent='Tap again to open Telegram and receive the original file.'}}
if(sessionStorage.getItem(k)==='1')mode();
b.onclick=function(){{if(sessionStorage.getItem(k)!=='1'){{sessionStorage.setItem(k,'1');b.href=ad}}else b.href=tg}};"""
    else:
        href=tg; label="Get Original Media"; js=""
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} | VisualPrompt AI</title><style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;padding:22px 12px;font-family:Arial,sans-serif;color:#fff;background:linear-gradient(180deg,#70bd79,#55a99a 38%,#347fb1 72%,#2364a4)}}.page{{max-width:480px;margin:auto}}.brand{{text-align:center;margin:8px 0 22px}}.logo{{width:92px;height:92px;margin:auto;border-radius:50%;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.16);border:2px solid rgba(255,255,255,.5);font-size:24px;font-weight:800}}.brand h1{{margin:14px 0 5px;font-size:25px}}.brand p{{margin:0;color:rgba(255,255,255,.78);font-size:13px}}.card{{padding:21px;border-radius:24px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.28);box-shadow:0 18px 45px rgba(0,0,0,.14);backdrop-filter:blur(12px)}}.icon{{width:78px;height:78px;margin:0 auto 14px;border-radius:20px;display:flex;align-items:center;justify-content:center;background:#fff;color:#277bb0;font-weight:800;font-size:22px}}.title{{text-align:center}}.title h2{{margin:0;font-size:22px;word-break:break-word}}.badge{{display:inline-block;margin-top:8px;padding:5px 11px;border-radius:30px;background:rgba(255,255,255,.18);font-size:12px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:18px 0}}.item{{padding:12px 8px;border-radius:13px;text-align:center;background:rgba(255,255,255,.12)}}.item small{{display:block;color:rgba(255,255,255,.68);font-size:10px;text-transform:uppercase;margin-bottom:5px}}.prompt{{margin-top:16px;padding:14px;border-radius:13px;background:rgba(0,0,0,.12);font-size:13px;line-height:1.65;white-space:pre-wrap;word-break:break-word}}.btn{{display:block;margin-top:20px;padding:15px;border-radius:13px;background:#fff;color:#2775aa;text-align:center;text-decoration:none;font-size:16px;font-weight:800}}.note{{margin:11px 0 0;text-align:center;color:rgba(255,255,255,.72);font-size:11px;line-height:1.5}}.footer{{margin:20px 0 4px;text-align:center;font-size:11px;color:rgba(255,255,255,.65)}}</style></head>
<body><main class="page"><header class="brand"><div class="logo">VP</div><h1>VisualPrompt AI</h1><p>AI Photo &amp; Video Prompts</p></header><section class="card"><div class="icon">{kind[:3].upper()}</div><div class="title"><h2>{title}</h2><span class="badge">{kind}</span></div><div class="grid"><div class="item"><small>Media</small><strong>{kind}</strong></div><div class="item"><small>Source</small><strong>Telegram</strong></div></div><div class="prompt"><strong>Prompt</strong><br>{prompt}</div><a id="b" class="btn" href="{href}" rel="nofollow sponsored noopener noreferrer">{label}</a><p id="n" class="note">Continue to receive the original media.</p></section><div class="footer">© 2026 VisualPrompt AI</div></main><script>{js}</script></body></html>"""

async def start_web():
    async def health(request): return web.Response(text="VisualPrompt AI is alive ✅")
    async def download(request):
        try:
            sid=int(request.match_info["storage_msg_id"])
            title=request.query.get("title","Visual Prompt"); kind=request.query.get("type","Media"); prompt=request.query.get("prompt","")
            return web.Response(text=landing_html(sid,title,kind,prompt),content_type="text/html")
        except Exception: return web.Response(text="Invalid download link",status=400)
    app=web.Application(); app.router.add_get("/",health); app.router.add_get("/health",health); app.router.add_get("/download/{storage_msg_id}",download)
    runner=web.AppRunner(app); await runner.setup(); port=int(os.environ.get("PORT","8080")); await web.TCPSite(runner,"0.0.0.0",port).start()
    log.info("Web server started on port %s",port)

async def save_storage(message):
    try:
        saved=await client.forward_messages(STORAGE_CHANNEL_ID,message)
        sid=saved[0].id if isinstance(saved,list) else saved.id
        STATS["storage_saved"]+=1; log.info("Stored media | %s",sid); return sid
    except Exception:
        STATS["storage_failed"]+=1; log.exception("Storage save failed"); return None

async def publish(dest,message,caption):
    try:
        await client.send_file(dest,file=message,caption=caption,parse_mode="html",link_preview=False)
        return True
    except FloodWaitError as e:
        log.warning("FloodWait %ss | %s",e.seconds,dest); await asyncio.sleep(e.seconds+5); return False
    except Exception:
        STATS["send_failed"]+=1; log.exception("Publish failed | %s",dest); return False

def caption(sid,title,kind,prompt):
    url=f"{PUBLIC_BASE_URL}/download/{sid}?title={quote(title)}&type={quote(kind)}&prompt={quote(prompt)}"
    return f"🎨 <b>{html_escape(title)}</b>\n\n🎬 <b>Type:</b> {html_escape(kind)}\n📝 <b>Prompt:</b>\n{html_escape(prompt or 'Visual prompt')}\n\n⬇️ <b><a href=\"{url}\">Get Original {html_escape(kind)}</a></b>\n\n✨ <b>VisualPrompt AI</b>"

@client.on(events.NewMessage())
async def handler(event):
    global ME_ID
    try:
        if event.is_private:
            sender=await event.get_sender()
            if sender and sender.id==ME_ID:
                cmd=(event.text or "").strip().lower()
                if cmd=="/alive":
                    await event.reply(f"✅ <b>Online</b>\\n📥 Queue: {len(QUEUE)}\\n📤 Sent: {STATS['sent']}\\n🚫 Duplicates: {STATS['duplicates']}\\n💾 Storage: {STATS['storage_saved']}",parse_mode="html"); return
                if cmd=="/stats":
                    await event.reply(f"📊 <b>VisualPrompt AI</b>\\n\\n📤 Sent: {STATS['sent']}\\n📥 Queued: {STATS['queued']}\\n🚫 Duplicates: {STATS['duplicates']}\\n💾 Storage: {STATS['storage_saved']}\\n❌ Storage Failed: {STATS['storage_failed']}\\n📷 Photos: {STATS['photos']}\\n🎬 Videos: {STATS['videos']}\\n🗃️ Queue: {len(QUEUE)}",parse_mode="html"); return
        kind=media_kind(event.message)
        if not kind or not await allowed(event): return
        prompt=clean_prompt(event.message.text or event.message.message or "")
        if blocked(prompt): log.info("Blocked promotional post | %s",event.id); return
        k=key(event)
        if k in SEEN or k in PUBLISHED: STATS["duplicates"]+=1; return
        first=prompt.splitlines()[0].strip() if prompt else ""
        title=first[:80] if first else ("AI Photo Prompt" if kind=="Photo" else "AI Video Prompt")
        QUEUE.append({"message":event.message,"prompt":prompt,"kind":kind,"title":title,"key":k}); SEEN.add(k); STATS["queued"]+=1
        log.info("Queued %s | %s | queue=%s",kind,title,len(QUEUE))
    except Exception: log.exception("Event handler failed")

async def worker():
    while True:
        if not QUEUE: await asyncio.sleep(5); continue
        item=QUEUE.pop(0)
        try:
            sid=await save_storage(item["message"])
            if not sid: continue
            cap=caption(sid,item["title"],item["kind"],item["prompt"])
            success=0
            for dest in DEST_CHANNELS:
                if await publish(dest,item["message"],cap):
                    success+=1; STATS["sent"]+=1
                    STATS["photos" if item["kind"]=="Photo" else "videos"]+=1
                await asyncio.sleep(CHANNEL_DELAY_SECONDS)
            if success: PUBLISHED.add(item["key"])
            await asyncio.sleep(POST_INTERVAL_SECONDS)
        except Exception:
            log.exception("Worker error"); await asyncio.sleep(10)

async def main():
    global ME_ID
    await start_web()
    await client.connect()
    if not await client.is_user_authorized(): raise RuntimeError("Invalid SESSION_STRING")
    me=await client.get_me(); ME_ID=me.id
    log.info("VisualPrompt AI started | user=%s | storage=%s | bot=@%s",ME_ID,STORAGE_CHANNEL_ID,DOWNLOAD_BOT_USERNAME)
    log.info("Destinations: %s",DEST_CHANNELS)
    log.info("Sources: %s",SOURCE_CHANNELS or "all accessible chats except ignored")
    asyncio.create_task(worker())
    try: await client.run_until_disconnected()
    finally: await client.disconnect()

if __name__=="__main__": asyncio.run(main())
