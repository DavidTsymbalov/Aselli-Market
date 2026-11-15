"""Aselli Market 0.1. Python 3.11+, без сторонних зависимостей."""

import argparse
from contextlib import contextmanager
import json
import logging
import os
from pathlib import Path
import signal
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("aselli")
STOP = threading.Event()


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def get_webapp_url():
    # Render назначает HTTPS-адрес сам; явный URL позволяет подключить свой домен.
    return (os.environ.get("WEBAPP_URL", "").strip()
            or os.environ.get("RENDER_EXTERNAL_URL", "").strip())


@contextmanager
def connect_db(path):
    db = sqlite3.connect(path, timeout=10)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        with db:
            yield db
    finally:
        db.close()


def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect_db(path) as db:
        db.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))


class TelegramError(Exception):
    def __init__(self, code, retry_after=5):
        super().__init__(f"Telegram API: код {code}")
        self.code = code
        self.retry_after = retry_after


def telegram(token, method, payload):
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=40) as response:
            body = json.load(response)
    except HTTPError as error:
        try:
            body = json.loads(error.read())
        except (ValueError, OSError):
            body = {}
        raise TelegramError(error.code, body.get("parameters", {}).get("retry_after", 5)) from None
    except (URLError, TimeoutError, OSError):
        # Не выводим URL исключения: он содержит токен.
        raise TelegramError("network") from None
    if not body.get("ok"):
        raise TelegramError(body.get("error_code", "unknown"))
    return body["result"]


def handle_update(update, token, webapp_url, db_path):
    message = update.get("message", {})
    if message.get("chat", {}).get("type") != "private":
        return
    user = message.get("from", {})
    if not user or user.get("is_bot"):
        return
    with connect_db(db_path) as db:
        db.execute(
            """INSERT INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username,
            first_name=excluded.first_name, last_seen_at=CURRENT_TIMESTAMP""",
            (user["id"], user.get("username"), user.get("first_name", "")),
        )
    if not message.get("text"):
        return
    payload = {
        "chat_id": message["chat"]["id"],
        "text": "Привет! Это Aselli Market, бета 0.1.\nСкоро тут будут штуки 🙂",
    }
    if webapp_url:
        payload["reply_markup"] = {"inline_keyboard": [[{
            "text": "Открыть магазин",
            "web_app": {"url": webapp_url},
        }]]}
    telegram(token, "sendMessage", payload)


def poll(token, webapp_url, db_path):
    telegram(token, "getMe", {})
    info = telegram(token, "getWebhookInfo", {})
    if info.get("url"):
        raise RuntimeError("У бота уже установлен webhook. Отключите его перед запуском polling.")
    telegram(token, "setMyCommands", {"commands": [{"command": "start", "description": "Открыть Aselli Market"}]})
    if webapp_url:
        telegram(token, "setChatMenuButton", {"menu_button": {
            "type": "web_app", "text": "Магазин", "web_app": {"url": webapp_url},
        }})
    with connect_db(db_path) as db:
        row = db.execute("SELECT value FROM bot_state WHERE key='offset'").fetchone()
    offset = row[0] if row else 0
    LOG.info("Бот подключён. Ожидаем /start в личном чате.")
    while not STOP.is_set():
        try:
            updates = telegram(token, "getUpdates", {"offset": offset, "timeout": 25, "allowed_updates": ["message"]})
            for update in updates:
                if STOP.is_set():
                    break
                try:
                    handle_update(update, token, webapp_url, db_path)
                except TelegramError as error:
                    # Заблокировавший бота пользователь не должен останавливать очередь.
                    if error.code not in (400, 403):
                        raise
                    LOG.warning("Ответ пропущен: %s", error)
                offset = update["update_id"] + 1
                with connect_db(db_path) as db:
                    db.execute("INSERT INTO bot_state VALUES ('offset', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (offset,))
        except TelegramError as error:
            if error.code in (401, 404, 409):
                raise RuntimeError("Проверьте токен и убедитесь, что запущен только один экземпляр бота.") from None
            LOG.warning("%s; повторим запрос позже.", error)
            STOP.wait(max(1, error.retry_after))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = urlsplit(self.path).path
        if route in ("/", "/index.html"):
            body = (ROOT / "web/index.html").read_bytes()
            content_type = "text/html; charset=utf-8"
        elif route == "/health":
            body = b'{"status":"ok","version":"0.1.0"}'
            content_type = "application/json"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--web-only", action="store_true", help="Просмотр без подключения бота")
    mode.add_argument("--bot-only", action="store_true", help="Только бот, без HTTP-сервера")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    load_env()
    token = os.environ.get("BOT_TOKEN", "").strip()
    webapp_url = get_webapp_url()
    if not args.web_only:
        parsed = urlsplit(webapp_url)
        if not token:
            parser.error("Укажите BOT_TOKEN в .env.")
        if webapp_url and (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password):
            parser.error("WEBAPP_URL должен быть публичным HTTPS-адресом. Для запуска только бота оставьте его пустым.")
    db_path = os.environ.get("DATABASE_PATH", str(ROOT / "data/aselli.sqlite3"))
    init_db(db_path)
    server = None
    if args.web_only or (webapp_url and not args.bot_only):
        server = ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        LOG.info("Мини-приложение: http://localhost:%s", server.server_port)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: STOP.set())
    if not args.web_only and not webapp_url:
        LOG.info("Локальный режим: бот работает без мини-приложения. WEBAPP_URL можно добавить позже.")
    try:
        if args.web_only:
            STOP.wait()
        else:
            poll(token, webapp_url, db_path)
    except (TelegramError, RuntimeError) as error:
        LOG.error("%s", error)
        raise SystemExit(1) from None
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
