import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app


class BetaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "market.sqlite3")
        app.init_db(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def update(self, username="tester", chat_type="private"):
        return {"update_id": 1, "message": {
            "chat": {"id": 42, "type": chat_type}, "text": "/start",
            "from": {"id": 42, "first_name": "Тест", "username": username},
        }}

    def test_start_button_and_user_upsert(self):
        with patch.object(app, "telegram") as api:
            app.handle_update(self.update(), "test", "https://example.com", self.path)
            app.handle_update(self.update("updated"), "test", "https://example.com", self.path)
        payload = api.call_args.args[2]
        self.assertEqual(payload["chat_id"], 42)
        self.assertEqual(payload["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"], "https://example.com")
        with app.connect_db(self.path) as db:
            self.assertEqual(db.execute("SELECT telegram_id, username FROM users").fetchall(), [(42, "updated")])

    def test_groups_do_not_receive_web_app_buttons(self):
        with patch.object(app, "telegram") as api:
            app.handle_update(self.update(chat_type="group"), "test", "https://example.com", self.path)
            api.assert_not_called()

    def test_database_survives_reinitialization_and_enforces_constraints(self):
        with app.connect_db(self.path) as db:
            db.execute("INSERT INTO products (title, price_minor) VALUES ('Товар', 100)")
        app.init_db(self.path)
        with app.connect_db(self.path) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM products").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO products (title, price_minor) VALUES ('Товар', -1)")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("INSERT INTO orders (user_id) VALUES (999)")

    def test_web_routes_do_not_expose_secrets_or_database(self):
        # Выполняем настоящий HTTP-обработчик через транспорт в памяти.
        class Connection:
            def __init__(self, route):
                self.input = io.BytesIO(f"GET {route} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())
                self.output = bytearray()

            def makefile(self, *_args):
                return self.input

            def sendall(self, data):
                self.output.extend(data)

        def request(route):
            connection = Connection(route)
            app.Handler(connection, ("127.0.0.1", 1234), None)
            headers, body = bytes(connection.output).split(b"\r\n\r\n", 1)
            return int(headers.split()[1]), body.decode()

        status, html = request("/")
        self.assertEqual(status, 200)
        self.assertIn("Aselli Market — скоро тут будут штуки.", html)
        self.assertEqual(html.count("<p>"), 1)
        status, body = request("/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")
        for route in ("/.env", "/app.py", "/schema.sql", "/data/aselli.sqlite3", "/../.env"):
            self.assertEqual(request(route)[0], 404)

    def test_telegram_network_error_does_not_expose_token(self):
        with patch.object(app, "urlopen", side_effect=app.URLError("https://api.telegram.org/botSECRET")):
            with self.assertRaises(app.TelegramError) as error:
                app.telegram("SECRET", "getMe", {})
        self.assertNotIn("SECRET", str(error.exception))


if __name__ == "__main__":
    unittest.main()
