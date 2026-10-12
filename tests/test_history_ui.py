"""
test_history_ui.py — поведение окна «История»: поиск, статус, пустое состояние,
клавиатура, перенос слов в предупреждениях.
Запуск: pytest tests/test_history_ui.py -v
"""
from __future__ import annotations

from test_ui_settings import hist  # noqa: F401  (общая фикстура: окно с пустыми данными)


def _loaded(make):
    w = make()
    assert w.wait_for_load()
    return w


def test_enter_selects_the_only_partial_match(hist):
    h, make = hist
    w = _loaded(make)
    chosen = []
    w.select_employee = chosen.append
    w.search_input.setText("иван")             # не полное имя из списка, но совпадение одно
    w.on_search_enter()
    assert chosen == [7]
    assert w.search_hint_lbl.isHidden()


def test_enter_with_no_match_says_so_instead_of_staying_silent(hist):
    h, make = hist
    w = _loaded(make)
    chosen = []
    w.select_employee = chosen.append
    w.search_input.setText("яяя")
    w.on_search_enter()
    assert chosen == []
    assert not w.search_hint_lbl.isHidden() and "не найден" in w.search_hint_lbl.text()
    w.search_input.setText("я")                # правка текста убирает устаревшую подсказку
    assert w.search_hint_lbl.isHidden()


def test_saved_confirmation_is_shown_in_status_and_then_reverts(hist):
    h, make = hist
    w = _loaded(make)
    base = w._base_status
    assert base
    w._flash_status("Нормы сохранены")
    assert w.status_lbl.text().startswith("✓") and w.status_lbl.property("mode") == "success"
    w._end_flash()
    assert w.status_lbl.text() == base and w.status_lbl.property("mode") == "idle"
    w._flash_timer.stop()


def test_empty_state_explains_what_to_do_until_an_employee_is_shown(hist):
    h, make = hist
    w = _loaded(make)
    assert not w.empty_lbl.isHidden() and w.table.isHidden()
    assert "ФИО" in w.empty_lbl.text()


def test_ctrl_f_expands_collapsed_top_panel_and_focuses_search(hist):
    h, make = hist
    w = _loaded(make)
    w.set_top_collapsed(True)
    assert w.top_body.isHidden()
    w.focus_search()
    assert not w.top_body.isHidden()


def test_enter_on_year_header_toggles_the_year(hist):
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QColor, QKeyEvent
    h, make = hist
    w = _loaded(make)
    w.table.setRowCount(0)
    header_row = w.add_year_header_row("2020", 3, QColor("#EDF2F7"))
    month_row = w.add_span_row("", "месяц", QColor("#000000"))
    block = {"label": "2020", "header_row": header_row, "month_rows": [month_row], "collapsed": False}
    w.header_row_to_block = {header_row: block}
    w.table.setCurrentCell(header_row, 0)

    press = QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier)
    assert w.eventFilter(w.table, press) is True
    assert block["collapsed"] is True and w.table.isRowHidden(month_row)
    assert "свёрнут" in w.table.item(header_row, 0).data(Qt.AccessibleTextRole)

    assert w.eventFilter(w.table, QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier)) is True
    assert block["collapsed"] is False and not w.table.isRowHidden(month_row)


def test_long_warning_row_wraps_instead_of_being_cut_off(hist):
    from PyQt5.QtGui import QColor
    h, make = hist
    w = _loaded(make)
    w.table.setRowCount(0)
    w._wrapped_rows = []
    text = "очень длинное предупреждение " * 120
    row = w.add_span_row("⚠", text, QColor("#9C4221"), QColor("#FFFAF0"), wrap=True)
    w._fit_wrapped_rows()
    assert w.table.rowHeight(row) > 32                      # строка выросла под перенос слов
    assert w.table.item(row, 1).toolTip() == text           # полный текст доступен и в тултипе


def test_editable_columns_say_so_in_header_tooltips_and_class_is_named_consistently(hist):
    h, make = hist
    w = _loaded(make)
    assert "Двойной клик" in w.table.horizontalHeaderItem(2).toolTip()
    assert "Двойной клик" not in w.table.horizontalHeaderItem(7).toolTip()      # «Итого» — расчётная
    assert h.COLUMN_TITLES[8] == "Класс"
    assert "Балл" not in " ".join(h.COLUMN_TITLES)
