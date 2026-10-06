"""
test_stage5.py — округление: расчёт дробный, итог округляется к ближайшему целому.
Запуск: pytest test_stage5.py -v
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import history_reader as hr
import insalubrity as ins
from helpers import leave_of
from test_class_split import vr


@pytest.mark.parametrize("value, expected", [
    (0.4, 0), (0.5, 1), (1.5, 2), (2.5, 3), (2.4999, 2), (22.0, 22),
    (-0.4, 0), (-0.5, -1), (-2.5, -3), (-2.4999, -2),
])
def test_fox_round_half_away_from_zero(value, expected):
    assert ins.fox_round(value) == expected


def test_fox_round_ignores_float_noise():
    assert ins.fox_round(22.499999999999996) == 23                # шум 22.5 -> 23, а не 22
    assert ins.fox_round(0.1 * 3 + 2.2) == 3                     # 2.5000000000000004 -> 3
    assert ins.fox_round(2.675 * 100 / 100 - 0.175) == 3         # 2.5 с шумом -> 3


def test_fox_round_returns_int():
    assert isinstance(ins.fox_round(2.5), int) and isinstance(ins.fox_round(-2.5), int)


def test_negative_vf_storno_rounds_away_from_zero():
    # 3.5 дня сторно: -3.5 -> -4 (раньше получалось -3)
    assert ins.fox_round(-3.5) == -4


def test_leave_total_is_rounded_but_calculation_stays_fractional():
    # 12 мес. по 10 дн. вредности 3.1 при норме 20 раб.дн./мес. -> 120*4/240 = 2
    # чтобы получить дробное, берём 13 дн. в одном месяце: (11*10 + 13) * 4 / 240
    rows = [vr(m, 10, 3.1, 0.29) for m in range(1, 13) if m != 6] + [vr(6, 13, 3.1, 0.29)]
    _, leave = leave_of(rows)
    expected_raw = (11 * 10 + 13) * 4 / (12 * 20)
    assert leave["vyshlo_total"] == pytest.approx(expected_raw)          # 2.0500 — дробное остаётся
    assert leave["vyshlo_total_rounded"] == 2
    assert leave["classes"][0]["vyshlo"] == pytest.approx(expected_raw)  # по классу не округляем


def test_rounded_total_half_up():
    # подбираем так, чтобы итог был ровно 2.5: дни * 4 / 240 = 2.5 -> дни = 150
    rows = [vr(m, 12, 3.1, 0.29) for m in range(1, 13) if m != 6] + [vr(6, 18, 3.1, 0.29)]
    _, leave = leave_of(rows)
    assert leave["vyshlo_total"] == pytest.approx((11 * 12 + 18) * 4 / 240)   # 2.5
    assert leave["vyshlo_total_rounded"] == 3


def test_rounded_total_sums_classes_before_rounding():
    # два класса: 1.4 + 1.4 = 2.8 -> 3, а не 1 + 1 = 2
    rows = (
        [vr(m, 10, 3.1, 0.29) for m in range(1, 7)]
        + [vr(m, 10, 3.2, 0.41) for m in range(7, 13)]
    )
    _, leave = leave_of(rows)
    parts = [c["vyshlo"] for c in leave["classes"]]
    assert sum(parts) == pytest.approx(leave["vyshlo_total"])
    assert leave["vyshlo_total_rounded"] == ins.fox_round(sum(parts))


def test_capped_total_never_exceeds_integer_norm():
    rows = [vr(m, 25, 3.1, 0.29) for m in range(1, 13)]
    _, leave = leave_of(rows)
    assert leave["vyshlo_total_rounded"] <= leave["polozheno_total"]
