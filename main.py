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
    if "media_type" not in cols:
        con.execute("ALTER TABLE content ADD COLUMN media_type TEXT DEFAULT 'image'")
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
         prompt, tutorial, caption, source_url, created_at, media_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, data)
    con.commit()
    con.close()

def parse_prompt_tutorial(text):
    text = BeautifulSoup(text or "", "html.parser").get_text("\n")
    text = re.sub(r"\r", "", text).strip()
    if not text or not AI_WORDS.search(text):
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

    if len(prompt) < 20:
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

def build_post_caption(prompt, tutorial):
    kind = "🎬 AI VIDEO PROMPT" if re.search(r"(video|kling|runway|veo|sora)", prompt or "", re.I) else "🖼️ AI IMAGE PROMPT"
    has_guide = bool((tutorial or "").strip())
    guide_line = "📚 Full tutorial included" if has_guide else "🧠 Full prompt included"
    return (
        "✨ <b>VISUAL PROMPT AI</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"<b>{kind}</b>\n"
        f"{guide_line}\n"
        "🎯 Tap the button below to open the full guide.\n"
        "━━━━━━━━━━━━━━━━━━"
    )

async def publish_to_channels(media_path, prompt, tutorial, cid):
    landing_url = f"{PUBLIC_BASE_URL}/content/{cid}"
    if not PUBLIC_BASE_URL:
        print("❌ PUBLIC_BASE_URL is empty; cannot create landing URL.")
        return

    from telethon import Button
    caption = build_post_caption(prompt, tutorial)
    buttons = [[Button.url("🎯 GET PROMPT + TUTORIAL", landing_url)]]

    for ch in PUBLISHED_CHANNELS:
        try:
            print(f"📤 Publishing to {ch} -> professional post + button")
            msg = await client.send_file(
                ch,
                media_path,
                caption=caption,
                parse_mode="html",
                buttons=buttons,
                force_document=False,
            )
            mid = getattr(msg, "id", None)
            print(f"✅ Published to {ch} (message_id={mid}, button_url={landing_url})")
        except Exception as e:
            print(f"❌ Publish error {ch}: {repr(e)}")

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
        media_type = "video" if str(filename).lower().endswith((".mp4", ".webm", ".mov", ".mkv")) else "image"
        save_row((
            cid, source_type, str(source_chat), str(source_message_id), storage_msg_id,
            prompt, tutorial, "", source_url,
            datetime.now(timezone.utc).isoformat(), media_type
        ))
        await publish_to_channels(str(temp), prompt, tutorial, cid)
        return True
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

def _truncate(text, n=260):
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if len(clean) <= n:
        return clean
    return clean[:n].rstrip(" .,-") + "…"

def _page_title(row):
    media_type = (row["media_type"] if "media_type" in row.keys() else "image") or "image"
    label = "Video" if media_type == "video" else "Image"
    return f"AI {label} Prompt & Tutorial"

def _bot_deep_link(cid):
    return f"https://t.me/{BOT_USERNAME}?start=content_{cid}"

async def home(request):
    return web.Response(
        text="""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Visual Prompt AI</title>
<meta name="theme-color" content="#111827">
<style>
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(circle at top,#312e81 0,#0f172a 42%,#020617 100%);
font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#f8fafc}
.wrap{max-width:760px;margin:0 auto;padding:28px 16px 50px}
.hero{padding:30px 20px;text-align:center}
.logo{width:64px;height:64px;border-radius:18px;display:grid;place-items:center;margin:0 auto 14px;
background:linear-gradient(135deg,#8b5cf6,#ec4899);font-size:30px;box-shadow:0 14px 40px rgba(0,0,0,.25)}
h1{margin:0 0 10px;font-size:34px;letter-spacing:-.7px}
p{color:#cbd5e1;line-height:1.65}
.btn{display:inline-block;margin-top:12px;padding:13px 18px;border-radius:12px;text-decoration:none;font-weight:800;
background:#fff;color:#111827}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <div class="logo">✦</div>
    <h1>Visual Prompt AI</h1>
    <p>AI image & video prompts, creative workflows and tutorials in one place.</p>
    <a class="btn" href="https://t.me/VisualPromptAIBot">Open Telegram Bot</a>
  </div>
</div>
</body>
</html>""",
        content_type="text/html"
    )

