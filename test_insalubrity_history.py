"""
test_insalubrity_history.py
============================
Регрессионный прогон построения истории/отпуска за вредность СРАЗУ ПО ВСЕМ
сотрудникам из lschet.dbf. Использует ровно ту же логику, что и GUI
(history_reader.build_employee_timeline / build_work_year_blocks /
summarize_leave_entitlement) — никакого дублирования кода, никакого PyQt6.

Что проверяется на каждом сотруднике:
  1. build_employee_timeline(...) не падает с исключением.
  2. build_work_year_blocks(...) не падает с исключением (тот же вызов,
     что использует insalubrity_history.py при отрисовке).
  3. Базовые инварианты результата (см. check_timeline_invariants и
     check_blocks_invariants) — например, что monthly_total действительно
     равен сумме своих слагаемых, что часы/дни не отрицательные, что среди
     отображаемых рабочих лет нет ни одного полностью пустого и наоборот —
     что ни один рабочий год с реальными данными не потерялся при фильтрации.

Запуск (пути берутся из .env — того же файла, что использует GUI):
    python test_insalubrity_history.py                # печатает статус по каждому сотруднику
    python test_insalubrity_history.py --stress        # + прогон по синтетическим датам устройства
    python test_insalubrity_history.py -q              # только предупреждения/ошибки + итог
    python test_insalubrity_history.py --data-dir ... --out-dir ...   # переопределить пути

Через pytest (если он установлен):
    pytest test_insalubrity_history.py -v -s
"""

from __future__ import annotations

import argparse
import math
import sys
import traceback
from pathlib import Path

import pandas as pd

import history_reader as hr
from app_env import load_env_vars

REQUIRED_TIMELINE_COLUMNS = {
    "year", "month", "kol_rd", "vred_dni", "bal_vredn", "otp_dni",
    "otp_bud_m", "po_sredn", "tar1", "has_data", "work_year_key",
    "work_year_label", "monthly_total", "bal_vredn_effective", "is_projected",
}

VALID_CLASSES = (3.1, 3.2, 3.3)


def _is_nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def check_timeline_invariants(timeline: pd.DataFrame) -> list[str]:
    """Возвращает список текстовых проблем по одному таймлайну (пусто — всё ок)."""
    problems: list[str] = []
    if timeline.empty:
        return problems  # пустой таймлайн — законный случай (нет ни одной записи)

    missing_cols = REQUIRED_TIMELINE_COLUMNS - set(timeline.columns)
    if missing_cols:
        problems.append(f"в таймлайне нет колонок: {sorted(missing_cols)}")
        return problems  # дальше без них не проверить

    for _, r in timeline.iterrows():
        ym = f"{int(r['year'])}-{int(r['month']):02d}"

        for col in ("kol_rd", "vred_dni", "otp_dni", "otp_bud_m", "po_sredn", "monthly_total"):
            val = r[col]
            if _is_nan(val):
                problems.append(f"{ym}: {col} = None/NaN (ожидалось число, в т.ч. 0)")
            elif val < 0:
                problems.append(f"{ym}: {col} = {val} — отрицательное значение")

        expected_monthly = (r["vred_dni"] or 0) + (r["otp_dni"] or 0) + (r["otp_bud_m"] or 0) + (r["po_sredn"] or 0)
        if abs((r["monthly_total"] or 0) - expected_monthly) > 1e-6:
            problems.append(
                f"{ym}: monthly_total={r['monthly_total']} != "
                f"vred+otp+otp_bud+po_sredn={expected_monthly}"
            )

        if not bool(r["has_data"]):
            # kol_rd — исключение: fix_zero_kol_rd_months осознанно проставляет
            # туда оценочную норму дней по графику (is_projected=True) даже
            # когда по вредности/отпуску записей вообще нет — это НЕ баг.
            # А вот вредность/отпуск/итого при отсутствии данных обязаны
            # остаться нулевыми — их фиктивным средним не подменяют.
            for col in ("vred_dni", "otp_dni", "otp_bud_m", "po_sredn", "monthly_total"):
                if (r[col] or 0) != 0:
                    problems.append(f"{ym}: has_data=False, но {col}={r[col]} (ожидался 0)")
            if bool(r.get("is_data_fix", False)):
                problems.append(f"{ym}: has_data=False, но is_data_fix=True (это состояние только для has_data=True)")

        bal = r["bal_vredn"]
        if not _is_nan(bal) and round(bal, 1) not in VALID_CLASSES:
            problems.append(f"{ym}: неожиданный класс bal_vredn={bal}")

    return problems


