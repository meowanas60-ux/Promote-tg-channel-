import os
import re
import sqlite3

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_USERNAME = os.getenv(
    "STORAGE_CHANNEL_USERNAME", "sahatanas"
).lstrip("@")


def parse_caption(caption=""):
    def get(label):
        match = re.search(
            rf"(?:^|\n)\s*{re.escape(label)}\s*:\s*(.+)",
            caption,
            re.IGNORECASE
        )
        return match.group(1).strip() if match else ""

    return {
        "name": get("Name") or get("App Name"),
        "version": get("Version"),
        "description": get("Description")
    }


def save_post(post, db_path):
    document = post.get("document")

    if not document:
        return False

    file_name = document.get("file_name", "")

    if not file_name.lower().endswith(".apk"):
        return False

    parsed = parse_caption(post.get("caption", ""))

    if not parsed["name"]:
        return False

    photos = post.get("photo") or []

    image_file_id = (
        photos[-1].get("file_id", "")
        if photos else ""
    )

    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS apps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_message_id INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            version TEXT DEFAULT '',
            description TEXT DEFAULT '',
            image_file_id TEXT DEFAULT '',
            document_file_id TEXT DEFAULT '',
            document_name TEXT DEFAULT '',
            document_size INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        INSERT INTO apps (
            telegram_message_id,
            name,
            version,
            description,
            image_file_id,
            document_file_id,
            document_name,
            document_size
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(telegram_message_id)
        DO UPDATE SET
            name=excluded.name,
            version=excluded.version,
            description=excluded.description,
            image_file_id=excluded.image_file_id,
            document_file_id=excluded.document_file_id,
            document_name=excluded.document_name,
            document_size=excluded.document_size,
            updated_at=CURRENT_TIMESTAMP
    """, (
        post["message_id"],
        parsed["name"],
        parsed["version"],
        parsed["description"],
        image_file_id,
        document.get("file_id", ""),
        file_name,
        document.get("file_size", 0)
    ))

    conn.commit()
    conn.close()

    return True


def handle_update(update, db_path):
    post = (
        update.get("channel_post")
        or update.get("edited_channel_post")
    )

    if not post:
        return False

    chat = post.get("chat", {})

    username = (
        chat.get("username") or ""
    ).lstrip("@").lower()

    expected = CHANNEL_USERNAME.lower()

    if expected and username and username != expected:
        return False

    return save_post(post, db_path)
