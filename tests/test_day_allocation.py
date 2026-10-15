"""
test_day_allocation.py — (1) округление дней вредности по сумме месяца, а не по строкам;
(2) класс вредности текстом в RSV не роняет чтение истории.
Запуск: pytest tests/test_day_allocation.py -v
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from openpyxl import load_workbook

import history_reader as hr
import insalubrity as ins
from helpers import rec, write_rsv


# --- allocate_days -------------------------------------------------------------------
def _alloc(values, keys=None):
    exact = pd.Series(values, dtype=float)
    keys = keys if keys is not None else [(1, 2025, 5)] * len(values)
    groups = pd.DataFrame(keys, columns=["tn", "god", "mes"], index=exact.index)
    return ins.allocate_days(exact, groups).tolist()


def test_two_half_day_rows_sum_to_month_norm():
    # было 11 + 11 = 22 при норме месяца 21
    assert sum(_alloc([10.5, 10.5])) == 21


@pytest.mark.parametrize("values, total", [
    ([4.5, 4.5], 9),
    ([2.5, 2.5, 2.5], 8),          # сумма 7,5 -> 8 (половина от нуля, как fox_round)
    ([7.2, 13.8], 21),
    ([0.4, 0.4, 0.4], 1),          # 1,2 -> 1: «лишних» единиц не появляется
])
def test_group_total_equals_rounded_exact_sum(values, total):
    out = _alloc(values)
    assert sum(out) == total
    assert all(isinstance(v, int) for v in out)


def test_extra_units_go_to_largest_fraction_then_first_row():
    assert _alloc([10.2, 10.8]) == [10, 11]
    assert _alloc([10.5, 10.5]) == [11, 10]      # ничья — раньше стоящая строка


def test_groups_are_independent():
    out = _alloc([10.5, 10.5, 3.5], keys=[(1, 2025, 5), (1, 2025, 5), (2, 2025, 5)])
    assert sum(out[:2]) == 21 and out[2] == 4


def test_single_row_behaves_like_fox_round():
    assert _alloc([10.5]) == [11] and _alloc([10.4]) == [10]


def test_storno_group_falls_back_to_per_row_rounding():
    assert _alloc([10.5, -3.5]) == [11, -4]


def test_nan_group_keys_do_not_crash():
    out = _alloc([1.5, 1.5], keys=[(1, float("nan"), 5), (1, float("nan"), 5)])
    assert sum(out) == 3


# --- через _do_run ------------------------------------------------------------------
def _run(tmp_path, monkeypatch, svod_rows):
    svod = pd.DataFrame(svod_rows)
    lschet = pd.DataFrame([{"tn": t, "fio": f"Т{t}", "pr_dn": 1} for t in sorted({r["tn"] for r in svod_rows})])
    kalend = pd.DataFrame([(1, 2025, 5, 21, 168.0)], columns=["pr_dn", "god", "mes", "kol_rd", "fond_ch"])
    dolgn = pd.DataFrame([{"dshifr": 7, "dname": "Слесарь"}])
    tables = {"lschet": lschet, "kalend": kalend, "dolgn": dolgn, "svod2505": svod}
    monkeypatch.setattr(ins, "find_table", lambda d, name: name)
    monkeypatch.setattr(ins, "load_dbf", lambda path, enc="cp866": tables[path].copy())
    res = ins._do_run(tmp_path, 5, 2025, 0.29, 0.41, 0.58, tmp_path, "cp866", lambda m: None)
    return hr.read_rsv_file(res["rsv_path"]), res


def _row(tn, vop, vf, rate):
    return {"tn": tn, "no": 1, "vop": vop, "vf": vf, "sux": vf * rate, "dolgn": 7,
            "god": 2025, "mes": 5, "pr_dn": 1}


def test_class_change_month_never_exceeds_norm(tmp_path, monkeypatch):
    df, res = _run(tmp_path, monkeypatch, [_row(1, 49, 84.0, 0.29), _row(1, 49, 84.0, 0.41)])
    assert int(df["vred_dni"].sum()) == 21 and res["sum_rsv"] == 21
    assert sorted(df["bal_vredn"].tolist()) == [3.1, 3.2]       # оба класса сохранены


def test_other_employees_are_not_mixed(tmp_path, monkeypatch):
    df, _ = _run(tmp_path, monkeypatch, [_row(1, 49, 84.0, 0.29), _row(1, 49, 84.0, 0.41),
                                         _row(2, 49, 84.0, 0.29)])
    by_tn = df.groupby("tn")["vred_dni"].sum().to_dict()
    assert by_tn == {1: 21, 2: 11}                              # 10,5 у одиночной строки -> 11


def test_po_sredn_is_allocated_by_month_too(tmp_path, monkeypatch):
    df, _ = _run(tmp_path, monkeypatch, [_row(1, 6, 84.0, 0.1), _row(1, 6, 84.0, 0.1)])
    assert int(df["po_sredn"].sum()) == 21


# --- класс текстом в RSV ----------------------------------------------------------
def test_text_class_with_comma_does_not_crash_history(tmp_path):
    write_rsv(tmp_path / "2025" / "rsv_01.xlsx",
              [rec(1, bal_vredn="3,1", vred_dni=15), rec(1, bal_vredn=3.2, vred_dni=5)])
    logs = []
    history = hr.build_history(tmp_path, log=logs.append)
    assert sorted(history["bal_vredn"].tolist()) == [3.1, 3.2]
    tl = hr.build_employee_timeline(1, history, hire_date=date(2025, 1, 5))
    assert tl.loc[0, "bal_vredn"] == 3.1                        # больше дней вредности
    assert tl.loc[0, "vred_by_class"] == {3.1: 15.0, 3.2: 5.0}
    assert not any("bal_vredn" in m for m in logs)              # «3,1» — не потерянное значение


def test_garbage_class_is_reported_not_fatal(tmp_path):
    write_rsv(tmp_path / "2025" / "rsv_01.xlsx", [rec(1, bal_vredn="abc"), rec(2, bal_vredn=3.1)])
    logs = []
    history = hr.build_history(tmp_path, log=logs.append)
    assert history["bal_vredn"].isna().sum() == 1
    assert any("bal_vredn" in m and "abc" in m for m in logs)
