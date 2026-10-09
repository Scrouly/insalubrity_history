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


def test_leave_and_po_sredn_are_not_split_they_go_to_year_dominant_class():
    # вредность 5 дн. (3.1) и 15 дн. (3.2); отпуск 8 и «по среднему» 2 -> целиком в
    # класс, преобладающий за рабочий год по дням вредности: 3.1 (11*20+5 против 15)
    rows = year_rows(skip=(6,)) + [
        vr(6, 5, 3.1, 0.29), vr(6, 15, 3.2, 0.41),
        dict(tn=1, vop=80, otp_dni=8, kol_rd=20, tar1=1500.0, file_year=2025, file_month=6),
        dict(tn=1, vop=6, po_sredn=2, kol_rd=20, tar1=1500.0, file_year=2025, file_month=6),
    ]
    _, leave = leave_of(rows)
    c = by_class(leave)
    assert c[3.1]["days"] == pytest.approx(11 * 20 + 5 + 8 + 2)  # вредность + отпуск + по среднему
    assert c[3.2]["days"] == pytest.approx(15)                   # только свои дни вредности
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


# --- правило: в месяце с несколькими классами отпуск идёт в класс, преобладающий за год ---

def _mixed_june_with_leave(year_cls, june_split, leave=8, year_vred=20):
    """Год из 11 обычных месяцев в классе year_cls (ставка по классу) + июнь с двумя
    классами и отпуском."""
    tars = {3.1: 0.29, 3.2: 0.41, 3.3: 0.58}
    rows = year_rows(skip=(6,), vred=year_vred, cls=year_cls, tar=tars[year_cls])
    rows += [vr(6, d, c, tars[c]) for c, d in june_split]
    rows.append(dict(tn=1, vop=80, otp_dni=leave, kol_rd=20, tar1=1500.0, file_year=2025, file_month=6))
    return leave_of(rows)


def test_leave_in_mixed_month_goes_to_class_dominant_over_the_year_not_the_month():
    # июнь: 3.1 — 5 дн., 3.2 — 15 дн. (в месяце преобладает 3.2), но за год больше всего
    # дней в 3.1 -> отпуск целиком в 3.1
    _, leave = _mixed_june_with_leave(3.1, [(3.1, 5), (3.2, 15)])
    c = by_class(leave)
    assert c[3.1]["days"] == pytest.approx(11 * 20 + 5 + 8)
    assert c[3.2]["days"] == pytest.approx(15)


def test_leave_in_mixed_month_follows_year_class_when_it_is_the_higher_one():
    # за год больше всего дней в 3.2 -> отпуск в 3.2, хотя в июне больше дней в 3.1
    _, leave = _mixed_june_with_leave(3.2, [(3.1, 15), (3.2, 5)])
    c = by_class(leave)
    assert c[3.2]["days"] == pytest.approx(11 * 20 + 5 + 8)
    assert c[3.1]["days"] == pytest.approx(15)


def test_year_dominance_is_by_sum_of_days_not_by_number_of_months():
    # 3.1 встречается в 8 месяцах (40 + 12 дн. вне июня), 3.2 — всего в 3 (66 дн.):
    # с июнем 3.1 = 57 дн., 3.2 = 71 дн. -> отпуск в смешанном июне идёт в 3.2
    tars = {3.1: 0.29, 3.2: 0.41}
    rows = (
        [vr(m, 10, 3.1, tars[3.1]) for m in (1, 2, 3, 4)]
        + [vr(m, 22, 3.2, tars[3.2]) for m in (5, 7, 8)]
        + [vr(m, 3, 3.1, tars[3.1]) for m in (9, 10, 11, 12)]
        + [vr(6, 5, 3.1, tars[3.1]), vr(6, 5, 3.2, tars[3.2]),
           dict(tn=1, vop=80, otp_dni=6, kol_rd=20, tar1=1500.0, file_year=2025, file_month=6)]
    )
    _, leave = leave_of(rows)
    c = by_class(leave)
    assert c[3.2]["days"] == pytest.approx(66 + 5 + 6)
    assert c[3.1]["days"] == pytest.approx(40 + 12 + 5)


