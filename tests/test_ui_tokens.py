"""
test_ui_tokens.py — цвета интерфейса: контраст по WCAG 2.1 AA и отсутствие «голых» цветов.
Запуск: pytest tests/test_ui_tokens.py -v

Qt здесь не нужен: проверяются сами токены (src/ui_tokens.py) и исходники интерфейса.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import ui_tokens as ui

SRC = Path(__file__).resolve().parent.parent / "src"

# (цвет текста, фон) — обычный текст: >= 4.5:1
TEXT_PAIRS = [
    ("основной на белом", ui.TEXT, ui.WHITE),
    ("основной на фоне окна", ui.TEXT, ui.APP_BG),
    ("основной на выделении", ui.TEXT, ui.SELECTION),
    ("подписи полей на белом", ui.TEXT_SECONDARY, ui.WHITE),
    ("подписи полей на фоне окна", ui.TEXT_SECONDARY, ui.APP_BG),
    ("заголовки колонок", ui.TEXT_SECONDARY, ui.GRAY_50),
    ("пояснения на фоне окна", ui.TEXT_MUTED, ui.APP_BG),
    ("пояснения на белом", ui.TEXT_MUTED, ui.WHITE),
    ("пояснения на светлой строке", ui.TEXT_MUTED, ui.GRAY_50),
    ("пояснения на сером", ui.TEXT_MUTED, ui.GRAY_100),
    ("«нет данных» на белой строке", ui.TEXT_FAINT, ui.WHITE),
    ("«нет данных» на тонированной строке", ui.TEXT_FAINT, ui.GRAY_50),
    ("белый на основной кнопке", ui.WHITE, ui.PRIMARY),
    ("белый на основной кнопке (hover)", ui.WHITE, ui.PRIMARY_HOVER),
    ("белый на основной кнопке (pressed)", ui.WHITE, ui.PRIMARY_PRESSED),
    ("мини-шапка года", *ui.MINI_HEADER),
    ("ручная правка", *ui.STATUS_OVERRIDE),
    ("устаревшая правка", *ui.STATUS_STALE),
    ("класс перенесён", *ui.STATUS_CARRIED),
    ("оценка (прогноз)", *ui.STATUS_PROJECTED),
    ("предупреждение", *ui.NOTE_WARN),
    ("«не учтено»", *ui.NOTE_NOTICE),
    ("смена класса", *ui.NOTE_CLASS_CHANGE),
    ("разбор по классам", *ui.NOTE_PLAIN),
    ("итоги и отпуск", *ui.SUMMARY),
    ("плашка предупреждений", *ui.BANNER),
    ("плашка: бездействие", ui.PILL_IDLE_FG, ui.PILL_IDLE_BG),
    ("плашка: успех", ui.PILL_SUCCESS_FG, ui.PILL_SUCCESS_BG),
    ("плашка: работа", ui.PILL_WORKING_FG, ui.PILL_WORKING_BG),
    ("плашка: ошибка", ui.PILL_ERROR_FG, ui.PILL_ERROR_BG),
]

# Элементы интерфейса без текста (рамка поля, фокус): >= 3:1 (WCAG 1.4.11)
NON_TEXT_PAIRS = [
    ("рамка поля на белом", ui.BORDER_FIELD, ui.WHITE),
    ("рамка поля при наведении", ui.BORDER_FIELD_HOVER, ui.WHITE),
    ("рамка фокуса на белом", ui.FOCUS, ui.WHITE),
    ("рамка фокуса на фоне окна", ui.FOCUS, ui.APP_BG),
]


@pytest.mark.parametrize("name,fg,bg", TEXT_PAIRS, ids=[p[0] for p in TEXT_PAIRS])
def test_text_contrast_is_at_least_4_5(name, fg, bg):
    assert ui.contrast_ratio(fg, bg) >= 4.5, f"{name}: {fg} на {bg} = {ui.contrast_ratio(fg, bg):.2f}:1"


@pytest.mark.parametrize("name,fg,bg", NON_TEXT_PAIRS, ids=[p[0] for p in NON_TEXT_PAIRS])
def test_non_text_contrast_is_at_least_3(name, fg, bg):
    assert ui.contrast_ratio(fg, bg) >= 3.0, f"{name}: {fg} на {bg} = {ui.contrast_ratio(fg, bg):.2f}:1"


def test_contrast_formula_matches_wcag_reference_values():
    assert ui.contrast_ratio("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert ui.contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)


def test_status_badges_are_distinct_so_color_is_not_the_only_cue():
    badges = list(ui.STATUS_BADGES.values())
    assert len(badges) == len(set(badges)) == len(ui.STATUS_BADGES) == 3   # Р, !, →


def test_every_qss_token_is_resolved_and_no_raw_colors_remain():
    gui = (SRC / "insalubrity_gui.py").read_text(encoding="utf-8")
    template = re.search(r'_QSS_TEMPLATE = """\n(.*?)\n"""', gui, re.S).group(1)
    assert re.findall(r"#[0-9A-Fa-f]{6}\b", template) == []          # все цвета — токены
    resolved = ui.apply_tokens(template)                              # не бросает: токены существуют
    assert "@" not in resolved


def test_unknown_token_in_qss_is_reported():
    with pytest.raises(ValueError):
        ui.apply_tokens("QLabel { color: @NO_SUCH_TOKEN@; }")


def test_history_window_has_no_hardcoded_colors():
    text = (SRC / "insalubrity_history.py").read_text(encoding="utf-8")
    assert re.findall(r'QColor\("#|#[0-9A-Fa-f]{6}\b', text) == []
