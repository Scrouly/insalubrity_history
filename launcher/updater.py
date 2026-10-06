"""
updater.py — логика обновления локальной копии программы с сервера (без интерфейса).

Раскладка на компьютере кадровика (BASE — папка запускателя):
    BASE/InsalubrityHistoryLauncher.exe   запускатель (этот код)
    BASE/server.txt                       путь к папке на сервере (одна строка)
    BASE/app/                             локальная копия программы (обновляется)
    BASE/launcher.log                     журнал запускателя

На сервере:  <server>/current/  — актуальная сборка, в ней version.txt.

Данные пользователя (%APPDATA%\\InsalubrityHistory) запускатель не знает и не трогает.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

APP_EXE = "InsalubrityHistory.exe"
VERSION_FILE = "version.txt"
CHUNK = 1024 * 1024
LOG_LIMIT = 200_000

Progress = Callable[[int, int, str], None]      # (скопировано байт, всего байт, имя файла)


class UpdateError(Exception):
    """Понятная пользователю причина, по которой обновить/запустить не удалось."""


@dataclass
class UpdateInfo:
    source: Path                  # <server>/current
    server_version: str
    local_version: Optional[str]  # None — программа ещё не установлена


# ---------------------------------------------------------------------------
# Журнал
# ---------------------------------------------------------------------------
def write_log(base: Path, message: str) -> None:
    try:
        path = Path(base) / "launcher.log"
        if path.exists() and path.stat().st_size > LOG_LIMIT:
            tail = path.read_text(encoding="utf-8", errors="replace")[-LOG_LIMIT // 4:]
            path.write_text(tail, encoding="utf-8")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}\n")
    except OSError:
        pass  # журнал не должен мешать запуску


# ---------------------------------------------------------------------------
# Версии
# ---------------------------------------------------------------------------
def read_version(path: Path) -> Optional[str]:
    try:
        text = Path(path).read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    return text or None


def read_server_root(base: Path) -> Optional[Path]:
    try:
        line = (Path(base) / "server.txt").read_text(encoding="utf-8-sig").splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return Path(line) if line else None


def check_update(base: Path, exe_name: str = APP_EXE) -> Optional[UpdateInfo]:
    """Нужно ли обновление. None — нет (сервер не задан/недоступен, версии совпадают)."""
    base = Path(base)
    server = read_server_root(base)
    if server is None:
        return None
    source = server / "current"
    server_version = read_version(source / VERSION_FILE)       # недоступный сервер -> None
    if server_version is None:
        return None
    app = base / "app"
    local_version = read_version(app / VERSION_FILE)
    if local_version == server_version and (app / exe_name).exists():
        return None
    return UpdateInfo(source=source, server_version=server_version, local_version=local_version)


# ---------------------------------------------------------------------------
# Запущена ли программа
# ---------------------------------------------------------------------------
def is_app_running(exe_name: str = APP_EXE) -> bool:
    """Запущена ли программа (её файлы в этом случае заменить нельзя). Без окна консоли."""
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/NH"],
            capture_output=True, text=True, timeout=15,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return exe_name.lower() in (result.stdout or "").lower()


# ---------------------------------------------------------------------------
# Копирование с прогрессом
# ---------------------------------------------------------------------------
def _list_files(src: Path) -> list[tuple[Path, int]]:
    files = []
    for root, _dirs, names in os.walk(src):
        for name in names:
            p = Path(root) / name
            files.append((p, p.stat().st_size))
    return files


def copy_tree(src: Path, dst: Path, progress: Optional[Progress] = None) -> int:
    """Копирует каталог src в dst кусками по 1 МБ и сообщает ход копирования.
    Возвращает общий размер в байтах."""
    src, dst = Path(src), Path(dst)
    files = _list_files(src)
    total = sum(size for _, size in files)
    done = 0
    dst.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(0, total, "")
    for path, _size in files:
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "rb") as fin, open(target, "wb") as fout:
            while True:
                chunk = fin.read(CHUNK)
                if not chunk:
                    break
                fout.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total, str(rel))
        try:
            shutil.copystat(path, target)
        except OSError:
            pass
    if progress:
        progress(total, total, "")
    return total


def _rename_retry(src: Path, dst: Path, attempts: int = 6, delay: float = 0.5) -> None:
    """Переименование с повторами: антивирус/индексатор на Windows бывает кратко держит папку."""
    last: Optional[OSError] = None
    for attempt in range(attempts):
        try:
            os.rename(src, dst)
            return
        except OSError as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(delay)
    raise last  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Обновление
# ---------------------------------------------------------------------------
def apply_update(base: Path, info: UpdateInfo, progress: Optional[Progress] = None,
                 exe_name: str = APP_EXE) -> None:
    """Копирует новую сборку в BASE/app.new и только после полной проверки меняет её
    на BASE/app. При любой ошибке рабочая копия остаётся прежней."""
    base = Path(base)
    app, new, old = base / "app", base / "app.new", base / "app.old"

    shutil.rmtree(new, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)

    try:
        copy_tree(info.source, new, progress)
    except OSError as exc:
        shutil.rmtree(new, ignore_errors=True)
        raise UpdateError(f"Не удалось скопировать новую версию с сервера: {exc}") from exc

    if not (new / VERSION_FILE).exists() or not (new / exe_name).exists():
        shutil.rmtree(new, ignore_errors=True)
        raise UpdateError("Новая версия на сервере скопировалась не полностью (нет программы или version.txt)")

    had_old = app.exists()
    try:
        if had_old:
            _rename_retry(app, old)
        _rename_retry(new, app)
    except OSError as exc:
        # вернуть прежнюю рабочую копию
        if had_old and not app.exists() and old.exists():
            try:
                os.rename(old, app)
            except OSError:
                pass
        shutil.rmtree(new, ignore_errors=True)
        raise UpdateError(f"Не удалось заменить файлы программы (возможно, она открыта): {exc}") from exc

    shutil.rmtree(old, ignore_errors=True)


# ---------------------------------------------------------------------------
# Запуск программы
# ---------------------------------------------------------------------------
def launch_app(base: Path, exe_name: str = APP_EXE) -> None:
    app = Path(base) / "app"
    exe = app / exe_name
    if not exe.exists():
        raise UpdateError(f"Программа не найдена: {exe}")
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(exe)], cwd=str(app), close_fds=True, creationflags=flags)
