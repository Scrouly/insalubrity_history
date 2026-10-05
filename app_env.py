"""
app_env.py
==========
Общие для всех приложений вещи, которым НЕ нужен PyQt5:

* чтение/запись .env (со СЛИЯНИЕМ — чужие ключи не стираются);
* атомарная запись файлов (сначала во временный файл, потом os.replace);
* глобальный обработчик необработанных исключений для GUI.

Вынесено из insalubrity_gui.py, чтобы скрипты (тесты, отчёты) не тянули
за собой весь PyQt5 только ради чтения настроек.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path

def app_dir() -> Path:
    """Папка программы: рядом с exe в собранном виде, иначе рядом с этим файлом.

    Раньше .env, JSON-файлы правок и crash.log считались от os.getcwd() — если
    приложение запустить ярлыком с другой рабочей папкой (или собранный .exe
    запущен через "Отправить" / другой ярлык), оно создавало пустые настройки и
    файлы правок в НОВОМ месте, а старые настройки и правки выглядели пропавшими.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ENV_FILE_PATH = app_dir() / ".env"
CRASH_LOG_PATH = app_dir() / "crash.log"

DEFAULT_ENV_CONFIG = {
    "DBF_DATA_DIR": "./dbf",
    "OUT_DIR": "./",
    "CALC_MONTH": "5",
    "CALC_YEAR": "2026",
    "STAVKA1": "0.29",
    "STAVKA2": "0.41",
    "STAVKA3": "0.58",
}

class EnvFileError(Exception):
    """.env нельзя прочитать или записать.

    Раньше при ошибке чтения save_env_vars() всё равно перезаписывал файл одними
    переданными ключами (стирая остальные, например LEAVE_DAYS_*), а ошибки
    записи уходили в print(), которого в оконной сборке не видно.
    """


ENV_HEADER = "# Настройки расчёта вредности (автоматическое сохранение)\n"


# ---------------------------------------------------------------------------
# Атомарная запись
# ---------------------------------------------------------------------------
def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Пишет файл так, что при сбое посреди записи остаётся либо старая
    версия целиком, либо новая целиком — но не обрубок."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------
def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def load_env_vars() -> dict[str, str]:
    config = DEFAULT_ENV_CONFIG.copy()

    if ENV_FILE_PATH.exists():
        try:
            config.update(_read_env_file(ENV_FILE_PATH))
        except Exception as exc:
            print(f"Ошибка чтения .env: {exc}")
    else:
        try:
            save_env_vars(config)
        except EnvFileError as exc:
            print(exc)  # первый запуск в папке без прав записи — работаем с умолчаниями

    return config


def save_env_vars(config: dict[str, str]) -> None:
    """Записывает ТОЛЬКО переданные ключи, сохраняя все остальные ключи,
    которые уже есть в .env (например LEAVE_DAYS_31/32/33 из окна истории).

    Раньше функция целиком перезаписывала файл переданным словарём — из-за
    этого калькулятор стирал настройки, принадлежащие другому приложению.

    При ошибке чтения/записи бросает EnvFileError (вызывающий код показывает её
    пользователю); при этом существующий .env остаётся нетронутым.
    """
    merged: dict[str, str] = {}
    if ENV_FILE_PATH.exists():
        try:
            merged.update(_read_env_file(ENV_FILE_PATH))
        except Exception as exc:
            # НЕ перезаписываем файл, который не смогли прочитать: иначе потеряем
            # все остальные ключи.
            raise EnvFileError(
                f"Не удалось прочитать {ENV_FILE_PATH}: {exc}\n"
                f"Файл НЕ был изменён — настройки не сохранены."
            ) from exc
    merged.update({k: str(v) for k, v in config.items()})

    text = ENV_HEADER + "".join(f"{k}={v}\n" for k, v in merged.items())
    try:
        atomic_write_text(ENV_FILE_PATH, text)
    except Exception as exc:
        raise EnvFileError(f"Не удалось записать {ENV_FILE_PATH}: {exc}") from exc


# ---------------------------------------------------------------------------
# Глобальный обработчик необработанных исключений
# ---------------------------------------------------------------------------


def install_excepthook(app_title: str = "Ошибка") -> None:
    """Ставит sys.excepthook: пишет трейсбек в crash.log рядом с программой и
    показывает диалог, вместо того чтобы PyQt5 молча закрыл окно (в сборке
    с console=False пользователь иначе вообще не увидит причину).

    Вызывать ПОСЛЕ создания QApplication.
    """
    in_handler = {"busy": False}

    def handle(exc_type, exc, tb, show_dialog=True):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            with open(CRASH_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} ===\n{text}")
        except Exception:
            pass
        try:
            sys.__stderr__ and sys.__stderr__.write(text)
        except Exception:
            pass

        if not show_dialog or in_handler["busy"]:
            return  # из фонового потока диалог показывать нельзя; ошибка внутри самого диалога — не зацикливаемся
        in_handler["busy"] = True
        try:
            from PyQt5.QtWidgets import QMessageBox

            box = QMessageBox()
            box.setIcon(QMessageBox.Critical)
            box.setWindowTitle(app_title)
            box.setText(f"Непредвиденная ошибка: {exc}")
            box.setInformativeText(f"Подробности записаны в файл:\n{CRASH_LOG_PATH}")
            box.setDetailedText(text)
            box.exec()
        except Exception:
            pass
        finally:
            in_handler["busy"] = False

    sys.excepthook = handle

    def handle_thread(args):
        handle(args.exc_type, args.exc_value, args.exc_traceback, show_dialog=False)

    threading.excepthook = handle_thread