def test_year_dominant_tie_in_mixed_month_goes_to_higher_class():
    # за год 3.1 = 60 дн., 3.2 = 60 дн. (ничья) -> отпуск в смешанном марте в старший класс
    rows = [vr(m, 10, 3.1, 0.29) for m in (1, 4, 5, 6, 7)]
    rows += [vr(m, 10, 3.2, 0.41) for m in (2, 8, 9, 10, 11)]
    rows += [vr(3, 5, 3.1, 0.29), vr(3, 5, 3.2, 0.41),
             vr(12, 5, 3.1, 0.29), vr(12, 5, 3.2, 0.41),
             dict(tn=1, vop=80, otp_dni=4, kol_rd=20, tar1=1500.0, file_year=2025, file_month=3)]
    _, leave = leave_of(rows)
    c = by_class(leave)
    assert c[3.2]["days"] == pytest.approx(50 + 5 + 5 + 4)
    assert c[3.1]["days"] == pytest.approx(50 + 5 + 5)


def test_year_dominant_is_chosen_only_among_classes_of_the_mixed_month():
    # за год преобладает 3.3 (180 дн.), но в смешанном июне его нет; в июне больше дней
    # в 3.1 (9 против 6), зато за год 3.2 (46) > 3.1 (9) -> отпуск (5) в 3.2, а не в 3.3 и не в 3.1
    rows = [vr(m, 20, 3.2, 0.41) for m in (1, 2)]
    rows += [vr(m, 20, 3.3, 0.58) for m in (3, 4, 5, 7, 8, 9, 10, 11, 12)]
    rows += [vr(6, 9, 3.1, 0.29), vr(6, 6, 3.2, 0.41),
             dict(tn=1, vop=80, otp_dni=5, kol_rd=20, tar1=1500.0, file_year=2025, file_month=6)]
    _, leave = leave_of(rows)
    c = by_class(leave)
    assert c[3.3]["days"] == pytest.approx(9 * 20)
    assert c[3.2]["days"] == pytest.approx(40 + 6 + 5)
    assert c[3.1]["days"] == pytest.approx(9)


def test_single_class_month_leave_still_goes_to_month_class():
    _, leave = leave_of(year_rows(skip=(6,)) + [
        vr(6, 12, 3.2, 0.41),
        dict(tn=1, vop=80, otp_dni=3, kol_rd=20, tar1=1500.0, file_year=2025, file_month=6)])
    c = by_class(leave)
    assert c[3.2]["days"] == pytest.approx(12 + 3)
    assert c[3.1]["days"] == pytest.approx(11 * 20)


# --- правило: в достроенных месяцах дни вредности равны норме рабочих дней ---

def test_projected_months_vred_days_equal_kol_rd():
    # в прошлых месяцах вредность 12 дн. при норме 20 — среднее vred_dni было бы 12
    rows = [vr(m, 12, 3.1, 0.29, year=2025, kol=20) for m in range(1, 7)]
    tl = hr.build_employee_timeline(1, make_history(rows), hire_date=date(2025, 1, 10))
    proj = hr.project_current_work_year(tl)
    p = proj[proj["is_projected"]]
    assert len(p) == 6
    assert (p["kol_rd"] == 20).all()
    assert (p["vred_dni"] == p["kol_rd"]).all()
    assert (p["monthly_total"] == p["kol_rd"]).all()
    assert p["projection_note"].str.contains("равными норме").all()
    # фактические месяцы не тронуты
    assert (proj.loc[~proj["is_projected"], "vred_dni"] == 12).all()


def test_projected_kol_rd_is_still_pool_average():
    rows = [vr(m, 10, 3.1, 0.29, year=2025, kol=k) for m, k in zip(range(1, 5), (18, 20, 22, 20))]
    tl = hr.build_employee_timeline(1, make_history(rows), hire_date=date(2025, 1, 10))
    p = hr.project_current_work_year(tl)
    p = p[p["is_projected"]]
    assert (p["kol_rd"] == 20).all() and (p["vred_dni"] == 20).all()


def test_projection_gives_leave_year_total_up_to_norm_for_unfinished_year():
    rows = [vr(m, 12, 3.1, 0.29, year=2025, kol=20) for m in range(1, 7)]
    tl = hr.build_employee_timeline(1, make_history(rows), hire_date=date(2025, 1, 10))
    leave = hr.summarize_leave_entitlement(hr.project_current_work_year(tl))[0]
    # 6 факт. мес. по 12 дн. + 6 достроенных по 20 дн. = 192 дня из 240
    assert by_class(leave)[3.1]["days"] == pytest.approx(6 * 12 + 6 * 20)


def test_leave_result_reports_class_chosen_for_mixed_month():
    _, leave = _mixed_june_with_leave(3.1, [(3.1, 5), (3.2, 15)])
    assert leave["mixed_month_leave_class"] == {(2025, 6): 3.1}
    # без смены класса словарь пуст
    _, plain = leave_of(year_rows())
    assert plain["mixed_month_leave_class"] == {}