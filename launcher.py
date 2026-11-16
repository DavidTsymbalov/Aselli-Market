"""Настройка и запуск локального бота без редактирования кода."""

import fcntl
import getpass
import os
from pathlib import Path
import re
import sys

import app

WEBAPP_URL = "https://davidtsymbalov.github.io/Aselli-Market/"


def prepare_config(root, prompt=getpass.getpass):
    path = Path(root) / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values = {}
    for line in lines:
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    token = os.environ.get("BOT_TOKEN", "").strip() or values.get("BOT_TOKEN", "")
    if not token:
        token = prompt("Вставьте токен из BotFather (ввод скрыт): ").strip()
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        raise ValueError("Токен должен иметь формат число:секрет. Значение не сохранено.")
    changes = {}
    if not os.environ.get("BOT_TOKEN", "").strip() and not values.get("BOT_TOKEN"):
        changes["BOT_TOKEN"] = token
    if not values.get("WEBAPP_URL") and not os.environ.get("WEBAPP_URL", "").strip():
        changes["WEBAPP_URL"] = WEBAPP_URL
    for key, value in changes.items():
        indices = [i for i, line in enumerate(lines) if line.split("=", 1)[0].strip() == key]
        if indices:
            for index in indices:
                lines[index] = f"{key}={value}"
        else:
            lines.append(f"{key}={value}")
    if changes:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
        path.chmod(0o600)


def main():
    os.chdir(app.ROOT)
    data = app.ROOT / "data"
    data.mkdir(exist_ok=True)
    with (data / "bot.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Бот уже запущен через start.command. Второй экземпляр не нужен.")
            return
        prepare_config(app.ROOT)
        print("Aselli Market · локальный запуск", flush=True)
        print("Оставьте окно открытым. Для остановки нажмите Ctrl+C.", flush=True)
        sys.argv = [str(app.ROOT / "app.py"), "--bot-only"]
        app.main()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, EOFError) as error:
        print(error)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("\nБот остановлен.")
