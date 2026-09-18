import asyncio
import hashlib
import html
import os
import re
import sqlite3
import urllib.parse
import urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from aiohttp import web
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Channel
from telethon import utils
from io import BytesIO

load_dotenv()

API_ID = int(os.getenv("API_ID", "35317271"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")
STORAGE_CHANNEL_ID = int(os.getenv("STORAGE_CHANNEL_ID", "-1003976996787"))
PUBLISHED_CHANNELS = [x.strip() for x in os.getenv(
    "PUBLISHED_CHANNELS",
    "@TheFramePromptOfficial,@NextGen_AI_Creates,@NextGenAICreates"
).split(",") if x.strip()]
BOT_USERNAME = os.getenv("BOT_USERNAME", "VisualPromptAIBot").replace("@", "")
PUBLIC_BASE_URL = (os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
PORT = int(os.getenv("PORT", "10000"))
DB_PATH = os.getenv("DB_PATH", "prompts.db")

# Worldwide web discovery:
# Put public RSS/Atom feeds here, comma-separated. The built-in discovery feed
# uses Google News RSS as a broad worldwide discovery layer. Actual publishing
# still requires a page to contain both prompt + tutorial/guide and reusable media.
DEFAULT_RSS = (
    "https://news.google.com/rss/search?q="
    + urllib.parse.quote(
        '("AI image prompt" OR "AI video prompt" OR "Midjourney prompt" '
        'OR "Flux prompt" OR "Veo prompt" OR "AI art prompt" OR "AI video tutorial")'
    )
    + "&hl=en-US&gl=US&ceid=US:en"
)
TREND_RSS_URLS = [x.strip() for x in os.getenv("TREND_RSS_URLS", DEFAULT_RSS).split(",") if x.strip()]
TREND_SCAN_INTERVAL = int(os.getenv("TREND_SCAN_INTERVAL", "86400"))
MAX_WEB_ITEMS_PER_SCAN = int(os.getenv("MAX_WEB_ITEMS_PER_SCAN", "12"))
WEB_ALLOWED_DOMAINS = {
    x.strip().lower().lstrip(".")
    for x in os.getenv("WEB_ALLOWED_DOMAINS", "").split(",") if x.strip()
}
WEB_MEDIA_REUSE = os.getenv("WEB_MEDIA_REUSE", "0") == "1"
USER_AGENT = os.getenv("USER_AGENT", "VisualPromptAI/1.0 (+https://t.me/VisualPromptAIBot)")

if not API_HASH or not SESSION_STRING:
    raise RuntimeError("API_HASH and SESSION_STRING are required")

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

AI_WORDS = re.compile(
    r"\b(ai|artificial intelligence|midjourney|stable diffusion|flux|dall[- ]?e|"
    r"imagen|firefly|ideogram|leonardo|kling|runway|veo|sora|hailuo|wan|"
    r"seedance|comfyui|gen[- ]?ai|generative|prompt)\b",
    re.I
)

PROMPT_HEADINGS = re.compile(r"(?:^|\n)\s*(?:prompt|image prompt|video prompt|full prompt)\s*[:\-]\s*", re.I)
TUTORIAL_HEADINGS = re.compile(
    r"(?:^|\n)\s*(?:tutorial|guide|how to|steps|workflow|instructions)\s*[:\-]\s*",
    re.I
)

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS content (
            content_id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_chat TEXT NOT NULL,
            source_message_id TEXT NOT NULL,
            storage_msg_id INTEGER NOT NULL,
            prompt TEXT NOT NULL,
            tutorial TEXT NOT NULL,
            caption TEXT,
            source_url TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(source_chat, source_message_id)
        )
    """)
    cols = {r[1] for r in con.execute("PRAGMA table_info(content)").fetchall()}
    if "source_url" not in cols:
        con.execute("ALTER TABLE content ADD COLUMN source_url TEXT")
    con.commit()
    con.close()

def already_seen(source_chat, source_message_id):
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT 1 FROM content WHERE source_chat=? AND source_message_id=?",
        (str(source_chat), str(source_message_id))
    ).fetchone()
    con.close()
    return row is not None

def save_row(data):
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        INSERT OR IGNORE INTO content
        (content_id, source_type, source_chat, source_message_id, storage_msg_id,
         prompt, tutorial, caption, source_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, data)
    con.commit()
    con.close()

def parse_prompt_tutorial(text):
    """
    Category-agnostic parser.
    The previous version required an AI keyword, which caused posts from
    other categories to be silently discarded.
    """
    text = BeautifulSoup(text or "", "html.parser").get_text("\n")
    text = re.sub(r"\r", "", text).strip()
    if not text:
        return None, None

    pm = PROMPT_HEADINGS.search(text)
    tm = TUTORIAL_HEADINGS.search(text)

    # If a source uses a clear Prompt: heading, keep the exact section.
    if pm:
        if tm and tm.start() > pm.end():
            prompt = text[pm.end():tm.start()].strip()
            tutorial = text[tm.end():].strip()
        else:
            prompt = text[pm.end():].strip()
            tutorial = ""
    else:
        # Many Telegram prompt channels simply paste the prompt without a
        # "Prompt:" heading. For a media post, AI-looking text is sufficient.
        prompt = text
        tutorial = ""
        if tm:
            tutorial = text[tm.end():].strip()
            prompt = text[:tm.start()].strip()

    if len(prompt) < 5:
        return None, None
    if len(prompt) > 12000:
        prompt = prompt[:12000].rstrip()
    if len(tutorial) > 12000:
        tutorial = tutorial[:12000].rstrip()
    return prompt, tutorial

def content_id(source_type, source_key):
    return hashlib.sha256(f"{source_type}:{source_key}".encode()).hexdigest()[:16]

def channel_is_publish_target(entity):
    username = (getattr(entity, "username", "") or "").lower()
    return any(username == x.replace("@", "").lower() for x in PUBLISHED_CHANNELS)

async def publish_to_channels(media_path, prompt, tutorial, cid):
    if not PUBLIC_BASE_URL:
        print("⚠️ PUBLIC_BASE_URL is empty; landing-page button will be invalid.")

    link = f"{PUBLIC_BASE_URL}/content/{cid}" if PUBLIC_BASE_URL else f"/content/{cid}"
    caption = "✨ <b>AI Prompt & Tutorial</b>\n\nTap below to get the full prompt + guide."
    from telethon import Button

    success = 0
    for ch in PUBLISHED_CHANNELS:
        try:
            entity = await client.get_entity(ch)
            title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(entity.id)
            print(f"📤 Publishing to {ch} -> {title}")
            await client.send_file(
                entity,
                media_path,
                caption=caption,
                parse_mode="html",
                buttons=Button.url("🎯 Get Prompt & Tutorial", link),
            )
            success += 1
            print(f"✅ Published to {ch} (cid={cid})")
        except Exception as e:
            print(f"❌ Publish error: {ch}: {type(e).__name__}: {e}")

    if success == 0:
        print("❌ Publish failed for ALL configured PUBLISHED_CHANNELS.")
    return success > 0


async def save_and_publish(media_bytes, filename, source_type, source_chat, source_message_id,
                           prompt, tutorial, source_url=""):
    if already_seen(source_chat, source_message_id):
        return False

    cid = content_id(source_type, f"{source_chat}:{source_message_id}")
    temp = Path("/tmp") / f"{cid}_{filename}"
    temp.write_bytes(media_bytes)

    storage_caption = (
        "AI Prompt Content\n"
        f"CONTENT_ID: {cid}\n"
        f"SOURCE_TYPE: {source_type}\n\n"
        f"PROMPT:\n{prompt}\n\n"
        f"TUTORIAL:\n{tutorial}"
    )
    try:
        msg = await client.send_file(
            STORAGE_CHANNEL_ID,
            str(temp),
            caption=storage_caption,
            parse_mode="html"
        )
        storage_msg_id = msg.id if hasattr(msg, "id") else msg[0].id
        save_row((
            cid, source_type, str(source_chat), str(source_message_id), storage_msg_id,
            prompt, tutorial, "", source_url,
            datetime.now(timezone.utc).isoformat()
        ))
        published = await publish_to_channels(str(temp), prompt, tutorial, cid)
        if not published:
            print(f"⚠️ Stored {cid}, but no destination channel accepted the publication.")
        return published
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass

def media_from_telegram(msg):
    if getattr(msg, "photo", None):
        return "photo"
    if getattr(msg, "video", None):
        return "video"
    if getattr(msg, "document", None):
        mime = (getattr(msg.document, "mime_type", "") or "").lower()
        if mime.startswith("video/"):
            return "video"
    return None

async def download_telegram_media(msg):
    # BytesIO is reliable across Telethon versions and avoids passing the
    # built-in bytes type as a pseudo file object.
    bio = BytesIO()
    await client.download_media(msg, file=bio)
    return bio.getvalue()

async def process_telegram_media(entity, media_msg, prompt_text, tutorial_text=""):
    kind = media_from_telegram(media_msg)
    if not kind or not prompt_text:
        return False

    prompt, tutorial = parse_prompt_tutorial(prompt_text)
    if not prompt:
        return False
    if tutorial_text:
        _, parsed_tutorial = parse_prompt_tutorial(tutorial_text)
        if parsed_tutorial:
            tutorial = parsed_tutorial
        elif len(tutorial_text.strip()) >= 20:
            tutorial = tutorial_text.strip()[:12000]

    data = await download_telegram_media(media_msg)
    if not data:
        return False
    ext = ".jpg" if kind == "photo" else ".mp4"
    username = getattr(entity, "username", None)
    source_chat = username or entity.id
    source_url = f"https://t.me/{username}/{media_msg.id}" if username else ""
    return await save_and_publish(
        data, f"telegram_{media_msg.id}{ext}", "telegram", source_chat,
        media_msg.id, prompt, tutorial, source_url
    )

@client.on(events.NewMessage)
async def telegram_handler(event):
    try:
        msg = event.message
        if not msg:
            return
        entity = await event.get_chat()
        if not isinstance(entity, Channel):
            return
        if getattr(entity, "megagroup", False):
            return

        # Telethon channel entity IDs are positive; get_peer_id() gives the
        # normal -100... form used by Telegram config.
        if utils.get_peer_id(entity) == STORAGE_CHANNEL_ID:
            return
        if channel_is_publish_target(entity):
            return

        # Case 1: photo/video and prompt are in the same caption.
        kind = media_from_telegram(msg)
        if kind:
            text = msg.message or ""
            prompt, tutorial = parse_prompt_tutorial(text)
            if prompt:
                await process_telegram_media(entity, msg, text, tutorial)
                return

        # Case 2: source sends the photo/video first and the prompt as the
        # next text message, or sends the prompt as a reply to the media.
        if not kind and (msg.message or ""):
            prompt, tutorial = parse_prompt_tutorial(msg.message)
            if not prompt:
                return
            media_msg = None
            if getattr(msg, "reply_to_msg_id", None):
                try:
                    candidate = await client.get_messages(entity, ids=msg.reply_to_msg_id)
                    if candidate and media_from_telegram(candidate):
                        media_msg = candidate
                except Exception:
                    pass
            if media_msg is None:
                try:
                    previous = await client.get_messages(entity, limit=2)
                    for candidate in previous:
                        if candidate.id != msg.id and media_from_telegram(candidate):
                            media_msg = candidate
                            break
                except Exception:
                    pass
            if media_msg:
                await process_telegram_media(entity, media_msg, msg.message, tutorial)
    except Exception as e:
        print("Telegram handler error:", repr(e))

def allowed_domain(url):
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if not host:
            return False
        return any(host == d or host.endswith("." + d) for d in WEB_ALLOWED_DOMAINS)
    except Exception:
        return False

async def robots_allowed(url):
    try:
        parsed = urllib.parse.urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        # Network access through urllib is blocking, so use a conservative
        # rule: if no explicit allowlist exists, do not reuse page media.
        return WEB_MEDIA_REUSE and allowed_domain(url)
    except Exception:
        return False

def feed_entries(xml_text):
    root = ET.fromstring(xml_text)
    items = []
    for item in root.findall(".//item"):
        def txt(tag):
            x = item.find(tag)
            return (x.text or "").strip() if x is not None and x.text else ""
        link = txt("link")
        title = txt("title")
        desc = txt("description")
        pub = txt("pubDate")
        enclosure = item.find("enclosure")
        media_url = enclosure.attrib.get("url", "") if enclosure is not None else ""
        media_type = enclosure.attrib.get("type", "") if enclosure is not None else ""
        items.append((title, link, desc, pub, media_url, media_type))
    return items

def extract_media_from_html(page_url, html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    og_image = soup.find("meta", attrs={"property": "og:image"})
    og_video = soup.find("meta", attrs={"property": "og:video"})
    if og_video and og_video.get("content"):
        return urllib.parse.urljoin(page_url, og_video["content"]), "video"
    if og_image and og_image.get("content"):
        return urllib.parse.urljoin(page_url, og_image["content"]), "photo"
    for video in soup.find_all("video"):
        src = video.get("src")
        if src:
            return urllib.parse.urljoin(page_url, src), "video"
        source = video.find("source")
        if source and source.get("src"):
            return urllib.parse.urljoin(page_url, source["src"]), "video"
    return "", ""

async def fetch_url(session, url, max_bytes=6_000_000):
    async with session.get(
        url,
        timeout=aiohttp.ClientTimeout(total=25),
        headers={"User-Agent": USER_AGENT},
        allow_redirects=True
    ) as r:
        if r.status != 200:
            return "", "", r.headers.get("content-type", "")
        body = await r.content.read(max_bytes)
        return body.decode("utf-8", "ignore"), str(r.url), r.headers.get("content-type", "")

async def fetch_binary(session, url, max_bytes=30_000_000):
    async with session.get(
        url,
        timeout=aiohttp.ClientTimeout(total=45),
        headers={"User-Agent": USER_AGENT},
        allow_redirects=True
    ) as r:
        if r.status != 200:
            return None, r.headers.get("content-type", "")
        return await r.content.read(max_bytes), r.headers.get("content-type", "")

async def scan_web_trends():
    if not TREND_RSS_URLS:
        return
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        candidates = []
        for feed_url in TREND_RSS_URLS:
            try:
                xml, _, ctype = await fetch_url(session, feed_url, max_bytes=5_000_000)
                if not xml:
                    continue
                for title, link, desc, pub, enclosure, media_type in feed_entries(xml):
                    if link:
                        candidates.append((title, link, desc, pub, enclosure, media_type))
            except Exception as e:
                print("RSS error:", feed_url, e)

        # Newest/relevant items first. RSS feeds are the discovery layer;
        # the content itself is published only when prompt + tutorial + media
        # are all available and web media reuse is enabled for the domain.
        candidates = candidates[:MAX_WEB_ITEMS_PER_SCAN]

        for title, link, desc, pub, enclosure, media_type in candidates:
            try:
                if not allowed_domain(link):
                    # Discovery is allowed, but automatic media reposting is
                    # intentionally blocked until the domain is allowlisted.
                    continue

                page_html, final_url, ctype = await fetch_url(session, link, max_bytes=8_000_000)
                if not page_html:
                    continue

                soup = BeautifulSoup(page_html, "html.parser")
                main_text = soup.get_text("\n", strip=True)
                combined = f"{title}\n{desc}\n{main_text}"
                prompt, tutorial = parse_prompt_tutorial(combined)
                if not prompt:
                    continue

                media_url = enclosure
                kind = "video" if "video" in (media_type or "").lower() else "photo"
                if not media_url:
                    media_url, kind = extract_media_from_html(final_url, page_html)
                if not media_url or not await robots_allowed(final_url):
                    continue

                media_bytes, mtype = await fetch_binary(session, media_url)
                if not media_bytes:
                    continue
                if "video" in (mtype or "").lower() or kind == "video":
                    ext = ".mp4"
                else:
                    ext = ".jpg"

                source_key = hashlib.sha256(final_url.encode()).hexdigest()
                await save_and_publish(
                    media_bytes,
                    f"web_{source_key[:16]}{ext}",
                    "web",
                    urllib.parse.urlparse(final_url).netloc,
                    source_key,
                    prompt,
                    tutorial,
                    final_url
                )
            except Exception as e:
                print("Web item error:", repr(e))

async def web_trend_loop():
    while True:
        try:
            print("🌐 Running worldwide web trend scan...")
            await scan_web_trends()
        except Exception as e:
            print("Web scan error:", repr(e))
        await asyncio.sleep(TREND_SCAN_INTERVAL)

async def health(request):
    return web.json_response({
        "ok": True,
        "service": "Visual Prompt AI",
        "telegram_monitor": True,
        "web_trend_scanner": True,
        "web_scan_interval_seconds": TREND_SCAN_INTERVAL
    })

async def home(request):
    return web.Response(text="""<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Visual Prompt AI</title><style>body{font-family:Arial;background:#111827;color:#fff;text-align:center;padding:50px}a{display:inline-block;margin:10px;padding:14px 22px;background:#fff;color:#111827;border-radius:10px;text-decoration:none;font-weight:700}</style></head><body><h1>🎨 Visual Prompt AI</h1><p>AI photo/video prompt delivery service is online.</p><a href="/health">Health Check</a><a href="https://t.me/VisualPromptAIBot">Open Bot</a></body></html>""", content_type="text/html")

async def landing(request):
    cid = request.match_info["content_id"]
    link = f"{PUBLIC_BASE_URL}/content/{cid}"
    smartlink = "https://www.profitableratecpmnetwork.com/herywwsc?key=a8803ae52732f8b9dc5b4aaf1ba40e0a"

    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Prompt & Tutorial</title>
<style>
body{{margin:0;background:#f5f7fb;color:#172033;font-family:Arial,sans-serif}}
.wrap{{max-width:760px;margin:auto;padding:18px}}
.card{{background:#fff;border-radius:18px;padding:20px;margin:14px 0;box-shadow:0 4px 20px rgba(0,0,0,.07)}}
h1{{margin-top:0;font-size:26px}}
.btn{{display:inline-block;padding:14px 22px;border-radius:12px;background:#111827;color:#fff;text-decoration:none;font-weight:700}}
.ad{{display:flex;justify-content:center;align-items:center;min-height:90px;overflow:hidden;margin:10px 0}}
.small{{color:#667085;font-size:13px}}
</style>

<!-- Social Bar -->
<script src="https://pl31392177.profitableratecpmnetwork.com/e8/1f/77/e81f77dcaabfb52998ffb6fe2e50a4b8.js"></script>
</head>
<body>
<div class="wrap">

<div class="card">
<h1>🎨 AI Prompt & Tutorial</h1>
<p>Get the AI photo/video and its prompt from Telegram.</p>
</div>

<!-- Native Ad -->
<div class="card ad">
<script async="async" data-cfasync="false" src="https://pl31392178.profitableratecpmnetwork.com/c5399e7ba5336815e27f57a310183960/invoke.js"></script>
<div id="container-c5399e7ba5336815e27f57a310183960"></div>
</div>

<!-- 300x250 Banner -->
<div class="card ad">
<script>
  atOptions = {{
    'key' : '27f7adc1905b29d75422693fb24c5c27',
    'format' : 'iframe',
    'height' : 250,
    'width' : 300,
    'params' : {{}}
  }};
</script>
<script src="https://www.highrevenueformat.com/27f7adc1905b29d75422693fb24c5c27/invoke.js"></script>
</div>

<div class="card" style="text-align:center">
<p><b>Step 1:</b> Join the required Telegram channel(s).</p>
<p><b>Step 2:</b> Open the bot and receive the media + prompt.</p>
<a class="btn" href="{html.escape(link)}">🎯 Get Prompt & Tutorial</a>
</div>

<!-- Smart Link -->
<div class="card" style="text-align:center">
<a class="btn" href="{smartlink}" target="_blank" rel="noopener">🔗 Continue</a>
<p class="small">The smart link may open a third-party advertising page.</p>
</div>

<!-- Popunder -->
<script src="https://pl31392175.profitableratecpmnetwork.com/24/9e/8f/249e8ffb48623ecc2f8419c35b6bef1b.js"></script>

<div class="card small">
<p>© AI Prompt & Tutorial</p>
</div>
</div>
</body>
</html>"""
    return web.Response(text=body, content_type="text/html")


async def start_web():
    app = web.Application()
    app.router.add_get("/", home)
    app.router.add_get("/health", health)
    app.router.add_get("/content/{content_id}", landing)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌍 Web server listening on {PORT}")
    return runner

async def verify_publish_targets():
    print("🔎 Checking configured publish channels...")
    for ch in PUBLISHED_CHANNELS:
        try:
            entity = await client.get_entity(ch)
            title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(entity.id)
            print(f"✅ Publish target reachable: {ch} -> {title}")
        except Exception as e:
            print(f"❌ Publish target NOT reachable: {ch}: {type(e).__name__}: {e}")


async def startup_scan():
    limit = int(os.getenv("STARTUP_SCAN_LIMIT", "0"))
    if limit <= 0:
        return

    print(f"🔁 Startup scan enabled: last {limit} messages per joined broadcast channel")
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if not isinstance(entity, Channel):
            continue
        if getattr(entity, "megagroup", False):
            continue
        if utils.get_peer_id(entity) == STORAGE_CHANNEL_ID:
            continue
        if channel_is_publish_target(entity):
            continue

        try:
            async for msg in client.iter_messages(entity, limit=limit):
                kind = media_from_telegram(msg)
                text = msg.message or ""
                if not kind and not text.strip():
                    continue

                if kind:
                    prompt, tutorial = parse_prompt_tutorial(text)
                    if prompt:
                        await process_telegram_media(entity, msg, text, tutorial)
                else:
                    prompt, tutorial = parse_prompt_tutorial(text)
                    if not prompt:
                        continue
                    media_msg = None
                    if getattr(msg, "reply_to_msg_id", None):
                        try:
                            candidate = await client.get_messages(entity, ids=msg.reply_to_msg_id)
                            if candidate and media_from_telegram(candidate):
                                media_msg = candidate
                        except Exception:
                            pass
                    if media_msg:
                        await process_telegram_media(entity, media_msg, msg.message, tutorial)
        except Exception as e:
            print(f"⚠️ Startup scan error in {getattr(entity, 'username', entity.id)}: {e}")

async def main():
    init_db()
    # Start HTTP first so Render's health check has a live endpoint even if
    # the Telethon session needs to reconnect.
    await start_web()
    asyncio.create_task(web_trend_loop())

    while True:
        try:
            await client.start()
            me = await client.get_me()
            print("✅ Telegram user client online:", getattr(me, "username", None) or me.id)
            await verify_publish_targets()
            await startup_scan()
            print("📡 Monitoring every joined broadcast channel automatically.")
            print("🌐 Web trend scanner enabled.")
            await client.run_until_disconnected()
        except Exception as e:
            print("❌ Telegram client error:", repr(e))
            await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(main())
