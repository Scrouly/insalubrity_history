"""
test_ui_followup.py — доработки окна «История» после UI-прохода: формулировки, запятая,
«свернуть/развернуть все», стрелки на годе, порядок Tab, период в ИТОГО.
Запуск: pytest tests/test_ui_followup.py -v
"""
from __future__ import annotations

from datetime import date

from helpers import make_history, vr
from test_ui_settings import hist  # noqa: F401  (общая фикстура: окно с пустыми данными)


def _shown(make):
    """Окно с тремя рабочими годами одного сотрудника (tn=1), дата приёма 10.01.2023."""
    w = make()
    assert w.wait_for_load()
    rows = [vr(m, 20, 3.1, 0.29, year=y) for y in (2023, 2024) for m in range(1, 13)]
    rows += [vr(m, 20, 3.1, 0.29, year=2025) for m in range(1, 7)]
    w.history = make_history(rows)
    w.render_timeline(1, date(2023, 1, 10))
    return w


def _all_texts(w):
    return [w.table.item(r, c).text() for r in range(w.table.rowCount())
            for c in range(w.table.columnCount()) if w.table.item(r, c) is not None]


def test_wording_says_hire_date_and_accrual_not_jargon(hist):
    h, make = hist
    w = _shown(make)
    texts = " | ".join(_all_texts(w))
    assert "норма за год" in texts and "начислено пропорционально" in texts
    assert "положено" not in texts and "вышло" not in texts
    for label in h.SOURCE_LABELS.values():
        assert not label or "DNEPR" not in label
    for label in h.TERMINATION_SOURCE_LABELS.values():
        assert not label or "DATA_UVL" not in label
    assert [h.COLUMN_TITLES[c] for c in (3, 6)] == ["Вредность", "По среднему"]


def test_hire_date_is_called_hire_date_everywhere_in_the_window(hist):
    h, make = hist
    w = _shown(make)
    from PyQt5.QtWidgets import QLabel
    assert w.hire_date_edit.accessibleName() == "Дата приёма на работу"
    labels = " | ".join(lbl.text() for lbl in w.findChildren(QLabel))
    assert "Дата приёма на работу" in labels and "устройства" not in labels
    w.select_employee(7)
    assert "дата приёма" in w.hire_source_lbl.text() and "устройства" not in w.hire_source_lbl.text()


def test_numbers_are_shown_with_decimal_comma(hist):
    h, make = hist
    assert h.fmt_num(3.81) == "3,81" and h.fmt_num(0.5, 1) == "0,5"
    w = _shown(make)
    tariffs = [w.table.item(r, 9).text() for r in range(w.table.rowCount())
               if w.table.item(r, 9) is not None and w.table.item(r, 9).text()[:1].isdigit()]
    assert tariffs and all("," in t and "." not in t for t in tariffs)
    import re
    rows = [t for t in _all_texts(w) if "↳" in t]
    assert rows and not any(re.search(r"=\s*\d+\.\d", t) for t in rows)      # «= 4,00», а не «= 4.00»


def test_year_total_row_shows_a_period_that_fits_the_month_column(hist):
    h, make = hist
    w = _shown(make)
    total_rows = [r for r in range(w.table.rowCount()) if w.table.item(r, 0) and w.table.item(r, 0).text() == "ИТОГО"]
    assert total_rows
    item = w.table.item(total_rows[0], 1)
    assert "…" not in item.text() and len(item.text()) <= 11          # «01.23–12.23»
    assert "2023" in item.toolTip()                                     # полный период — в тултипе


def test_tariff_column_is_left_aligned_next_to_class(hist):
    from PyQt5.QtCore import Qt
    h, make = hist
    w = _shown(make)
    assert w.COLUMN_ALIGN[9] & Qt.AlignLeft and w.COLUMN_ALIGN[8] & Qt.AlignRight


def test_collapse_all_and_expand_all_buttons(hist):
    h, make = hist
    w = _shown(make)
    assert len(w.year_blocks) >= 3
    w.collapse_all_btn.click()
    assert all(b["collapsed"] for b in w.year_blocks)
    assert all(w.table.isRowHidden(r) for b in w.year_blocks for r in b["month_rows"])
    w.expand_all_btn.click()
    assert not any(b["collapsed"] for b in w.year_blocks)


