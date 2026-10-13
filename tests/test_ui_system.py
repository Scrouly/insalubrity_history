"""
test_ui_system.py — система дизайна (фаза 3 плана): три ступени текста, шкала шрифтов,
отсутствие неиспользуемых токенов, единые имена вариантов кнопок.
Запуск: pytest tests/test_ui_system.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import ui_tokens as ui

SRC = Path(__file__).resolve().parent.parent / "src"
LIGHT_BACKGROUNDS = (ui.WHITE, ui.APP_BG, ui.GRAY_50, ui.GRAY_100)


def _src(name: str) -> str:
    return (SRC / name).read_text(encoding="utf-8")


# ---- текст: не больше трёх ступеней ---------------------------------------------------------

def test_text_has_exactly_three_steps():
    steps = sorted(n for n in vars(ui) if n.startswith("TEXT") and n.isupper())
    assert steps == ["TEXT", "TEXT_MUTED", "TEXT_SECONDARY"]


@pytest.mark.parametrize("name", ["TEXT", "TEXT_SECONDARY", "TEXT_MUTED"])
@pytest.mark.parametrize("bg", LIGHT_BACKGROUNDS)
def test_every_text_step_is_readable_on_every_light_background(name, bg):
    assert ui.contrast_ratio(getattr(ui, name), bg) >= 4.5


def test_text_steps_get_progressively_lighter():
    lum = [ui.relative_luminance(getattr(ui, n)) for n in ("TEXT", "TEXT_SECONDARY", "TEXT_MUTED")]
    assert lum == sorted(lum) and len(set(lum)) == 3


# ---- шкала шрифтов --------------------------------------------------------------------------

def test_font_scale_is_small_ascending_and_never_below_12px():
    sizes = list(ui.FONT_SIZES.values())
    assert sizes == sorted(sizes) and len(set(sizes)) == len(sizes) <= 6
    assert min(sizes) >= 12


def test_qss_has_no_raw_font_sizes_and_resolves_to_the_scale():
    assert not re.search(r"font-size:\s*\d+px", _src("insalubrity_gui.py"))          # только @FS_*@
    import insalubrity_gui as gui
    used = {int(px) for px in re.findall(r"font-size:\s*(\d+)px", gui.STYLESHEET)}
    assert used <= set(ui.FONT_SIZES.values())


def test_window_code_takes_inline_font_sizes_from_the_scale():
    code = _src("insalubrity_history.py")
    assert not re.search(r"font-size:\s*\d+px", code)


def test_unknown_font_token_is_reported():
    with pytest.raises(ValueError):
        ui.apply_tokens("QLabel { font-size: @FS_HUGE@; }")


# ---- токены без мусора ----------------------------------------------------------------------

def test_every_token_is_used_somewhere():
    sources = {p.name: p.read_text(encoding="utf-8") for p in SRC.glob("*.py")}
    token_file = sources["ui_tokens.py"]
    unused = []
    for name in (n for n in vars(ui) if n.isupper() and not n.startswith("_")):
        outside = sum(len(re.findall(rf"\bui\.{name}\b|@{name}@", text))
                      for key, text in sources.items() if key != "ui_tokens.py")
        inside = len(re.findall(rf"\b{name}\b", token_file)) - 1       # минус определение
        if outside == 0 and inside <= 0 and name != "FONT_SIZES":
            unused.append(name)
    assert unused == []


def test_banner_is_defined_once_not_as_pair_and_parts():
    assert not hasattr(ui, "BANNER")
    assert hasattr(ui, "BANNER_FG") and hasattr(ui, "BANNER_BG")


# ---- кнопки ---------------------------------------------------------------------------------

BUTTON_NAME_CALL = re.compile(r'(\w*(?:btn|button)\w*)\.setObjectName\("(\w+)"\)', re.IGNORECASE)


def test_button_variants_share_one_naming_suffix():
    names = set()
    for fname in ("insalubrity_gui.py", "insalubrity_history.py"):
        text = _src(fname)
        names |= set(re.findall(r"QPushButton#(\w+)", text))
        names |= {m[1] for m in BUTTON_NAME_CALL.findall(text)}
    assert names, "кнопки не найдены"
    assert all(n.endswith("Button") for n in names), sorted(n for n in names if not n.endswith("Button"))


def test_every_button_variant_in_code_is_styled_in_qss():
    import insalubrity_gui as gui
    code = _src("insalubrity_gui.py") + _src("insalubrity_history.py")
    used = {m[1] for m in BUTTON_NAME_CALL.findall(code)}
    assert used
    for name in used:
        assert f"QPushButton#{name}" in gui.STYLESHEET, name


def test_button_variants_are_documented_in_the_token_module():
    doc = ui.__doc__
    for name in ("MainActionButton", "UtilityButton", "BrowseButton", "FileButton", "IconButton", "LinkButton"):
        assert name in doc