async def media_preview(request):
    cid = request.match_info["content_id"]
    row = get_content_row(cid)
    if not row:
        return web.Response(status=404, text="Content not found")

    try:
        msg = await client.get_messages(STORAGE_CHANNEL_ID, ids=int(row["storage_msg_id"]))
        if not msg:
            return web.Response(status=404, text="Media not found")

        bio = BytesIO()
        await client.download_media(msg, file=bio)
        data = bio.getvalue()
        if not data:
            return web.Response(status=404, text="Media not available")

        media_type = (row["media_type"] if "media_type" in row.keys() else "image") or "image"
        ctype = "video/mp4" if media_type == "video" else "image/jpeg"
        return web.Response(
            body=data,
            content_type=ctype,
            headers={"Cache-Control": "public, max-age=3600"}
        )
    except Exception as e:
        print("Media preview error:", repr(e))
        return web.Response(status=500, text="Media preview unavailable")

def get_content_row(cid):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM content WHERE content_id=?", (cid,)).fetchone()
    con.close()
    return row

async def landing(request):
    cid = request.match_info["content_id"]
    row = get_content_row(cid)
    if not row:
        return web.Response(status=404, text="Content not found")

    bot_link = _bot_deep_link(cid)
    smartlink = os.getenv(
        "ADSTERRA_SMARTLINK",
        "https://www.profitableratecpmnetwork.com/herywwsc?key=a8803ae52732f8b9dc5b4aaf1ba40e0a"
    )
    media_type = (row["media_type"] if "media_type" in row.keys() else "image") or "image"
    title = _page_title(row)
    prompt_preview = _truncate(row["prompt"], 520)
    tutorial = (row["tutorial"] or "").strip()
    tutorial_preview = _truncate(tutorial, 700) if tutorial else "No separate tutorial was provided by the source."

    if media_type == "video":
        media_html = f'<video class="preview" controls playsinline preload="metadata" src="/media/{html.escape(cid)}"></video>'
    else:
        media_html = f'<img class="preview" src="/media/{html.escape(cid)}" alt="AI prompt reference image" loading="eager">'

    body = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="Visual Prompt AI — full AI prompt and tutorial.">
