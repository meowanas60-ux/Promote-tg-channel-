import os
import re
import sqlite3
import requests


BOT_TOKEN = os.getenv("BOT_TOKEN", "")

STORAGE_CHANNEL = os.getenv(
    "STORAGE_CHANNEL",
    "-1003976996787"
).strip()


def telegram_api(method, data):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not configured")

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/{method}"
    )

    response = requests.post(
        url,
        json=data,
        timeout=30
    )

    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            result.get(
                "description",
                "Telegram API error"
            )
        )

    return result["result"]


def parse_caption(caption=""):

    def get(label):
        match = re.search(
            rf"(?:^|\n)\s*{re.escape(label)}\s*:\s*(.+)",
            caption,
            re.IGNORECASE
        )

        return (
            match.group(1).strip()
            if match
            else ""
        )

    return {
        "name": (
            get("Name")
            or get("App Name")
        ),

        "version": get("Version"),

        "description": get("Description")
    }


def save_post(post, db_path):

    document = post.get("document")

    if not document:
        return False

    file_name = document.get(
        "file_name",
        ""
    )

    if not file_name.lower().endswith(".apk"):
        return False

    parsed = parse_caption(
        post.get("caption", "")
    )

    if not parsed["name"]:
        return False

    photos = post.get("photo") or []

    image_file_id = ""

    if photos:
        image_file_id = photos[-1].get(
            "file_id",
            ""
        )

    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS apps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            telegram_message_id
                INTEGER UNIQUE NOT NULL,

            name TEXT NOT NULL,

            version TEXT DEFAULT '',

            description TEXT DEFAULT '',

            image_file_id TEXT DEFAULT '',

            document_file_id TEXT DEFAULT '',

            document_name TEXT DEFAULT '',

            document_size INTEGER DEFAULT 0,

            created_at
                TEXT DEFAULT CURRENT_TIMESTAMP,

            updated_at
                TEXT DEFAULT CURRENT_TIMESTAMP
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

            name = excluded.name,

            version = excluded.version,

            description = excluded.description,

            image_file_id =
                excluded.image_file_id,

            document_file_id =
                excluded.document_file_id,

            document_name =
                excluded.document_name,

            document_size =
                excluded.document_size,

            updated_at =
                CURRENT_TIMESTAMP
    """, (

        post["message_id"],

        parsed["name"],

        parsed["version"],

        parsed["description"],

        image_file_id,

        document.get(
            "file_id",
            ""
        ),

        file_name,

        document.get(
            "file_size",
            0
        )
    ))

    conn.commit()
    conn.close()

    return True


def send_app_to_user(
    user_id,
    message_id,
    db_path
):

    conn = sqlite3.connect(db_path)

    conn.row_factory = sqlite3.Row

    app = conn.execute(
        """
        SELECT *
        FROM apps
        WHERE telegram_message_id = ?
        """,
        (message_id,)
    ).fetchone()

    conn.close()

    if not app:
        telegram_api(
            "sendMessage",
            {
                "chat_id": user_id,
                "text": (
                    "❌ App not found.\n\n"
                    "Please try again from the website."
                )
            }
        )

        return False

    caption = (
        f"📱 {app['name']}\n\n"
        f"📦 Version: "
        f"{app['version'] or 'Latest'}\n\n"
        f"📝 {app['description'] or 'No description'}"
    )

    # Send app photo first
    if app["image_file_id"]:

        telegram_api(
            "sendPhoto",
            {
                "chat_id": user_id,
                "photo": app["image_file_id"]
            }
        )

    # Send APK
    telegram_api(
        "sendDocument",
        {
            "chat_id": user_id,
            "document": app["document_file_id"],
            "caption": caption
        }
    )

    return True


def handle_update(update, db_path):

    # ------------------------------------------------
    # 1. New or edited channel post
    # ------------------------------------------------

    post = (
        update.get("channel_post")
        or update.get("edited_channel_post")
    )

    if post:

        chat = post.get(
            "chat",
            {}
        )

        actual_channel_id = str(
            chat.get("id", "")
        ).strip()

        if (
            STORAGE_CHANNEL
            and actual_channel_id
            != STORAGE_CHANNEL
        ):
            return False

        return save_post(
            post,
            db_path
        )


    # ------------------------------------------------
    # 2. User starts the Telegram bot
    # ------------------------------------------------

    message = update.get("message")

    if not message:
        return False

    text = (
        message.get("text")
        or ""
    ).strip()

    if not text.startswith("/start"):
        return False

    user_id = message["chat"]["id"]

    parts = text.split(
        maxsplit=1
    )

    if len(parts) != 2:
        telegram_api(
            "sendMessage",
            {
                "chat_id": user_id,
                "text": (
                    "👋 Welcome!\n\n"
                    "Please open an app "
                    "from the website."
                )
            }
        )

        return True

    try:
        message_id = int(
            parts[1]
        )

    except ValueError:

        telegram_api(
            "sendMessage",
            {
                "chat_id": user_id,
                "text": (
                    "❌ Invalid app link."
                )
            }
        )

        return True

    return send_app_to_user(
        user_id,
        message_id,
        db_path
    )