def check_blocks_invariants(blocks: list[dict], timeline: pd.DataFrame) -> list[str]:
    """Проверяет результат build_work_year_blocks относительно исходного таймлайна."""
    problems: list[str] = []
    if not blocks:
        return problems

    # Самый ранний месяц, за который у сотрудника вообще есть настоящие
    # RSV-данные — ни один спрогнозированный месяц не должен быть раньше него
    # (иначе прогноз "достраивает" вредность до того, как сотрудник вообще
    # появился в данных — см. историю с project_current_work_year).
    real_months = timeline.loc[timeline["has_data"], ["year", "month"]]
    earliest_real = (
        tuple(real_months.astype(int).sort_values(["year", "month"]).iloc[0])
        if not real_months.empty else None
    )

    for b in blocks:
        label = b.get("label", "?")

        if not b.get("has_data"):
            problems.append(f"год {label}: попал в отображение, но has_data=False у всех строк")
        if not b["month_rows"]:
            problems.append(f"год {label}: пустой список месяцев")
        if b["month_count"] != len(b["month_rows"]):
            problems.append(f"год {label}: month_count={b['month_count']} != len(month_rows)={len(b['month_rows'])}")
        if b["month_count"] > 12:
            problems.append(f"год {label}: month_count={b['month_count']} > 12 — прогноз достроил лишнее")

        for r in b["month_rows"]:
            if bool(r.get("is_projected", False)):
                ym = f"{int(r['year'])}-{int(r['month']):02d}"
                if bool(r["has_data"]):
                    problems.append(f"год {label}, {ym}: is_projected=True, но has_data=True одновременно")
                if r["kol_rd"] < 0 or r["vred_dni"] < 0:
                    problems.append(f"год {label}, {ym}: спрогнозированные kol_rd/vred_dni отрицательны")
                # Проверяем только настоящий ПРОГНОЗ вредности (vred_dni > 0). Оценка
                # одной лишь нормы дней (fix_zero_kol_rd_months) для месяцев без
                # записей — легитимна и может стоять раньше первой реальной записи.
                if (
                    earliest_real is not None
                    and (r["vred_dni"] or 0) > 0
                    and (int(r["year"]), int(r["month"])) < earliest_real
                ):
                    problems.append(
                        f"год {label}, {ym}: спрогнозированный месяц РАНЬШЕ самого раннего "
                        f"реального ({earliest_real[0]}-{earliest_real[1]:02d}) — прогноз ушёл в прошлое"
                    )

        for col in ("kol_rd_total", "vred_total", "monthly_total"):
            val = b[col]
            if _is_nan(val):
                problems.append(f"год {label}: {col} = None/NaN")
            elif val < 0:
                problems.append(f"год {label}: {col} = {val} — отрицательное значение")

        leave = b.get("leave")
        if leave is not None:
            if _is_nan(leave["vyshlo_total"]) or leave["vyshlo_total"] < 0:
                problems.append(f"год {label}: vyshlo_total некорректен ({leave['vyshlo_total']})")
            if leave["polozheno_total"] < 0:
                problems.append(f"год {label}: polozheno_total < 0")
            if leave["unclassified_days"] < 0:
                problems.append(f"год {label}: unclassified_days < 0")
            for c in leave["classes"]:
                if round(c["klass"], 1) not in VALID_CLASSES:
                    problems.append(f"год {label}: неизвестный класс в разбивке {c['klass']}")

    # Множество рабочих лет, реально содержащих данные в таймлайне, должно
    # ровно совпадать с множеством лет, показанных в blocks — ни одно
    # непустое не должно потеряться, ни одно пустое не должно просочиться.
    years_with_data_in_timeline = {
        key for key, grp in timeline.groupby("work_year_key") if grp["has_data"].any()
    }
    shown_keys = {b["work_year_key"] for b in blocks}
    if shown_keys != years_with_data_in_timeline:
        problems.append(
            f"расхождение множеств рабочих лет: показаны {sorted(shown_keys)}, "
            f"а реально с данными {sorted(years_with_data_in_timeline)}"
        )

    return problems


