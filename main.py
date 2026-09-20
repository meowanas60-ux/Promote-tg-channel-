import os
import sqlite3

from flask import Flask, jsonify, request, render_template

from bot import handle_update


app = Flask(__name__)

DB_PATH = os.getenv("DB_PATH", "apps.db")

BOT_USERNAME = os.getenv(
    "BOT_USERNAME",
    "BomssssssssBot"
).lstrip("@")


def init_db():

    conn = sqlite3.connect(DB_PATH)

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

    conn.commit()
    conn.close()


# IMPORTANT:
# Render uses gunicorn main:app.
# Therefore the database must be initialized when this module is imported.
init_db()


@app.get("/api/health")
def health():

    return jsonify(
        ok=True,
        service="gets-mods-render"
    )


@app.get("/api/apps")
def apps():

    q = request.args.get(
        "q",
        ""
    ).strip()

    try:

        limit = min(
            int(
                request.args.get(
                    "limit",
                    "30"
                )
            ),
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


    result = []


    for row in rows:

        item = dict(row)

        message_id = row[
            "telegram_message_id"
        ]

        item["download_url"] = (
            f"https://t.me/"
            f"{BOT_USERNAME}"
            f"?start={message_id}"
        )

        result.append(item)


    return jsonify(
        ok=True,
        apps=result
    )


@app.get("/api/apps/<int:message_id>")
def app_details(message_id):

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    row = conn.execute(
        """
        SELECT *
        FROM apps
        WHERE telegram_message_id = ?
        """,
        (message_id,)
    ).fetchone()

    conn.close()


    if not row:

        return jsonify(
            ok=False,
            error="App not found"
        ), 404


    item = dict(row)

    item["download_url"] = (
        f"https://t.me/"
        f"{BOT_USERNAME}"
        f"?start={message_id}"
    )


    return jsonify(
        ok=True,
        app=item
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

        return jsonify(
            ok=True
        )


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


@app.get("/app/<int:message_id>")
def app_page(message_id):

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
