#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

fail() {
  echo "$1"
  read -r -p "Нажмите Enter, чтобы закрыть окно..." _unused
  exit 1
}

command -v python3 >/dev/null 2>&1 || fail "Установите Python 3.11+ с python.org, затем откройте этот файл снова."
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || fail "Нужен Python 3.11 или новее."

if [ ! -x .venv/bin/python ]; then
  echo "Подготавливаю окружение Aselli Market..."
  python3 -m venv .venv || fail "Не удалось создать окружение Python."
fi

if ! .venv/bin/python -c 'import certifi' 2>/dev/null; then
  echo "Устанавливаю доверенные сертификаты..."
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt || fail "Не удалось установить сертификаты. Проверьте интернет и повторите запуск."
fi

.venv/bin/python launcher.py || fail "Бот остановлен. Причина указана выше."
