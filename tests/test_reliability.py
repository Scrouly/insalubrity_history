"""
test_stage7.py — надёжность: фоновая загрузка, кэш RSV, резервные копии правок.
Запуск: pytest test_stage7.py -v
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date

import pandas as pd
import pytest

import app_env
import history_reader as hr
from test_stage6 import rec, write_rsv


# --- резервные копии правок -----------------------------------------------------
def test_save_keeps_bak_and_daily_snapshot(tmp_path):
    f = tmp_path / "month_overrides.json"
    hr._save_json_dict(f, {"v": 1})
    assert not (tmp_path / "month_overrides.json.bak").exists()      # копировать ещё нечего
    hr._save_json_dict(f, {"v": 2})
    hr._save_json_dict(f, {"v": 3})
    assert json.loads((tmp_path / "month_overrides.json.bak").read_text(encoding="utf-8")) == {"v": 2}
    snap = tmp_path / "backups" / f"month_overrides_{date.today():%Y%m%d}.json"
    assert json.loads(snap.read_text(encoding="utf-8")) == {"v": 1}  # состояние до первого сохранения за день
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 3}


def test_old_snapshots_are_pruned(tmp_path):
    f = tmp_path / "hire_dates_override.json"
    f.write_text("{}", encoding="utf-8")
    backups = tmp_path / "backups"
    backups.mkdir()
    for day in range(1, 41):
        (backups / f"hire_dates_override_2025{(day - 1) // 28 + 1:02d}{(day - 1) % 28 + 1:02d}.json").write_text("{}")
    hr._save_json_dict(f, {"a": 1})
    left = sorted(p.name for p in backups.glob("hire_dates_override_*.json"))
    assert len(left) == hr.BACKUP_KEEP_DAYS
    assert left[0] > "hire_dates_override_20250101.json"            # самые старые удалены


def test_backup_failure_does_not_block_save(tmp_path, monkeypatch):
    f = tmp_path / "month_overrides.json"
    hr._save_json_dict(f, {"v": 1})
    monkeypatch.setattr(hr.shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    hr._save_json_dict(f, {"v": 2})
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2}


def test_corrupt_file_is_still_refused_and_untouched(tmp_path):
    f = tmp_path / "month_overrides.json"
    f.write_text("{ битый", encoding="utf-8")
    with pytest.raises(hr.OverrideFileError):
        hr.save_month_override(1, 2026, 5, "vred_dni", 10, path=f)
    assert f.read_text(encoding="utf-8") == "{ битый"
    assert not (tmp_path / "backups").exists()


# --- кэш чтения RSV ---------------------------------------------------------------
def test_unchanged_files_are_read_once_and_changed_files_reread(tmp_path, monkeypatch):
    hr.clear_rsv_cache()
    f1 = tmp_path / "2025" / "rsv_01.xlsx"
    f2 = tmp_path / "2025" / "rsv_02.xlsx"
    write_rsv(f1, [rec(1)])
    write_rsv(f2, [rec(2)])
    calls = []
    real = hr.read_rsv_file
    monkeypatch.setattr(hr, "read_rsv_file", lambda path, log=None: (calls.append(path.name), real(path, log=log))[1])

    h1 = hr.build_history(tmp_path, log=lambda m: None)
    assert sorted(calls) == ["rsv_01.xlsx", "rsv_02.xlsx"]
    calls.clear()
    h2 = hr.build_history(tmp_path, log=lambda m: None)
    assert calls == [] and h2["tn"].tolist() == h1["tn"].tolist()

    write_rsv(f2, [rec(2), rec(3)])
    os.utime(f2, ns=(time.time_ns() + 5_000_000_000, time.time_ns() + 5_000_000_000))
    h3 = hr.build_history(tmp_path, log=lambda m: None)
    assert calls == ["rsv_02.xlsx"] and sorted(h3["tn"].tolist()) == [1, 2, 3]
    hr.clear_rsv_cache()


def test_cache_returns_independent_copies(tmp_path):
    hr.clear_rsv_cache()
    write_rsv(tmp_path / "2025" / "rsv_01.xlsx", [rec(1)])
    a = hr.build_history(tmp_path, log=lambda m: None)
    a.loc[:, "tn"] = 999
    b = hr.build_history(tmp_path, log=lambda m: None)
    assert b["tn"].tolist() == [1]
    hr.clear_rsv_cache()


def test_file_warnings_survive_the_cache(tmp_path):
    hr.clear_rsv_cache()
    write_rsv(tmp_path / "2025" / "rsv_01.xlsx", [rec(1), {}, rec(2)])
    first, second = [], []
    hr.build_history(tmp_path, log=first.append)
    hr.build_history(tmp_path, log=second.append)
    assert first and any("пустая строка" in m for m in second)
    hr.clear_rsv_cache()


# --- фоновая загрузка окна ----------------------------------------------------------
_QAPP = None


def _qt():
    global _QAPP
    pytest.importorskip("PyQt5.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


@pytest.fixture
def window_factory(tmp_path, monkeypatch):
    _qt()
    from PyQt5.QtWidgets import QMessageBox
    boxes = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: boxes.append(("critical", a[2]))))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: boxes.append(("warning", a[2]))))
    monkeypatch.setattr(app_env, "ENV_FILE_PATH", tmp_path / ".env")
    (tmp_path / ".env").write_text(f"DBF_DATA_DIR={tmp_path}\nOUT_DIR={tmp_path}\n", encoding="utf-8")
    import insalubrity_history as h
    made = []

    def make(build_delay=0.0, employees=True):
        info = {"calls": 0, "threads": []}

        def fake_build(out_dir, log=print):
            info["calls"] += 1
            info["threads"].append(threading.current_thread() is threading.main_thread())
            time.sleep(build_delay)
            return hr.empty_history()

        def fake_employees(data_dir):
            if not employees:
                raise OSError("нет lschet.dbf")
            return pd.DataFrame({"tn": [7], "fio": ["ИВАНОВ ИВАН"], "dnepr": [date(2015, 3, 2)], "data_uvl": [None]})

        monkeypatch.setattr(h.hr, "build_history", fake_build)
        monkeypatch.setattr(h.hr, "get_lschet_employees", fake_employees)
        w = h.HistoryWindow()
        made.append(w)
        return w, info, boxes

    yield make
    for w in made:
        w.wait_for_load()


def test_window_does_not_block_while_loading(window_factory):
    w, info, _ = window_factory(build_delay=0.4)
    assert w._loader is not None and w._loader.isRunning()      # конструктор вернулся, чтение идёт в фоне
    assert not w.search_input.isEnabled()
    assert "Загрузка" in w.status_lbl.text()
    assert w.wait_for_load()
    assert info["threads"] == [False]                            # чтение было НЕ в главном потоке
    assert w.search_input.isEnabled()
    assert len(w.display_to_tn) == 1 and "Сотрудников: 1" in w.status_lbl.text()


def test_reload_during_loading_restarts_once_with_fresh_state(window_factory):
    w, info, _ = window_factory(build_delay=0.3)
    w.reload_data()
    w.reload_data()                                              # два нажатия «Обновить» подряд
    assert w.wait_for_load()
    assert info["calls"] == 2                                    # не 3 и не параллельно: текущая + одна повторная
    assert w._loader is None and w.search_input.isEnabled()


def test_lschet_error_shows_dialog_and_keeps_window_alive(window_factory):
    w, _, boxes = window_factory(employees=False)
    assert w.wait_for_load()
    assert w.employees is None
    assert boxes and boxes[0][0] == "critical" and "нет lschet.dbf" in boxes[0][1]
    assert w.search_input.isEnabled()
    assert "Ошибка чтения lschet.dbf" in w.status_lbl.text()


def test_close_waits_for_running_loader(window_factory):
    from PyQt5.QtGui import QCloseEvent
    w, _, _ = window_factory(build_delay=0.4)
    loader = w._loader
    assert loader.isRunning()
    w.closeEvent(QCloseEvent())
    assert not loader.isRunning()
