"""
test_deployment.py — раздача на компьютеры кадровиков: данные отдельно от программы.
Запуск: pytest test_deployment.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

import app_env

ROOT = Path(__file__).resolve().parents[1]      # корень проекта


# --- где лежат данные ----------------------------------------------------------------
def test_dev_run_keeps_data_in_project_root(monkeypatch):
    monkeypatch.delenv(app_env.DATA_DIR_ENV_VAR, raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert app_env.app_dir().name == "src"
    assert app_env.data_dir() == ROOT                      # .env и правки — в корне, не в src/


def test_dev_run_without_src_folder_keeps_data_next_to_code(monkeypatch, tmp_path):
    monkeypatch.delenv(app_env.DATA_DIR_ENV_VAR, raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(app_env, "app_dir", lambda: tmp_path / "flat")
    assert app_env.data_dir() == tmp_path / "flat"


def test_frozen_app_keeps_data_in_appdata_not_in_program_folder(monkeypatch, tmp_path):
    monkeypatch.delenv(app_env.DATA_DIR_ENV_VAR, raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "local" / "app" / "InsalubrityHistory.exe"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    data = app_env.data_dir()
    assert data == tmp_path / "roaming" / "InsalubrityHistory"
    program = app_env.app_dir()
    assert program not in data.parents and data not in program.parents    # обновление программы не заденет данные


def test_env_var_overrides_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv(app_env.DATA_DIR_ENV_VAR, str(tmp_path / "custom"))
    assert app_env.data_dir() == tmp_path / "custom"


# --- перенос прежних настроек ------------------------------------------------------------
@pytest.fixture
def split_dirs(monkeypatch, tmp_path):
    program, data = tmp_path / "program", tmp_path / "data"
    program.mkdir()
    monkeypatch.setattr(app_env, "app_dir", lambda: program)
    monkeypatch.setattr(app_env, "data_dir", lambda: data)
    return program, data


def test_migration_copies_old_files_and_keeps_originals(split_dirs):
    program, data = split_dirs
    (program / ".env").write_text("OUT_DIR=x\n", encoding="utf-8")
    (program / "month_overrides.json").write_text('{"1": {}}', encoding="utf-8")
    (program / "backups").mkdir()
    (program / "backups" / "month_overrides_20260101.json").write_text("{}", encoding="utf-8")
    copied = app_env.migrate_legacy_data()
    assert sorted(copied) == [".env", "backups/", "month_overrides.json"]
    assert (data / ".env").read_text(encoding="utf-8") == "OUT_DIR=x\n"
    assert (data / "backups" / "month_overrides_20260101.json").exists()
    assert (program / ".env").exists() and (program / "month_overrides.json").exists()   # оригиналы целы


def test_migration_never_overwrites_existing_user_data(split_dirs):
    program, data = split_dirs
    data.mkdir()
    (data / "month_overrides.json").write_text('{"new": 1}', encoding="utf-8")
    (program / "month_overrides.json").write_text('{"old": 1}', encoding="utf-8")
    assert app_env.migrate_legacy_data() == []
    assert (data / "month_overrides.json").read_text(encoding="utf-8") == '{"new": 1}'


def test_migration_is_idempotent_and_safe_when_nothing_to_copy(split_dirs):
    program, data = split_dirs
    assert app_env.migrate_legacy_data() == []
    (program / ".env").write_text("A=1\n", encoding="utf-8")
    assert app_env.migrate_legacy_data() == [".env"]
    assert app_env.migrate_legacy_data() == []


def test_migration_noop_when_data_dir_is_program_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(app_env, "app_dir", lambda: tmp_path)
    monkeypatch.setattr(app_env, "data_dir", lambda: tmp_path)
    (tmp_path / ".env").write_text("A=1\n", encoding="utf-8")
    assert app_env.migrate_legacy_data() == []


def test_crash_log_directory_is_created(monkeypatch, tmp_path):
    log = tmp_path / "not" / "yet" / "crash.log"
    monkeypatch.setattr(app_env, "CRASH_LOG_PATH", log)
    old_hook = sys.excepthook
    try:
        app_env.install_excepthook("t")
        try:
            raise RuntimeError("x-crash")
        except RuntimeError:
            import threading
            exc = sys.exc_info()
            threading.excepthook(threading.ExceptHookArgs((exc[0], exc[1], exc[2], None)))
        assert "x-crash" in log.read_text(encoding="utf-8")
    finally:
        sys.excepthook = old_hook


# --- версия и сборка -------------------------------------------------------------------------
def test_version_is_semver_like():
    from version import __version__
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_spec_has_upx_disabled_for_win7():
    spec = (ROOT / "packaging" / "InsalubrityHistory.spec").read_text(encoding="utf-8")
    assert "upx=True" not in spec and spec.count("upx=False") == 2


# --- гигиена скриптов (запустить их на Linux нельзя, но типичные поломки ловим) ----------
SCRIPTS = ["scripts/build.bat", "scripts/publish.bat", "deploy/install.bat"]


@pytest.mark.parametrize("name", SCRIPTS)
def test_batch_files_are_ascii_crlf_and_balanced(name):
    raw = (ROOT / name).read_bytes()
    text = raw.decode("ascii")                                  # без кириллицы: не зависит от кодовой страницы
    assert text.count("\r\n") == text.count("\n") and b"\r\r" not in raw    # только CRLF
    code = "\n".join(l for l in text.splitlines() if not l.strip().lower().startswith("rem "))
    assert code.count("(") == code.count(")")
    assert "\t" not in text


def test_launcher_code_never_touches_user_data():
    text = (ROOT / "launcher" / "updater.py").read_text(encoding="utf-8")
    # папку данных пользователя запускатель не знает: переменные окружения не читает вообще
    assert "os.environ" not in text and "getenv" not in text and "expandvars" not in text
    assert '"app.new"' in text and '"app.old"' in text                       # обновление через временную папку


def test_installer_uses_per_user_folder_and_server_txt():
    text = (ROOT / "deploy/install.bat").read_text(encoding="ascii")
    assert "%LOCALAPPDATA%" in text and "server.txt" in text and "ProgramFiles" not in text   # права админа не нужны
    assert "InsalubrityHistoryLauncher.exe" in text and ".cmd" not in text


def test_publish_uses_staging_and_refuses_same_version():
    text = (ROOT / "scripts" / "publish.bat").read_text(encoding="ascii")
    assert "current.new" in text and "current.old" in text
    assert 'if "%NEWVER%"=="%OLDVER%"' in text
    assert "InsalubrityHistoryLauncher.exe" in text                          # запускатель уходит на сервер вместе с установщиком


def test_build_runs_tests_before_pyinstaller_and_writes_version():
    text = (ROOT / "scripts" / "build.bat").read_text(encoding="ascii")
    assert text.index("pytest") < text.index("pyinstaller")
    assert "version.txt" in text
    assert "Launcher.spec" in text                                           # собирается и запускатель


def test_spec_excludes_pkg_resources_to_avoid_startup_crash():
    spec = (ROOT / "packaging" / "InsalubrityHistory.spec").read_text(encoding="utf-8")
    assert "excludes=['pkg_resources']" in spec


# --- структура проекта ----------------------------------------------------------------------
def test_project_layout_is_consistent():
    for rel in ("src/app_env.py", "src/history_reader.py", "src/insalubrity.py", "src/insalubrity_history.py",
                "src/version.py", "packaging/InsalubrityHistory.spec", "packaging/logo.ico",
                "scripts/build.bat", "scripts/publish.bat", "deploy/install.bat",
                "packaging/Launcher.spec", "launcher/launcher.py", "launcher/updater.py",
                "requirements-win7.txt", "pytest.ini"):
        assert (ROOT / rel).exists(), rel


def test_scripts_point_to_existing_paths():
    build = (ROOT / "scripts" / "build.bat").read_text(encoding="ascii")
    publish = (ROOT / "scripts" / "publish.bat").read_text(encoding="ascii")
    assert "packaging\\InsalubrityHistory.spec" in build
    assert 'robocopy "deploy"' in publish and (ROOT / "deploy").is_dir()
    assert 'cd /d "%~dp0.."' in build and 'cd /d "%~dp0.."' in publish        # работают из корня проекта
    assert "venv\\Scripts\\python.exe" in build                               # и venv, и .venv


def test_spec_builds_from_src_and_uses_packaged_icon():
    spec = (ROOT / "packaging" / "InsalubrityHistory.spec").read_text(encoding="utf-8")
    assert "SPECPATH" in spec and "'src'" in spec and "logo.ico" in spec


def test_launcher_spec_is_small_windowed_onefile():
    spec = (ROOT / "packaging" / "Launcher.spec").read_text(encoding="utf-8")
    assert "console=False" in spec and "upx=False" in spec
    assert "InsalubrityHistoryLauncher" in spec and "'PyQt5'" in spec         # Qt в запускатель не тянем
