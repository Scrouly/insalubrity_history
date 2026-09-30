"""
find_zero_kol_rd_months.py
===========================
Отчёт: у каких сотрудников и в каких месяцах сработала автопочинка
"kol_rd=0 при has_data=True" (см. history_reader.fix_zero_kol_rd_months) —
то есть за месяц ЕСТЬ реальная RSV-запись, но норма рабочих дней по графику
изначально была 0 (сбой сопоставления с kalend.dbf), и её заменили средним.

Никакой отдельной логики поиска не пишет — просто вызывает
build_employee_timeline() для каждого сотрудника (ровно ту же функцию, что
использует GUI) и смотрит на флаг is_data_fix в результате.

Запуск (пути берутся из .env — того же файла, что использует GUI):
    python find_zero_kol_rd_months.py
    python find_zero_kol_rd_months.py --data-dir ./dbf --out-dir ./rsv
    python find_zero_kol_rd_months.py --csv report.csv    # + сохранить в CSV
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

import history_reader as hr
from app_env import load_env_vars


def find_all(data_dir: Path, out_dir: Path) -> pd.DataFrame:
    print(f"DBF: {data_dir}")
    print(f"RSV: {out_dir}")
    print()

    history = hr.build_history(out_dir, log=print)
    if history.empty:
        print("В указанной папке не найдено ни одного файла rsv_ММ.xlsx.")
        return pd.DataFrame()

    try:
        employees = hr.get_lschet_employees(data_dir)
    except Exception as exc:
        print(f"ОШИБКА чтения lschet.dbf: {exc}")
        # Без lschet ФИО не подтянуть, но саму проверку можно продолжить по
        # одним таб. номерам, которые встречаются в истории.
        employees = pd.DataFrame(columns=["tn", "fio", "dnepr"])

    overrides = hr.load_hire_date_overrides()
    all_tns = sorted(int(tn) for tn in history["tn"].dropna().unique())

    print(f"Сотрудников в истории (RSV): {len(all_tns)}")
    print("Проверяю...\n")

    found_rows = []

    for tn in all_tns:
        fio_match = employees.loc[employees["tn"] == tn, "fio"]
        fio = str(fio_match.iloc[0]) if not fio_match.empty else "(нет в lschet.dbf)"

        hire_date, _source = hr.get_hire_date(tn, employees, overrides)
        termination_date, _term_source = hr.get_termination_date(tn, employees, hire_date)
        timeline = hr.build_employee_timeline(
            tn, history, hire_date=hire_date, termination_date=termination_date
        )
        if timeline.empty or "is_data_fix" not in timeline.columns:
            continue

        fixed = timeline.loc[timeline["is_data_fix"]]
        for _, row in fixed.iterrows():
            found_rows.append({
                "tn": tn,
                "fio": fio,
                "год": int(row["year"]),
                "месяц": int(row["month"]),
                "kol_rd_было": 0,
                "kol_rd_стало": round(float(row["kol_rd"]), 2),
                "vred_dni (не тронуто)": row["vred_dni"],
                "пояснение": row.get("data_fix_note", ""),
            })

    report = pd.DataFrame(found_rows)

    print()
    if report.empty:
        print("Ни одного сбойного месяца (kol_rd=0 при has_data=True) не найдено — всё чисто.")
    else:
        affected_people = report["tn"].nunique()
        print(f"Найдено сбойных месяцев: {len(report)}  (у {affected_people} сотрудник(ов))")
        print()
        with pd.option_context("display.max_rows", None, "display.width", 160):
            print(report[["tn", "fio", "год", "месяц", "kol_rd_было", "kol_rd_стало"]]
                  .sort_values(["tn", "год", "месяц"]).to_string(index=False))

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Найти сотрудников/месяцы, где сработала автопочинка kol_rd=0 при реальных RSV-данных"
    )
    parser.add_argument("--data-dir", type=Path, default=None, help="Папка с DBF (по умолч. — из .env)")
    parser.add_argument("--out-dir", type=Path, default=None, help="Папка с RSV (по умолч. — из .env)")
    parser.add_argument("--csv", type=Path, default=None, help="Сохранить полный отчёт в CSV по этому пути")
    args = parser.parse_args()

    env = load_env_vars()
    data_dir = args.data_dir or Path(env.get("DBF_DATA_DIR", "./dbf"))
    out_dir = args.out_dir or Path(env.get("OUT_DIR", "./rsv"))

    report = find_all(data_dir, out_dir)

    if args.csv is not None and not report.empty:
        report.to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"\nСохранено в {args.csv}")

    sys.exit(0)  # это отчёт, не тест — код возврата всегда 0


if __name__ == "__main__":
    main()