def test_left_and_right_arrows_collapse_and_expand_the_current_year(hist):
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QKeyEvent
    h, make = hist
    w = _shown(make)
    block = w.year_blocks[0]
    w.set_block_collapsed(block, False)
    w.table.setCurrentCell(block["header_row"], 0)
    assert w.eventFilter(w.table, QKeyEvent(QEvent.KeyPress, Qt.Key_Left, Qt.NoModifier)) is True
    assert block["collapsed"] is True
    assert w.eventFilter(w.table, QKeyEvent(QEvent.KeyPress, Qt.Key_Right, Qt.NoModifier)) is True
    assert block["collapsed"] is False
    # на обычной ячейке стрелки работают как обычно (событие не перехватывается)
    w.table.setCurrentCell(block["month_rows"][1], 2)
    assert w.eventFilter(w.table, QKeyEvent(QEvent.KeyPress, Qt.Key_Left, Qt.NoModifier)) is False


def test_tab_order_goes_settings_then_employee_then_table(hist):
    h, make = hist
    w = _shown(make)
    order = []
    widget = w.settings_btn
    for _ in range(80):
        order.append(widget)
        widget = widget.nextInFocusChain()
        if widget is w.settings_btn:
            break
    wanted = [w.settings_btn, w.search_input, w.hire_date_edit, w.save_hire_btn,
              w.collapse_all_btn, w.expand_all_btn, w.table]
    positions = [order.index(x) for x in wanted]
    assert positions == sorted(positions)


def test_there_is_exactly_one_refresh_button_even_with_settings_open(hist):
    from PyQt5.QtWidgets import QPushButton
    h, make = hist
    w = _shown(make)
    w.toggle_paths_panel()                                     # панель настроек открыта
    refreshers = [b for b in w.findChildren(QPushButton) if "Обновить данные" in b.text()]
    assert len(refreshers) == 1 and not refreshers[0].isHidden()
    assert refreshers[0].toolTip().endswith("(F5)")            # остался тот, что рядом со сводкой путей


# --- «А»: автоподстановка раб. дней при kol_rd=0 в RSV (has_data=True) отменена ---------------

def _zero_norm_history():
    rows = [vr(m, 20, 3.1, 0.29, year=2025) for m in range(1, 13) if m != 2]
    rows.append(vr(2, 0, 3.1, 0.29, year=2025, kol=0))        # в RSV запись есть, а норма дней = 0
    return make_history(rows)


def test_month_with_record_but_zero_norm_keeps_zero_and_is_not_marked_fixed():
    import history_reader as hr
    tl = hr.build_employee_timeline(1, _zero_norm_history(), hire_date=date(2025, 1, 10))
    feb = tl[(tl["year"] == 2025) & (tl["month"] == 2)].iloc[0]
    assert bool(feb["has_data"]) and feb["kol_rd"] == 0         # осталось как в RSV, не среднее
    assert not tl["is_data_fix"].any()                          # метки «А» нет нигде


def test_zero_norm_month_changes_the_yearly_denominator_as_in_rsv():
    import history_reader as hr
    tl = hr.build_employee_timeline(1, _zero_norm_history(), hire_date=date(2025, 1, 10))
    block = hr.build_work_year_blocks(tl)[0]
    assert block["kol_rd_total"] == 11 * 20                     # без подставленных 20 дней за февраль


def test_months_without_any_record_are_still_estimated_as_projected():
    import history_reader as hr
    rows = [vr(m, 20, 3.1, 0.29, year=2025) for m in range(1, 13) if m != 5]    # мая в RSV нет совсем
    tl = hr.build_employee_timeline(1, make_history(rows), hire_date=date(2025, 1, 10))
    may = tl[(tl["year"] == 2025) & (tl["month"] == 5)].iloc[0]
    assert bool(may["is_projected"]) and may["kol_rd"] == 20    # вторая функция fix_zero осталась


def test_window_has_no_auto_fix_legend_or_cell_accent(hist):
    h, make = hist
    w = make()
    assert w.wait_for_load()
    w.history = _zero_norm_history()
    w.render_timeline(1, date(2025, 1, 10))
    from PyQt5.QtWidgets import QLabel
    assert not any("исправлены автоматически" in lbl.text() for lbl in w.findChildren(QLabel))
    assert "А" not in h.ui.STATUS_BADGES.values()
