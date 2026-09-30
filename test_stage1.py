"""
test_stage1.py — тесты на правки этапа 1 (синтетика, реальные данные не нужны).
Запуск: pytest test_stage1.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import app_env
import history_reader as hr
import insalubrity


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    monkeypatch.setattr(app_env, "ENV_FILE_PATH", tmp_path / ".env")
    return tmp_path / ".env"


# 1.1 CRASH_LOG_PATH ----------------------------------------------------------
def test_crash_log_path_defined_and_excepthook_writes(tmp_path, monkeypatch):
    assert app_env.CRASH_LOG_PATH.name == "crash.log"
    monkeypatch.setattr(app_env, "CRASH_LOG_PATH", tmp_path / "crash.log")
    old_hook, old_thook = sys.excepthook, __import__("threading").excepthook
    try:
        app_env.install_excepthook("t")
        try:
            raise RuntimeError("boom-test")
        except RuntimeError:
            exc = sys.exc_info()
        # show_dialog=False путь (как из фонового потока) — без QApplication
        sys.excepthook.__closure__  # хук — замыкание handle
        import threading
        threading.excepthook(threading.ExceptHookArgs((exc[0], exc[1], exc[2], None)))
        text = (tmp_path / "crash.log").read_text(encoding="utf-8")
        assert "boom-test" in text
    finally:
        sys.excepthook, __import__("threading").excepthook = old_hook, old_thook


# 1.3 find_table без учёта регистра ------------------------------------------
@pytest.mark.parametrize("name", ["lschet.dbf", "LSCHET.DBF", "Lschet.Dbf", "LSCHET.dbf"])
def test_find_table_case_insensitive(tmp_path, name):
    (tmp_path / name).write_bytes(b"x")
    assert insalubrity.find_table(tmp_path, "lschet").name == name


def test_find_table_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        insalubrity.find_table(tmp_path, "lschet")


# 1.4 .env: не затирать нечитаемый файл, не глотать ошибки -----------------------
def test_save_env_merges_and_keeps_foreign_keys(env_file):
    env_file.write_text("LEAVE_DAYS_31=5\nOUT_DIR=a\n", encoding="utf-8")
    app_env.save_env_vars({"OUT_DIR": "b"})
    cfg = app_env._read_env_file(env_file)
    assert cfg == {"LEAVE_DAYS_31": "5", "OUT_DIR": "b"}


def test_save_env_refuses_to_overwrite_unreadable_file(env_file):
    original = b"LEAVE_DAYS_31=5\nBAD=\xff\xfe\xfa\n"  # невалидный UTF-8
    env_file.write_bytes(original)
    with pytest.raises(app_env.EnvFileError):
        app_env.save_env_vars({"OUT_DIR": "b"})
    assert env_file.read_bytes() == original  # файл не тронут


def test_save_env_write_failure_raises(env_file, monkeypatch):
    def boom(*a, **k):
        raise PermissionError("read-only")
    monkeypatch.setattr(app_env, "atomic_write_text", boom)
    with pytest.raises(app_env.EnvFileError):
        app_env.save_env_vars({"OUT_DIR": "b"})


def test_load_env_first_run_survives_unwritable_dir(env_file, monkeypatch):
    def boom(*a, **k):
        raise PermissionError("read-only")
    monkeypatch.setattr(app_env, "atomic_write_text", boom)
    cfg = app_env.load_env_vars()  # не должно падать
    assert cfg["STAVKA1"] == "0.29"


# 1.9 отброшенная ручная дата приёма ------------------------------------------
def test_describe_ignored_hire_override():
    d = hr.describe_ignored_hire_override
    assert d(1, {}) is None
    assert d(1, {"2": "2019-05-05"}) is None            # правка для другого tn
    assert d(1, {"1": "2019-05-05"}) is None            # валидная
    assert "не принята" in d(1, {"1": "1800-01-01"})    # слишком ранняя
    assert "не принята" in d(1, {"1": "2999-01-01"})    # в будущем
    assert "не принята" in d(1, {"1": "не дата"})       # мусор


def test_get_hire_date_contract_unchanged():
    emp = pd.DataFrame({"tn": [1], "fio": ["X"], "dnepr": [date(2015, 3, 2)], "data_uvl": [None]})
    assert hr.get_hire_date(1, emp, {"1": "1800-01-01"}) == (date(2015, 3, 2), "dnepr")


# 1.2 запятая в классе + 1.9 поле даты (нужен PyQt6, offscreen) -----------------
_QAPP = None  # держим ссылку: иначе QApplication уничтожается сборщиком мусора


def _qt():
    global _QAPP
    pytest.importorskip("PyQt6.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


def test_parse_class_accepts_comma():
    _qt()
    from insalubrity_history import HistoryWindow
    p = HistoryWindow._parse_editable_value
    assert p("bal_vredn", "3,1") == 3.1
    assert p("bal_vredn", "3.2") == 3.2
    with pytest.raises(ValueError):
        p("bal_vredn", "3,4")
    assert p("kol_rd", "22") == 22


def test_gui_env_debounce_and_close(tmp_path, monkeypatch):
    _qt()
    monkeypatch.setattr(app_env, "ENV_FILE_PATH", tmp_path / ".env")
    import insalubrity_gui as g
    monkeypatch.setattr(g, "save_env_vars", app_env.save_env_vars)
    calls = []
    real = app_env.save_env_vars
    monkeypatch.setattr(g, "save_env_vars", lambda c: (calls.append(c), real(c))[1])
    w = g.VrednMainWindow()
    calls.clear()
    for ch in "abc":
        w.data_dir_input.setText(w.data_dir_input.text() + ch)
    assert calls == []                       # на каждый символ больше не пишем
    assert w._env_timer.isActive()
    w.close()                                # при закрытии — сброс отложенной записи
    assert len(calls) == 1 and calls[0]["DBF_DATA_DIR"].endswith("abc")


def test_gui_refuses_close_while_worker_running(tmp_path, monkeypatch):
    _qt()
    monkeypatch.setattr(app_env, "ENV_FILE_PATH", tmp_path / ".env")
    import insalubrity_gui as g
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    w = g.VrednMainWindow()

    class Busy:
        def isRunning(self):
            return True
    w.worker = Busy()
    from PyQt6.QtGui import QCloseEvent
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert not ev.isAccepted()