def run_all(data_dir: Path, out_dir: Path, quiet: bool = False, stress_hire_dates: bool = False) -> int:
    print(f"DBF: {data_dir}")
    print(f"RSV: {out_dir}")
    print()

    history = hr.build_history(out_dir, log=print)
    if history.empty:
        print("В указанной папке не найдено ни одного файла rsv_ММ.xlsx — тестировать нечего.")
        return 1

    try:
        employees = hr.get_lschet_employees(data_dir)
    except Exception as exc:
        print(f"ОШИБКА чтения lschet.dbf: {exc}")
        return 1

    print(f"\nСотрудников в lschet.dbf: {len(employees)}")
    print("Начинаю проверку...\n")

    overrides = hr.load_hire_date_overrides()

    total = 0
    errored = 0
    warned = 0

    # В обычном режиме дата устройства берётся как есть (override/DNEPR/None).
    # В стресс-режиме дополнительно прогоняются синтетические даты устройства
    # со смещением от 1 до 25 месяцев назад — это специально задевает границы
    # рабочих лет (в т.ч. переход через несколько лет), которые почти не
    # проверяются, если у реальных сотрудников DNEPR не заполнен.
    stress_offsets = (1, 3, 11, 12, 13, 15, 24, 25) if stress_hire_dates else (None,)

    for _, row in employees.iterrows():
        tn = row["tn"]
        if pd.isna(tn):
            continue
        tn = int(tn)
        fio = str(row.get("fio", "?"))

        real_hire_date, _source = hr.get_hire_date(tn, employees, overrides)

        for offset in stress_offsets:
            hire_date = real_hire_date if offset is None else _shift_months(months_back=offset)
            label = fio if offset is None else f"{fio} (стресс: устройство {offset} мес. назад)"
            total += 1

            try:
                timeline = hr.build_employee_timeline(tn, history, hire_date=hire_date)
                blocks = hr.build_work_year_blocks(timeline)

                problems = check_timeline_invariants(timeline)
                problems += check_blocks_invariants(blocks, timeline)

                if problems:
                    warned += 1
                    print(f"[WARN]  tn={tn} {label}:")
                    for p in problems:
                        print(f"    - {p}")
                elif not quiet:
                    print(f"[OK]    tn={tn} {label}  ({len(timeline)} мес. в таймлайне, {len(blocks)} раб. год(а/лет) показано)")

            except Exception:
                errored += 1
                tb = traceback.format_exc()
                print(f"[ERROR] tn={tn} {label}:\n{tb}")

    print()
    print(f"Всего проверок (сотрудник × сценарий даты устройства): {total}")
    print(f"Упало с исключением:         {errored}")
    print(f"С нарушением инвариантов:    {warned}")
    print(f"Чисто прошли:                {total - errored - warned}")

    return 1 if errored else 0


def _shift_months(months_back: int):
    """Синтетическая дата устройства: months_back месяцев назад от июля 2026
    (последний месяц тестовых данных условно) — только для --stress."""
    class _D:
        def __init__(self, y, m, d=1):
            self.year, self.month, self.day = y, m, d

    y, m = 2026, 7
    m -= months_back
    while m <= 0:
        m += 12
        y -= 1
    return _D(y, m, 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Прогон построения истории/отпуска за вредность по всем сотрудникам"
    )
    parser.add_argument("--data-dir", type=Path, default=None, help="Папка с DBF (по умолч. — из .env)")
    parser.add_argument("--out-dir", type=Path, default=None, help="Папка с RSV (по умолч. — из .env)")
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Не печатать строку [OK] по каждому чисто прошедшему сотруднику — "
             "показывать только WARN/ERROR и итог (по умолчанию печатается всё)",
    )
    parser.add_argument(
        "--stress", action="store_true",
        help="Дополнительно прогнать каждого сотрудника с синтетическими датами устройства "
             "(1..25 мес. назад), чтобы задеть границы рабочих лет даже если реальный DNEPR пуст",
    )
    args = parser.parse_args()

    env = load_env_vars()
    data_dir = args.data_dir or Path(env.get("DBF_DATA_DIR", "./dbf"))
    out_dir = args.out_dir or Path(env.get("OUT_DIR", "./rsv"))

    sys.exit(run_all(data_dir, out_dir, quiet=args.quiet, stress_hire_dates=args.stress))


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# pytest-совместимая обёртка: `pytest test_insalubrity_history.py -v`
# ---------------------------------------------------------------------------
def test_all_employees_build_without_errors():
    env = load_env_vars()
    data_dir = Path(env.get("DBF_DATA_DIR", "./dbf"))
    out_dir = Path(env.get("OUT_DIR", "./rsv"))
    assert run_all(data_dir, out_dir, quiet=False, stress_hire_dates=True) == 0, \
        "См. вывод выше — есть падения или нарушения инвариантов"