"""
test_launcher.py — запускатель: проверка версий, копирование с прогрессом, безопасная замена.
Запуск: pytest tests/test_launcher.py -v
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import updater

EXE = updater.APP_EXE


def make_build(folder: Path, version: str, extra: dict | None = None, exe: bool = True) -> Path:
    """Фальшивая сборка программы: version.txt, «exe» и несколько файлов в подпапке."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / updater.VERSION_FILE).write_text(version + "\n", encoding="utf-8")
    if exe:
        (folder / EXE).write_text(f"exe {version}", encoding="utf-8")
    (folder / "lib").mkdir(exist_ok=True)
    (folder / "lib" / "a.dll").write_bytes(os.urandom(3 * 1024 * 1024 + 17))      # >1 МБ: несколько кусков
    (folder / "lib" / "b.dll").write_bytes(b"b" * 1000)
    for name, content in (extra or {}).items():
        (folder / name).write_text(content, encoding="utf-8")
    return folder


@pytest.fixture
def world(tmp_path):
    server = tmp_path / "server"
    base = tmp_path / "pc" / "InsalubrityHistory"
    base.mkdir(parents=True)
    (base / "server.txt").write_text(str(server) + "\n", encoding="utf-8")
    return base, server


# --- нужно ли обновление ---------------------------------------------------------------
def test_no_server_configured_means_no_update(tmp_path):
    assert updater.check_update(tmp_path) is None


def test_unreachable_server_means_no_update(world):
    base, _ = world
    assert updater.check_update(base) is None            # на сервере нет ничего (как при недоступной сети)


def test_same_version_means_no_update(world):
    base, server = world
    make_build(server / "current", "1.0.0")
    make_build(base / "app", "1.0.0")
    assert updater.check_update(base) is None


def test_different_version_needs_update(world):
    base, server = world
    make_build(server / "current", "1.0.1")
    make_build(base / "app", "1.0.0")
    info = updater.check_update(base)
    assert (info.server_version, info.local_version) == ("1.0.1", "1.0.0")


def test_downgrade_is_also_an_update_so_rollback_works(world):
    base, server = world
    make_build(server / "current", "1.0.0")
    make_build(base / "app", "1.0.1")
    assert updater.check_update(base).server_version == "1.0.0"


def test_first_install_has_no_local_version(world):
    base, server = world
    make_build(server / "current", "1.0.0")
    assert updater.check_update(base).local_version is None


def test_broken_local_copy_is_repaired_even_with_same_version(world):
    base, server = world
    make_build(server / "current", "1.0.0")
    make_build(base / "app", "1.0.0", exe=False)
    assert updater.check_update(base) is not None


# --- копирование с прогрессом -------------------------------------------------------------
def test_copy_reports_monotonic_progress_up_to_total(tmp_path):
    src = make_build(tmp_path / "src", "1")
    events = []
    total = updater.copy_tree(src, tmp_path / "dst", lambda d, t, n: events.append((d, t, n)))
    done = [e[0] for e in events]
    assert done == sorted(done) and done[0] == 0 and done[-1] == total
    assert all(e[1] == total for e in events)
    assert len(events) > 4                                                    # не один скачок 0 -> 100
    assert (tmp_path / "dst" / "lib" / "a.dll").read_bytes() == (src / "lib" / "a.dll").read_bytes()
    assert (tmp_path / "dst" / EXE).exists()


# --- замена ----------------------------------------------------------------------------------
def test_update_replaces_app_and_leaves_everything_else(world):
    base, server = world
    make_build(server / "current", "1.0.1")
    make_build(base / "app", "1.0.0", extra={"old_only.txt": "x"})
    (base / "launcher.log").write_text("log", encoding="utf-8")
    info = updater.check_update(base)
    updater.apply_update(base, info)
    assert updater.read_version(base / "app" / updater.VERSION_FILE) == "1.0.1"
    assert not (base / "app" / "old_only.txt").exists()                       # зеркало: лишнее старое удалено
    assert not (base / "app.new").exists() and not (base / "app.old").exists()
    assert (base / "server.txt").exists() and (base / "launcher.log").read_text(encoding="utf-8") == "log"
    assert updater.check_update(base) is None                                  # после обновления версии совпадают


def test_first_install_works_without_existing_app(world):
    base, server = world
    make_build(server / "current", "1.0.0")
    updater.apply_update(base, updater.check_update(base))
    assert (base / "app" / EXE).exists()


def test_copy_failure_keeps_old_version_and_cleans_staging(world, monkeypatch):
    base, server = world
    make_build(server / "current", "1.0.1")
    make_build(base / "app", "1.0.0")
    real = updater.copy_tree

    def broken(src, dst, progress=None):
        real(src, dst, progress)
        raise OSError("сеть пропала")

    monkeypatch.setattr(updater, "copy_tree", broken)
    with pytest.raises(updater.UpdateError):
        updater.apply_update(base, updater.check_update(base))
    assert updater.read_version(base / "app" / updater.VERSION_FILE) == "1.0.0"
    assert (base / "app" / EXE).read_text(encoding="utf-8") == "exe 1.0.0"
    assert not (base / "app.new").exists()


