"""
test_stage3.py — разделение дней по классам вредности (синтетика).
Запуск: pytest test_stage3.py -v
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import history_reader as hr


def make_history(rows):
    cols = hr.RSV_DATA_COLUMNS + ["file_year", "file_month"]
    df = pd.DataFrame(rows).reindex(columns=cols)
    for c in ("tn", "vop", "vred_dni", "otp_dni", "otp_bud_m", "po_sredn", "tar1", "kol_rd"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def vr(month, vred, cls, tar, tn=1, year=2025, kol=20):
    return dict(tn=tn, vop=49, vred_dni=vred, kol_rd=kol, bal_vredn=cls, tar1=tar, file_year=year, file_month=month)


def year_rows(skip=(), vred=20, cls=3.1, tar=0.29):
    return [vr(m, vred, cls, tar) for m in range(1, 13) if m not in skip]


def leave_of(rows, **kw):
    tl = hr.build_employee_timeline(1, make_history(rows), hire_date=date(2025, 1, 10))
    blocks = hr.build_work_year_blocks(tl, **kw)
    return tl, blocks[0]["leave"]


def by_class(leave):
    return {c["klass"]: c for c in leave["classes"]}


def test_mixed_month_splits_vredn_days_between_classes():
    rows = year_rows(skip=(6,)) + [vr(6, 5, 3.1, 0.29), vr(6, 15, 3.2, 0.41)]
    tl, leave = leave_of(rows)
    june = tl[(tl["year"] == 2025) & (tl["month"] == 6)].iloc[0]
    assert june["vred_dni"] == 20
    assert june["vred_by_class"] == {3.1: 5.0, 3.2: 15.0}
    assert june["bal_vredn"] == 3.2           # в ячейке — класс с большим числом дней
    c = by_class(leave)
    assert c[3.1]["days"] == pytest.approx(11 * 20 + 5)
    assert c[3.2]["days"] == pytest.approx(15)
    assert leave["mixed_class_months"] == [(2025, 6, {3.1: 5.0, 3.2: 15.0})]


def test_leave_and_po_sredn_are_not_split_they_go_to_usual_class():
    # вредность 5 дн. (3.1) и 15 дн. (3.2); отпуск 8 и «по среднему» 2 -> целиком в 3.2
    rows = year_rows(skip=(6,)) + [
        vr(6, 5, 3.1, 0.29), vr(6, 15, 3.2, 0.41),
        dict(tn=1, vop=80, otp_dni=8, kol_rd=20, tar1=1500.0, file_year=2025, file_month=6),
        dict(tn=1, vop=6, po_sredn=2, kol_rd=20, tar1=1500.0, file_year=2025, file_month=6),
    ]
    _, leave = leave_of(rows)
    c = by_class(leave)
    assert c[3.1]["days"] == pytest.approx(11 * 20 + 5)         # только свои дни вредности
    assert c[3.2]["days"] == pytest.approx(15 + 8 + 2)          # вредность + отпуск + по среднему
    total = sum(x["days"] for x in leave["classes"]) + leave["unclassified_days"]
    assert total == pytest.approx(11 * 20 + 30)                  # дни не теряются и не двоятся


def test_leave_goes_to_lower_class_when_it_dominates_the_month():
    rows = year_rows(skip=(6,)) + [
        vr(6, 15, 3.1, 0.29), vr(6, 5, 3.2, 0.41),
        dict(tn=1, vop=80, otp_dni=8, kol_rd=20, tar1=1500.0, file_year=2025, file_month=6),
    ]
    _, leave = leave_of(rows)
    c = by_class(leave)
    assert c[3.1]["days"] == pytest.approx(11 * 20 + 15 + 8)
    assert c[3.2]["days"] == pytest.approx(5)


def test_month_without_vredn_row_leave_goes_to_carried_class():
    rows = year_rows(skip=(6,)) + [dict(tn=1, vop=80, otp_dni=8, kol_rd=20, tar1=1500.0, file_year=2025, file_month=6)]
    _, leave = leave_of(rows)
    assert by_class(leave)[3.1]["days"] == pytest.approx(11 * 20 + 8)


def test_tie_goes_to_higher_class():
    rows = year_rows(skip=(6,)) + [vr(6, 10, 3.1, 0.29), vr(6, 10, 3.2, 0.41)]
    tl, _ = leave_of(rows)
    assert tl[(tl["year"] == 2025) & (tl["month"] == 6)].iloc[0]["bal_vredn"] == 3.2


def test_next_month_carries_dominant_class():
    # в июне больше дней в 3.1, а было 3.2 в 5 дней; июль без строки вредности — переносится 3.1
    rows = year_rows(skip=(6, 7)) + [vr(6, 15, 3.1, 0.29), vr(6, 5, 3.2, 0.41)]
    tl, _ = leave_of(rows)
    july = tl[(tl["year"] == 2025) & (tl["month"] == 7)].iloc[0]
    assert july["bal_vredn_effective"] == 3.1


def test_single_class_behaviour_unchanged():
    tl, leave = leave_of(year_rows())
    c = by_class(leave)
    assert list(c) == [3.1] and c[3.1]["days"] == pytest.approx(240)
    assert leave["mixed_class_months"] == []
    assert tl["vred_by_class"].map(len).max() == 1


def test_manual_class_override_beats_split():
    rows = year_rows(skip=(6,)) + [vr(6, 5, 3.1, 0.29), vr(6, 15, 3.2, 0.41)]
    overrides = {"2025-06": {"bal_vredn": 3.3}}
    _, leave = leave_of(rows, month_overrides=overrides)
    c = by_class(leave)
    assert c[3.3]["days"] == pytest.approx(20)        # весь июнь — в правленый класс
    assert c[3.1]["days"] == pytest.approx(11 * 20)
    assert 3.2 not in c
    assert leave["mixed_class_months"] == []


def test_overridden_vredn_days_scale_split_and_stay_fractional():
    rows = year_rows(skip=(6,)) + [vr(6, 5, 3.1, 0.29), vr(6, 15, 3.2, 0.41)]
    _, leave = leave_of(rows, month_overrides={"2025-06": {"vred_dni": 7}})
    c = by_class(leave)
    assert c[3.1]["days"] == pytest.approx(11 * 20 + 7 * 0.25)   # 1.75: дробные дни не округляются
    assert c[3.2]["days"] == pytest.approx(7 * 0.75)


def test_projected_months_use_carried_class_without_split_column():
    rows = [vr(m, 20, 3.1, 0.29, year=2025) for m in range(1, 7)]
    tl = hr.build_employee_timeline(1, make_history(rows), hire_date=date(2025, 1, 10))
    proj = hr.project_current_work_year(tl)
    leave = hr.summarize_leave_entitlement(proj)[0]
    assert [c["klass"] for c in leave["classes"]] == [3.1]
    assert leave["unclassified_days"] == 0
