"""
ui_tokens.py
============
Единственное место, где заданы цвета интерфейса (и калькулятора, и окна истории).
Раньше значения были разбросаны по QSS и по коду (`QColor("#...")` в десятках мест),
из-за чего часть пар «текст/фон» не проходила контраст WCAG 2.1 AA.

Правила:
  * пары «текст на фоне» держим парами (fg, bg) и проверяем тестом
    tests/test_ui_tokens.py: обычный текст >= 4.5:1, границы полей >= 3:1;
  * серый #A0AEC0 (GRAY_400) — только для декора и отключённых элементов,
    для читаемого текста его использовать нельзя (2.2:1 на белом);
  * смысл статуса нельзя передавать одним цветом: у каждого статуса ячейки есть
    ещё буква-метка (см. STATUS_BADGES) и пояснение в легенде.

Модуль не зависит от Qt — его можно импортировать в тестах и скриптах.
"""

from __future__ import annotations

# --- Нейтральная шкала -------------------------------------------------------
WHITE = "#FFFFFF"
APP_BG = "#F5F6F8"          # фон окна
GRAY_50 = "#F7FAFC"
GRAY_100 = "#EDF2F7"
GRAY_150 = "#F1F5F9"        # мини-шапка года
GRAY_200 = "#E2E8F0"
GRAY_300 = "#CBD5E0"
GRAY_400 = "#A0AEC0"        # ТОЛЬКО декор / disabled
GRAY_500 = "#718096"        # hover границ, тонкие акценты (не для мелкого текста на сером)
GRAY_700 = "#2D3748"
GRAY_900 = "#1A202C"

# --- Текст -------------------------------------------------------------------
TEXT = GRAY_900
TEXT_SECONDARY = "#4A5568"  # подписи полей, заголовки колонок
TEXT_MUTED = "#5A6678"      # пояснения, подписи-подсказки (>= 4.7:1 на всех светлых фонах)
TEXT_FAINT = "#667085"      # «нет данных»: приглушённо, но читаемо (4.5:1+ на белом/серых строках)

# --- Границы -----------------------------------------------------------------
BORDER_SUBTLE = GRAY_200            # рамки карточек (контейнеры, не органы управления)
BORDER_FIELD = "#8A94A6"            # рамка поля ввода: 3.06:1 на белом (WCAG 1.4.11)
BORDER_FIELD_HOVER = GRAY_500       # 4.0:1
BORDER_BUTTON = GRAY_300

# --- Акцент / фокус ----------------------------------------------------------
PRIMARY = "#2B6CB0"         # белый текст на нём — 5.4:1
PRIMARY_HOVER = "#2C5282"
PRIMARY_PRESSED = "#2A4365"
FOCUS = PRIMARY
SELECTION = "#BEE3F8"
HOVER_COLUMN_RGBA = (43, 108, 176, 30)   # подсветка колонки под курсором

# --- Статусы ячеек таблицы: (цвет текста, цвет фона) --------------------------
STATUS_OVERRIDE = ("#7B341E", "#FBD38D")    # ручная правка кадровика
STATUS_STALE = ("#742A2A", "#FEB2B2")       # правка расходится с появившимся RSV
STATUS_CARRIED = ("#553C9A", "#E9D8FD")     # класс перенесён с прошлого месяца
STATUS_PROJECTED = ("#276749", "#EDFDF3")   # строка-оценка (месяца ещё нет в RSV)

# Буква-метка в углу ячейки: статус виден и без различения цветов.
STATUS_BADGES = {
    "override": "Р",
    "stale": "!",
    "carried": "→",
}

# --- Строки-аннотации и итоги: (цвет текста, цвет фона) -----------------------
NOTE_WARN = ("#9C4221", "#FFFAF0")          # предупреждения расчёта
NOTE_NOTICE = ("#975A16", "#FFFBEB")        # «не учтено в расчёте»
NOTE_CLASS_CHANGE = ("#553C9A", "#FAF5FF")  # смена класса в месяце
NOTE_PLAIN = (TEXT_SECONDARY, GRAY_50)      # разбор по классам
SUMMARY = ("#2C5282", "#EBF8FF")            # ИТОГО и «Отпуск за вредность»
BANNER_FG = "#744210"                       # плашка важных предупреждений над таблицей
BANNER_BG = "#FFF5D6"
BANNER_BORDER = "#D69E2E"
BANNER = (BANNER_FG, BANNER_BG)
MINI_HEADER = (TEXT_MUTED, GRAY_150)        # мини-шапка колонок внутри года
YEAR_ROW_TINTS = (WHITE, GRAY_50)           # чередование фона по рабочим годам
YEAR_HEADER_TINTS = (GRAY_100, GRAY_200)    # заголовки рабочих лет
DIVIDER = GRAY_200

# --- Статус-плашка (StatusPill) ------------------------------------------------
PILL_IDLE_FG, PILL_IDLE_BG, PILL_IDLE_BORDER = TEXT_MUTED, GRAY_100, GRAY_200
PILL_SUCCESS_FG, PILL_SUCCESS_BG, PILL_SUCCESS_BORDER = "#276749", "#F0FFF4", "#9AE6B4"
PILL_WORKING_FG, PILL_WORKING_BG, PILL_WORKING_BORDER = "#2C5282", "#EBF8FF", "#90CDF4"
PILL_ERROR_FG, PILL_ERROR_BG, PILL_ERROR_BORDER = "#C53030", "#FFF5F5", "#FEB2B2"


# --- Контраст по WCAG 2.1 -----------------------------------------------------
def _channel(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(fg: str, bg: str) -> float:
    a, b = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def tokens() -> dict:
    """Все строковые токены-цвета (для подстановки в QSS: @ИМЯ@)."""
    return {k: v for k, v in globals().items() if k.isupper() and isinstance(v, str) and v.startswith("#")}


def apply_tokens(template: str) -> str:
    """Подставляет токены в QSS-шаблон: `@PRIMARY@` -> `#2B6CB0`.
    Длинные имена идут первыми, чтобы GRAY_50 не портил GRAY_500."""
    result = template
    for name in sorted(tokens(), key=len, reverse=True):
        result = result.replace(f"@{name}@", tokens()[name])
    if "@" in result:
        left = result[result.index("@"):][:40]
        raise ValueError(f"В QSS остался неподставленный токен: {left!r}")
    return result