def test_incomplete_server_build_is_rejected(world):
    base, server = world
    make_build(server / "current", "1.0.1", exe=False)
    make_build(base / "app", "1.0.0")
    with pytest.raises(updater.UpdateError):
        updater.apply_update(base, updater.check_update(base))
    assert updater.read_version(base / "app" / updater.VERSION_FILE) == "1.0.0"
    assert not (base / "app.new").exists()


def test_swap_failure_restores_previous_app(world, monkeypatch):
    base, server = world
    make_build(server / "current", "1.0.1")
    make_build(base / "app", "1.0.0")
    calls = []
    real = updater._rename_retry

    def flaky(src, dst, *a, **k):
        calls.append((src.name, dst.name))
        if src.name == "app.new":                          # вторая замена не удалась (папку держит антивирус)
            raise PermissionError("занято")
        real(src, dst, *a, **k)

    monkeypatch.setattr(updater, "_rename_retry", flaky)
    with pytest.raises(updater.UpdateError):
        updater.apply_update(base, updater.check_update(base))
    assert (base / "app" / EXE).read_text(encoding="utf-8") == "exe 1.0.0"      # прежняя копия возвращена
    assert not (base / "app.new").exists() and not (base / "app.old").exists()


def test_leftovers_from_a_previous_crash_do_not_break_the_next_update(world):
    base, server = world
    make_build(server / "current", "1.0.1")
    make_build(base / "app", "1.0.0")
    make_build(base / "app.new", "0.0.1")                  # остаток прерванного обновления
    make_build(base / "app.old", "0.0.2")
    updater.apply_update(base, updater.check_update(base))
    assert updater.read_version(base / "app" / updater.VERSION_FILE) == "1.0.1"
    assert not (base / "app.new").exists() and not (base / "app.old").exists()


# --- запущена ли программа / запуск ----------------------------------------------------------
def test_running_check_parses_tasklist_without_console_window(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["flags"] = cmd, kw.get("creationflags")
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{EXE}   1234 Console   1   50 000 K\n", stderr="")

    monkeypatch.setattr(updater.os, "name", "nt")
    monkeypatch.setattr(updater.subprocess, "run", fake_run)
    assert updater.is_app_running() is True
    assert seen["cmd"][0] == "tasklist" and seen["flags"] == 0x08000000        # CREATE_NO_WINDOW: консоль не мелькает
    monkeypatch.setattr(updater.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="INFO: No tasks are running", stderr=""))
    assert updater.is_app_running() is False


def test_running_check_is_false_if_tasklist_fails(monkeypatch):
    monkeypatch.setattr(updater.os, "name", "nt")
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("нет tasklist")))
    assert updater.is_app_running() is False


def test_launch_without_exe_gives_clear_error(tmp_path):
    with pytest.raises(updater.UpdateError, match="не найдена"):
        updater.launch_app(tmp_path)


def test_log_is_written_and_capped(tmp_path):
    updater.write_log(tmp_path, "первая запись")
    assert "первая запись" in (tmp_path / "launcher.log").read_text(encoding="utf-8")
    (tmp_path / "launcher.log").write_text("x" * (updater.LOG_LIMIT + 10), encoding="utf-8")
    updater.write_log(tmp_path, "после усечения")
    text = (tmp_path / "launcher.log").read_text(encoding="utf-8")
    assert len(text) < updater.LOG_LIMIT and "после усечения" in text


# --- запускатель целиком, с настоящим окном tkinter (только где есть виртуальный экран) -----
@pytest.mark.skipif(not shutil.which("xvfb-run") or os.name == "nt", reason="нужен xvfb-run (Linux)")
def test_launcher_window_updates_and_starts_the_app_end_to_end(world, tmp_path):
    base, server = world
    marker = tmp_path / "started.txt"
    for folder, version in ((server / "current", "2.0.0"),):
        make_build(folder, version)
        (folder / EXE).write_text(f"#!/bin/sh\necho started-{version} > {marker}\n", encoding="utf-8")
        (folder / EXE).chmod(0o755)
    make_build(base / "app", "1.0.0")
    launcher = Path(__file__).resolve().parents[1] / "launcher" / "launcher.py"
    env = dict(os.environ)
    for var, folder in (("TCL_LIBRARY", "tcl8.6"), ("TK_LIBRARY", "tk8.6")):      # у «портативных» Python путь к Tcl бывает не прописан
        candidate = Path(sys.base_prefix) / "lib" / folder
        if var not in env and candidate.is_dir():
            env[var] = str(candidate)
    result = subprocess.run(["xvfb-run", "-a", sys.executable, str(launcher), "--base", str(base)],
                            capture_output=True, text=True, timeout=60, env=env)
    assert result.returncode == 0, result.stderr
    for _ in range(50):
        if marker.exists():
            break
        import time; time.sleep(0.1)
    assert marker.read_text(encoding="utf-8").strip() == "started-2.0.0"
    assert updater.read_version(base / "app" / updater.VERSION_FILE) == "2.0.0"
    log = (base / "launcher.log").read_text(encoding="utf-8")
    assert "1.0.0 -> 2.0.0" in log and "Обновлено до 2.0.0" in log
