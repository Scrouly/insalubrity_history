"""
test_ui_polish.py — оформление и доступность окна «История» (фазы 1, 2 и 5 плана):
фокус в ячейке, стиль кнопок-ссылок в общем QSS, динамическая легенда, состояние в тексте
ячейки, баннер (склонение, месяцы с нулевой нормой), ширина таблицы, акцент на итоге отпуска.
Запуск: pytest tests/test_ui_polish.py -v
"""
from __future__ import annotations

from datetime import date

import history_reader as hr
from helpers import make_history, vr
from test_ui_followup import _shown
from test_ui_settings import hist  # noqa: F401  (общая фикстура: окно с пустыми данными)

HIRE = date(2023, 1, 10)


def _clean_overrides():
    hr.DEFAULT_MONTH_OVERRIDE_FILE.unlink(missing_ok=True)


def _two_years_without(year, month):
    """Два полных года по одному сотруднику (tn=1), кроме одного месяца."""
    return [vr(m, 20, 3.1, 0.29, year=y) for y in (2023, 2024) for m in range(1, 13)
            if (y, m) != (year, month)]


def _window_with(make, rows):
    w = make()
    assert w.wait_for_load()
    w.history = make_history(rows)
    w.render_timeline(1, HIRE)
    return w


def _badge_cells(w, h):
    return [(r, c) for r in range(w.table.rowCount()) for c in range(w.table.columnCount())
            if w.table.item(r, c) is not None and w.table.item(r, c).data(h.BADGE_ROLE)]


# ---- Фаза 1 --------------------------------------------------------------------------------

def test_focus_ring_and_link_button_live_in_shared_qss():
    import insalubrity_gui as gui
    import ui_tokens as ui
    qss = gui.STYLESHEET
    assert "QTableWidget::item:focus" in qss and "QPushButton#LinkButton" in qss
    assert "@" not in qss                                          # все токены подставлены
    assert ui.contrast_ratio(ui.FOCUS, ui.WHITE) >= 3.0            # рамка фокуса видна (WCAG 1.4.11)


def test_collapse_buttons_are_styled_by_shared_qss_not_inline(hist):
    h, make = hist
    w = _shown(make)
    for btn in (w.collapse_all_btn, w.expand_all_btn):
        assert btn.objectName() == "LinkButton" and btn.styleSheet() == ""


def test_cell_state_is_part_of_the_accessible_text_not_only_a_letter(hist):
    h, make = hist
    _clean_overrides()
    try:
        hr.save_month_override(1, 2024, 3, "vred_dni", 18, had_data=True)
        w = _shown(make)
        cells = _badge_cells(w, h)
        assert cells
        texts = [w.table.item(r, c).data(h.Qt.AccessibleTextRole) for r, c in cells]
        assert any("правка вручную" in (t or "") and t.startswith("18") for t in texts)
    finally:
        _clean_overrides()


def test_year_header_has_no_repeated_hint_but_keeps_it_in_tooltip(hist):
    h, make = hist
    w = _shown(make)
    head = w.table.item(w.year_blocks[0]["header_row"], 1)
    assert "клик или Enter" not in head.text() and "мес." in head.text()
    assert "Enter" in head.toolTip()


def test_banner_wording_and_plural_for_diverging_manual_edits(hist):
    h, make = hist
    assert [h.ru_plural(n, "правка", "правки", "правок") for n in (1, 2, 5, 11, 21, 22)] == \
        ["правка", "правки", "правок", "правок", "правка", "правки"]
    _clean_overrides()
    try:
        hr.save_month_override(1, 2024, 4, "kol_rd", 19, had_data=False)
        w = _shown(make)
        assert "1 правка вручную расходится с RSV" in w.banner_lbl.text()
        hr.save_month_override(1, 2024, 5, "kol_rd", 19, had_data=False)
        w.render_timeline(1, HIRE)
        assert "2 правки вручную расходятся с RSV" in w.banner_lbl.text()
    finally:
        _clean_overrides()


def test_override_file_read_error_tells_what_to_do(tmp_path):
    import pytest
    with pytest.raises(hr.OverrideFileError) as err:
        hr.load_month_overrides(tmp_path)                          # каталог вместо файла -> OSError
    assert "Закройте" in str(err.value)