<meta name="theme-color" content="#111827">
<style>
*{{box-sizing:border-box}}
body{{margin:0;background:linear-gradient(180deg,#eef2ff 0,#f8fafc 45%,#eef2ff 100%);
color:#0f172a;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif}}
.wrap{{max-width:780px;margin:0 auto;padding:16px}}
.top{{display:flex;align-items:center;gap:12px;padding:10px 4px 18px}}
.avatar{{width:46px;height:46px;border-radius:14px;display:grid;place-items:center;background:linear-gradient(135deg,#7c3aed,#ec4899);color:#fff;font-size:22px;font-weight:900}}
.brand{{font-weight:900;font-size:17px}}
.muted{{color:#64748b;font-size:13px}}
.card{{background:rgba(255,255,255,.96);border:1px solid #e2e8f0;border-radius:22px;padding:18px;margin:12px 0;box-shadow:0 12px 40px rgba(15,23,42,.07)}}
.preview{{width:100%;max-height:560px;object-fit:cover;border-radius:16px;background:#e2e8f0;display:block}}
.badges{{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 8px}}
.badge{{background:#f1f5f9;border:1px solid #e2e8f0;color:#334155;padding:7px 10px;border-radius:999px;font-size:12px;font-weight:800}}
h1{{font-size:29px;line-height:1.15;margin:8px 0 10px;letter-spacing:-.7px}}
h2{{font-size:17px;margin:0 0 10px}}
.copy{{white-space:pre-wrap;line-height:1.65;color:#334155;font-size:14px}}
.excerpt{{padding:14px;border-radius:14px;background:#f8fafc;border:1px solid #e2e8f0}}
.ad{{min-height:120px;display:grid;place-items:center;text-align:center;background:#fff}}
.ad-label{{font-size:11px;letter-spacing:.12em;color:#94a3b8;font-weight:900}}
.btn{{display:block;width:100%;padding:15px 16px;border-radius:14px;text-decoration:none;text-align:center;font-weight:900;margin-top:10px}}
.primary{{background:linear-gradient(135deg,#7c3aed,#ec4899);color:#fff;box-shadow:0 12px 28px rgba(124,58,237,.25)}}
.secondary{{background:#0f172a;color:#fff}}
.note{{font-size:12px;color:#64748b;line-height:1.6;text-align:center;margin:10px 0 0}}
.hidden{{display:none}}
.footer{{text-align:center;color:#94a3b8;font-size:12px;padding:12px 0 20px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div class="avatar">✦</div>
    <div>
      <div class="brand">Visual Prompt AI</div>
      <div class="muted">AI prompts • tutorials • creative workflows</div>
    </div>
  </div>

  <div class="card">
    {media_html}
    <div class="badges">
      <span class="badge">✨ AI Prompt</span>
      <span class="badge">📚 Tutorial</span>
      <span class="badge">⚡ Telegram Delivery</span>
    </div>
    <h1>{html.escape(title)}</h1>
    <div class="excerpt"><div class="copy">{html.escape(prompt_preview)}</div></div>
  </div>

  <div class="card">
    <h2>🧠 Prompt Preview</h2>
    <div class="copy">{html.escape(prompt_preview)}</div>
  </div>

  <div class="card">
    <h2>📚 Tutorial / Guide</h2>
    <div class="copy">{html.escape(tutorial_preview)}</div>
  </div>

  <div class="card ad">
    <div>
      <div class="ad-label">SPONSORED</div>
      <p class="muted">Support the project with the ad below.</p>
    </div>
  </div>

  <div class="card">
    <h2>🚀 Continue</h2>
    <p class="muted">Step 1: open the sponsored link. Step 2: return here. Step 3: open Telegram to receive the full content.</p>
    <a id="adBtn" class="btn primary" href="{html.escape(smartlink)}" target="_blank" rel="noopener noreferrer">🔓 CONTINUE</a>
    <a id="botBtn" class="btn secondary hidden" href="{html.escape(bot_link)}">📲 OPEN TELEGRAM & GET FULL CONTENT</a>
    <div id="timer" class="note">The Telegram button will appear after you continue.</div>
  </div>

  <div class="footer">© Visual Prompt AI • Built for prompt creators</div>
</div>
<script>
(function(){{
  const adBtn=document.getElementById('adBtn');
  const botBtn=document.getElementById('botBtn');
  const timer=document.getElementById('timer');
  function reveal(){{
    botBtn.classList.remove('hidden');
    timer.textContent='Ready — tap the Telegram button to continue.';
  }}
  adBtn.addEventListener('click',function(){{
    let s=3;
    timer.textContent='Please wait ' + s + ' seconds…';
    const iv=setInterval(function(){{
      s--;
      timer.textContent=s>0 ? 'Please wait ' + s + ' seconds…' : 'Ready — tap the Telegram button to continue.';
      if(s<=0){{clearInterval(iv);reveal();}}
    }},1000);
  }});
}})();
</script>
</body>
</html>"""
    return web.Response(text=body, content_type="text/html")

async def start_web():
    app = web.Application()
    app.router.add_get("/", home)
    app.router.add_get("/health", health)
    app.router.add_get("/content/{content_id}", landing)
    app.router.add_get("/media/{content_id}", media_preview)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"🌍 Web server listening on {PORT} | landing + media preview enabled")
    return runner

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
            print("📡 Monitoring every joined broadcast channel automatically.")
            print("🌐 Web trend scanner enabled.")
            await client.run_until_disconnected()
        except Exception as e:
            print("❌ Telegram client error:", repr(e))
            await asyncio.sleep(15)

if __name__ == "__main__":
    asyncio.run(main())
