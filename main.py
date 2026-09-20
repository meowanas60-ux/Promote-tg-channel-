import os
import sqlite3

from flask import Flask, jsonify, request, render_template

from bot import handle_update


app = Flask(__name__)

DB_PATH = os.getenv("DB_PATH", "apps.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)

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

    conn.commit()
    conn.close()


@app.get("/api/health")
def health():
    return jsonify(
        ok=True,
        service="gets-mods-render"
    )


@app.get("/api/apps")
def apps():
    q = request.args.get("q", "").strip()

    try:
        limit = min(
            int(request.args.get("limit", "30")),
            100
        )
    except ValueError:
        limit = 30

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if q:
        rows = conn.execute(
            """
            SELECT *
            FROM apps
            WHERE name LIKE ?
               OR description LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (
                f"%{q}%",
                f"%{q}%",
                limit
            )
        ).fetchall()

    else:
        rows = conn.execute(
            """
            SELECT *
            FROM apps
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,)
        ).fetchall()

    conn.close()

    channel = os.getenv(
        "STORAGE_CHANNEL_USERNAME",
        "sahatanas"
    ).lstrip("@")

    result = []

    for row in rows:
        item = dict(row)

        item["download_url"] = (
            f"https://t.me/{channel}/"
            f"{row['telegram_message_id']}"
        )

        result.append(item)

    return jsonify(
        ok=True,
        apps=result
    )


@app.post("/webhook")
def webhook():
    update = request.get_json(
        silent=True
    ) or {}

    try:
        handle_update(
            update,
            DB_PATH
        )

        return jsonify(ok=True)

    except Exception as exc:
        app.logger.exception(
            "Webhook error"
        )

        return jsonify(
            ok=False,
            error=str(exc)
        ), 500


@app.get("/")
def index():
    return render_template(
        "index.html"
    )


@app.get("/<path:path>")
def fallback(path):
    return render_template(
        "index.html"
    )


if __name__ == "__main__":
    init_db()

    port = int(
        os.getenv(
            "PORT",
            "10000"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
