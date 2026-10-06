"""
test_ui_settings.py — настройки интерфейса: файл в папке данных, не реестр; тесты их не портят.
Запуск: pytest tests/test_ui_settings.py -v
"""
from __future__ import annotations

import os
import uuid

import pytest

import app_env

_QAPP = None


def _qt():
    global _QAPP
    pytest.importorskip("PyQt5.QtWidgets")
    from PyQt5.QtWidgets import QApplication
    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


@pytest.fixture
def hist(tmp_path, monkeypatch):
    """Окно «Истории» с пустыми данными и своей папкой данных (в ней и лежит ui_settings.ini)."""
    _qt()
    import pandas as pd
    from datetime import date
    from PyQt5.QtWidgets import QMessageBox
    monkeypatch.setenv(app_env.DATA_DIR_ENV_VAR, str(tmp_path))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(app_env, "ENV_FILE_PATH", tmp_path / ".env")
    (tmp_path / ".env").write_text(f"DBF_DATA_DIR={tmp_path}\nOUT_DIR={tmp_path}\n", encoding="utf-8")
    import insalubrity_history as h
    import history_reader as hr
    monkeypatch.setattr(h.hr, "build_history", lambda out_dir, log=print: hr.empty_history())
    monkeypatch.setattr(h.hr, "get_lschet_employees", lambda d: pd.DataFrame(
        {"tn": [7], "fio": ["ИВАНОВ"], "dnepr": [date(2015, 3, 2)], "data_uvl": [None]}))
    windows = []

    def make():
        w = h.HistoryWindow()
        windows.append(w)
        return w

    yield h, make
    for w in windows:
        w.wait_for_load()


def _registry_snapshot(h):
    reg = h.QSettings(h._REGISTRY_ORG, h._REGISTRY_APP)
    return {k: bytes(reg.value(k)) if hasattr(reg.value(k), "data") else reg.value(k) for k in reg.allKeys()}


def test_settings_live_in_a_file_in_the_data_folder(hist, tmp_path):
    h, make = hist
    w = make()
    w.resize(1234, 777)
    w.close()
    ini = tmp_path / h.UI_SETTINGS_FILE
    assert ini.exists() and "geometry" in ini.read_text(encoding="utf-8", errors="replace")


def test_closing_the_window_never_touches_the_real_registry_settings(hist):
    """Регрессия: прогон тестов (build.bat) затирал реальные настройки окна разработчика."""
    h, make = hist
    before = _registry_snapshot(h)
    w = make()
    w.resize(901, 555)
    w.close()
    w.top_toggle_btn.click()
    assert _registry_snapshot(h) == before


def test_window_size_and_columns_are_restored_next_time(hist):
    h, make = hist
    w1 = make()
    w1.resize(1111, 700)
    w1.table.setColumnWidth(2, 222)
    w1.close()
    w1.wait_for_load()
    w2 = make()
    assert (w2.width(), w2.height()) == (1111, 700)
    assert w2.table.columnWidth(2) == 222


def test_collapsed_top_panel_is_remembered(hist):
    h, make = hist
    w1 = make()
    w1.set_top_collapsed(True)
    w1.close()
    w1.wait_for_load()
    w2 = make()
    assert not w2.top_body.isVisible() or w2.top_body.isHidden()


def test_changes_are_saved_without_closing_the_window(hist, tmp_path):
    """Окно убили/сбой — размеры колонок уже на диске (сохранение с задержкой)."""
    h, make = hist
    w = make()
    ini = tmp_path / h.UI_SETTINGS_FILE
    ini.unlink() if ini.exists() else None
    w.table.setColumnWidth(3, 333)
    assert w._ui_save_timer.isActive()
    w._ui_save_timer.stop()
    w.save_ui_state()                       # то же, что сделает таймер через секунду
    assert ini.exists()
    w2 = make()
    assert w2.table.columnWidth(3) == 333


def test_no_autosave_while_the_window_is_being_built(hist):
    h, make = hist
    w = make()
    assert w._ui_ready is True


def test_registry_settings_are_migrated_once(hist, tmp_path, monkeypatch):
    h, _ = hist
    org, app = "DolomitTest", "InsalubrityHistory-" + uuid.uuid4().hex[:8]
    monkeypatch.setattr(h, "_REGISTRY_ORG", org)
    monkeypatch.setattr(h, "_REGISTRY_APP", app)
    monkeypatch.delenv("INSALUBRITY_TESTING", raising=False)
    old = h.QSettings(org, app)
    try:
        old.setValue("ui/top_collapsed", True)
        old.setValue("table/header_state_v2", "x")
        old.sync()
        assert h.migrate_ui_settings_from_registry() is True
        new = h.ui_settings()
        assert str(new.value("ui/top_collapsed")).lower() == "true" and new.value("table/header_state_v2") == "x"
        new.setValue("ui/top_collapsed", False)
        new.sync()
        assert h.migrate_ui_settings_from_registry() is False                # второй раз — ничего не затирает
        assert str(h.ui_settings().value("ui/top_collapsed")).lower() == "false"
    finally:
        old.clear()
        old.sync()


def test_migration_is_skipped_during_tests(hist):
    h, _ = hist
    assert os.environ.get("INSALUBRITY_TESTING") == "1"
    assert h.migrate_ui_settings_from_registry() is False