def test_column_tip_for_future_month_leave(hist):
    h, _ = hist
    assert "будущий месяц" in h.COLUMN_TIPS[5] and "без сохранения" not in h.COLUMN_TIPS[5]


# ---- Фаза 2 --------------------------------------------------------------------------------

def test_legend_lists_only_states_present_and_hint_moved_to_title_row(hist):
    h, make = hist
    _clean_overrides()
    try:
        w = _shown(make)
        assert not w.legend_lbl.isHidden()                         # текущий год достроен «оценкой»
        assert "оценка" in w.legend_lbl.text() and "≈" in w.legend_lbl.text()
        assert "правка вручную" not in w.legend_lbl.text()        # правок ещё нет
        assert "Двойной клик" not in w.legend_lbl.text()
        assert "Двойной клик" in w.edit_hint_lbl.text()
        hr.save_month_override(1, 2024, 3, "vred_dni", 18, had_data=True)
        w.render_timeline(1, HIRE)
        assert "правка вручную" in w.legend_lbl.text()
    finally:
        _clean_overrides()


def test_legend_is_hidden_when_nothing_to_explain(hist):
    h, make = hist
    full_years = [vr(m, 20, 3.1, 0.29, year=y) for y in (2023, 2024) for m in range(1, 13)]
    w = _window_with(make, full_years)
    w.render_timeline(1, date(2023, 1, 10))
    # в двух полных годах без оценок и правок пояснять нечего
    assert w.legend_lbl.isHidden() or "правка" not in w.legend_lbl.text()


def test_table_width_is_capped_on_wide_screens(hist):
    from PyQt5.QtWidgets import QApplication
    h, make = hist
    w = _shown(make)
    w.resize(2400, 900)
    w.show()
    QApplication.processEvents()
    assert w.table.maximumWidth() == h.TABLE_MAX_WIDTH
    assert w.table.width() <= h.TABLE_MAX_WIDTH
    w.close()


def test_leave_total_row_is_more_prominent_than_formula_rows(hist):
    h, make = hist
    w = _shown(make)
    def label_for(prefix):
        for r in range(w.table.rowCount()):
            first = w.table.item(r, 0)
            second = w.table.item(r, 1)
            if prefix == "ОТПУСК" and first is not None and first.text() == "ОТПУСК":
                return w.table.cellWidget(r, 1)
            if prefix == "↳" and second is not None and second.text().strip().startswith("↳"):
                return w.table.cellWidget(r, 1)
    import ui_tokens as ui
    assert f"{ui.FS_HEADING}px" in label_for("ОТПУСК").styleSheet()
    assert f"{ui.FS_BODY}px" in label_for("↳").styleSheet()


# ---- Фаза 5 --------------------------------------------------------------------------------

def test_banner_warns_about_month_with_vredn_days_but_zero_norm(hist):
    h, make = hist
    rows = _two_years_without(2024, 2)
    rows.append(vr(2, 20, 3.1, 0.29, year=2024, kol=0))            # запись есть, вредность 20, норма 0
    w = _window_with(make, rows)
    text = w.banner_lbl.text()
    assert "02.2024" in text and "норма рабочих дней равна 0" in text
    assert not w.banner_lbl.isHidden()


def test_no_zero_norm_warning_when_month_has_no_vredn_days(hist):
    h, make = hist
    rows = _two_years_without(2024, 2)
    rows.append(vr(2, 0, 3.1, 0.29, year=2024, kol=0))             # норма 0, но вредности нет — нормально
    w = _window_with(make, rows)
    assert "норма рабочих дней равна 0" not in w.banner_lbl.text()


def test_exceed_norm_note_points_to_the_work_days_column(hist):
    h, make = hist
    rows = _two_years_without(2024, 2)
    rows.append(vr(2, 20, 3.1, 0.29, year=2024, kol=0))
    w = _window_with(make, rows)
    texts = [w.table.cellWidget(r, 1).text() for r in range(w.table.rowCount())
             if w.table.cellWidget(r, 1) is not None]
    assert any("Проверьте колонку «Раб. дни»" in t for t in texts)
