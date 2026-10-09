"""Окно «История по вредности»: для месяца со сменой класса подсказки называют класс,
в который отнесён отпуск, — преобладающий за рабочий год (а не за месяц)."""
from __future__ import annotations

import os
from datetime import date

import pandas as pd
import pytest

import history_reader as hr

_QAPP = None


def _qt():
    global _QAPP
    pytest.importorskip("PyQt5.QtWidgets")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication
    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


def _history(rows):
    cols = hr.RSV_DATA_COLUMNS + ["file_year", "file_month"]
    df = pd.DataFrame(rows).reindex(columns=cols)
    for c in ("tn", "vop", "vred_dni", "otp_dni", "otp_bud_m", "po_sredn", "tar1", "kol_rd"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _vr(month, vred, cls, tar):
    return dict(tn=1, vop=49, vred_dni=vred, kol_rd=20, bal_vredn=cls, tar1=tar, file_year=2025, file_month=month)


def test_window_names_year_dominant_class_for_leave_in_mixed_month(tmp_path, monkeypatch):
    _qt()
    import app_env
    import insalubrity_history as h

    monkeypatch.setattr(app_env, "ENV_FILE_PATH", tmp_path / ".env")
    (tmp_path / ".env").write_text(f"DBF_DATA_DIR={tmp_path}\nOUT_DIR={tmp_path}\n", encoding="utf-8")
    monkeypatch.setattr(h.hr, "build_history", lambda out_dir, log=print: hr.empty_history())
    monkeypatch.setattr(h.hr, "get_lschet_employees", lambda data_dir: pd.DataFrame(
        {"tn": [1], "fio": ["ИВАНОВ ИВАН"], "dnepr": [date(2025, 1, 10)], "data_uvl": [None]}))
    monkeypatch.setattr(h.hr, "load_month_overrides", lambda *a, **k: {})

    w = h.HistoryWindow()
    assert w.wait_for_load()

    # за год преобладает 3.2; в июне больше дней в 3.1 (9 против 6) и есть отпуск
    rows = [_vr(m, 20, 3.2, 0.41) for m in (1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12)]
    rows += [_vr(6, 9, 3.1, 0.29), _vr(6, 6, 3.2, 0.41),
             dict(tn=1, vop=80, otp_dni=5, kol_rd=20, tar1=1500.0, file_year=2025, file_month=6)]
    w.history = _history(rows)
    w.render_timeline(1, date(2025, 1, 10))

    texts, tips = [], []
    for r in range(w.table.rowCount()):
        for c in range(w.table.columnCount()):
            it = w.table.item(r, c)
            if it is not None:
                texts.append(it.text())
                tips.append(it.toolTip())

    summary = [t for t in texts if t.startswith("Смена класса в 06.2025")]
    assert len(summary) == 1
    assert "отнесены к классу 3.2" in summary[0] and "преобладает за рабочий год" in summary[0]
    cell_tips = [t for t in tips if t.startswith("Смена класса в этом месяце")]
    assert len(cell_tips) == 1 and "классу 3.2" in cell_tips[0]
    w.close()
