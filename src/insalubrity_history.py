"""
insalubrity_history.py
=======================
Отдельное приложение для кадровика: поиск сотрудника по ФИО и просмотр
помесячной/годовой истории по вредности на основе уже сформированных
файлов RSV (insalubrity.py). Никакой отдельной базы данных не ведётся —
данные каждый раз читаются заново из папки с результатами.

Использует те же настройки (.env), что и основной калькулятор
insalubrity_gui.py — папки не нужно указывать повторно.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
import re

from PyQt5.QtCore import (
    QCoreApplication, QDate, QEvent, QRect, QSettings, QStringListModel, Qt, QThread, QTimer, pyqtSignal,
)
from PyQt5.QtGui import QColor, QFont, QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QCompleter,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_env import EnvFileError, data_dir, install_excepthook, load_env_vars, migrate_legacy_data, save_env_vars
from version import __version__
from insalubrity_gui import STYLESHEET
import ui_tokens as ui

import history_reader as hr

APP_TITLE = "Расчёт отпуска за вредность"

MONTHS_RU_SHORT = [
    "", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
]

# Метка «эта ячейка — часть сетки данных» (месячные строки, ИТОГО, мини-шапка года):
# только у таких ячеек рисуются явные вертикальные линии и подсветка колонки под курсором.
GRID_ROLE = Qt.UserRole + 1
# Буква-метка статуса в углу ячейки («Р» — ручная правка и т.д.) и её цвет: статус виден
# не только по заливке (WCAG 1.4.1 — цвет не должен быть единственным признаком).
BADGE_ROLE = Qt.UserRole + 2
BADGE_COLOR_ROLE = Qt.UserRole + 3

# Единые названия колонок: и в верхней шапке, и в мини-шапке каждого рабочего года.
# Однострочные — двухстрочный текст не влезал в шапку и обрезался; пояснения — в тултипе.
COLUMN_TITLES = ["Год", "Месяц", "Раб. дни", "Вредность", "Отпуск", "О/б/м", "По среднему", "Итого", "Класс", "Тариф"]
COLUMN_TIPS = [
    "Год", "Месяц",
    "Рабочие дни по графику (норма месяца)",
    "Дни работы во вредных условиях",
    "Дни ежегодного отпуска",
    "Отпуск без сохранения / за свой счёт (О/б/м)",
    "Дни, оплачиваемые по среднему",
    "Итого дней вредности за месяц (расчётное)",
    "Класс вредности: 3.1 / 3.2 / 3.3",
    "Тариф",
]
# Колонки, которые кадровик может править двойным кликом (см. HistoryWindow.EDITABLE_COLUMNS).
EDIT_HINT = "\nДвойной клик — править; очистить ячейку — вернуть значение из RSV."
for _col in (2, 3, 4, 5, 6, 8):
    COLUMN_TIPS[_col] += EDIT_HINT

SOURCE_LABELS = {
    "override": "указана кадровиком вручную",
    "dnepr": "из карточки сотрудника",
    "dnepr_invalid": "в карточке неправдоподобная дата приёма — проигнорирована, укажите вручную",
    None: "не указана — таймлайн начат с первого найденного расчёта",
}

TERMINATION_SOURCE_LABELS = {
    "data_uvl": "по карточке сотрудника",
    "data_uvl_invalid": "в карточке неправдоподобная дата увольнения — проигнорирована",
    "data_uvl_before_hire": "в карточке есть более ранняя дата увольнения — проигнорирована (похоже на переприём)",
    None: None,
}


def fmt_num(value: float, digits: int = 2) -> str:
    """Число для показа: десятичная ЗАПЯТАЯ, как принято в русской документации."""
    return f"{value:.{digits}f}".replace(".", ",")


def format_fio(fio: str) -> str:
    """ФИО в базе хранится ЗАГЛАВНЫМИ — приводим к обычному регистру для
    отображения (Иванов Иван Иванович), с учётом двойных фамилий через дефис."""
    if not fio:
        return fio
    return re.sub(r"[^\s\-]+", lambda m: m.group(0).capitalize(), fio.lower())


class CompactCellDelegate(QStyledItemDelegate):
    """Редактор ячейки, который ровно вписывается в её границы.

    Общий QSS для QLineEdit (padding 9px 12px, min-height 20px, скругление 8px)
    рассчитан на поля формы, а в строке таблицы высотой ~32px такой редактор
    получается выше ячейки и вылезает за её края. Здесь у редактора свой
    компактный стиль, а геометрия принудительно равна прямоугольнику ячейки.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hover_col = -1  # колонка под курсором (подсвечивается в строках данных)
        self._badge_font = QFont()
        self._badge_font.setBold(True)
        self._badge_font.setPixelSize(10)

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        badge = index.data(BADGE_ROLE)
        if badge:
            painter.save()
            painter.setFont(self._badge_font)
            painter.setPen(QColor(index.data(BADGE_COLOR_ROLE) or ui.TEXT))
            r = option.rect
            painter.drawText(QRect(r.left() + 4, r.top() + 1, 16, 13), Qt.AlignLeft | Qt.AlignTop, str(badge))
            painter.restore()
        if not index.data(GRID_ROLE):
            return
        r = option.rect
        painter.save()
        if index.column() == self.hover_col:
            painter.fillRect(r, QColor(*ui.HOVER_COLUMN_RGBA))
        painter.setPen(QColor(ui.GRAY_300))  # явная вертикальная линия между колонками
        painter.drawLine(r.right(), r.top(), r.right(), r.bottom())
        painter.restore()

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        editor.setStyleSheet(
            "QLineEdit {"
            " padding: 0px 8px; min-height: 0px; margin: 0px;"
            f" border: 2px solid {ui.FOCUS}; border-radius: 0px;"
            f" background: {ui.WHITE}; color: {ui.TEXT}; font-size: 13px;"
            f" selection-background-color: {ui.PRIMARY}; selection-color: {ui.WHITE};"
            "}"
        )
        return editor

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


UI_SETTINGS_FILE = "ui_settings.ini"
_REGISTRY_ORG, _REGISTRY_APP = "Dolomit", "InsalubrityHistory"


def ui_settings() -> QSettings:
    """Настройки интерфейса (размер/положение окна, ширины колонок, свёрнутая панель).

    Лежат ФАЙЛОМ в папке данных пользователя (рядом с .env и правками), а не в реестре:
    они не зависят от обновления программы, их видно и можно скопировать/восстановить,
    а тесты (у которых своя временная папка данных) больше не перезаписывают настройки
    разработчика — раньше при каждом прогоне тестов (в том числе в build.bat) реальные
    настройки окна затирались настройками тестового окна."""
    folder = data_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return QSettings(str(folder / UI_SETTINGS_FILE), QSettings.IniFormat)


def migrate_ui_settings_from_registry() -> bool:
    """Один раз переносит прежние настройки интерфейса из реестра в файл.
    Ничего не делает, если файл уже есть, в реестре пусто или идут тесты."""
    if os.environ.get("INSALUBRITY_TESTING"):
        return False
    if (data_dir() / UI_SETTINGS_FILE).exists():
        return False
    old = QSettings(_REGISTRY_ORG, _REGISTRY_APP)
    keys = old.allKeys()
    if not keys:
        return False
    new = ui_settings()
    for key in keys:
        new.setValue(key, old.value(key))
    new.sync()
    return True


class DataLoadWorker(QThread):
    """Читает все RSV-файлы и список сотрудников в фоне, чтобы окно не «зависало»
    на время чтения (раньше это делалось в главном потоке)."""

    # history, employees (или None), список сообщений, текст ошибки чтения lschet ("" — нет)
    loaded = pyqtSignal(object, object, object, str)

    def __init__(self, out_dir: Path, data_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.out_dir = out_dir
        self.data_dir = data_dir

    def run(self) -> None:
        messages: list[str] = []
        try:
            history = hr.build_history(self.out_dir, log=messages.append)
        except Exception as exc:  # не даём упасть потоку: показываем как ошибку чтения
            history = hr.empty_history()
            messages.append(f"ОШИБКА чтения папки RSV {self.out_dir}: {exc}")
        employees = None
        error = ""
        try:
            employees = hr.get_lschet_employees(self.data_dir)
        except Exception as exc:
            error = str(exc)
        self.loaded.emit(history, employees, messages, error)


class HistoryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_TITLE} — v{__version__}")
        self.setStyleSheet(STYLESHEET)

        self.env_data = load_env_vars()
        self.employees = None          # DataFrame tn/fio/dnepr
        self.history = None            # DataFrame по всем rsv-файлам
        self.display_to_tn: dict[str, int] = {}
        self.current_tn: int | None = None
        self.current_source: str | None = None
        self.current_hire_date = None
        self._suppress_item_changed = False
        self.year_blocks: list[dict] = []
        self._base_status = ""
        self._early_warning = ""
        self.current_termination_date = None
        self.current_termination_source = None
        self.header_row_to_block: dict[int, dict] = {}
        self._wrapped_rows: list[tuple[int, QLabel]] = []   # строки-аннотации с переносом слов (row, label)
        self._fitting_rows = False
        self._load_messages: list[str] = []
        self._flash_text = ""

        self._loader: DataLoadWorker | None = None
        self._reload_pending = False
        self._ui_ready = False
        self._ui_save_timer = QTimer(self)
        self._ui_save_timer.setSingleShot(True)
        self._ui_save_timer.setInterval(1000)
        self._ui_save_timer.timeout.connect(self.save_ui_state)
        self._flash_timer = QTimer(self)      # временное «✓ Сохранено…» в строке статуса
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(6000)
        self._flash_timer.timeout.connect(self._end_flash)

        self.build_ui()
        self.restore_window_state()
        self.table.horizontalHeader().sectionResized.connect(self.schedule_ui_save)
        self.main_splitter.splitterMoved.connect(self.schedule_ui_save)
        self._ui_ready = True      # до этого момента изменения размеров — это сборка окна, не выбор пользователя
        self.reload_data()

    def restore_window_state(self) -> None:
        settings = ui_settings()
        geometry = settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            # Первый запуск — окно покрупнее по умолчанию, чтобы таблице сразу
            # хватало места, а не только заголовку и карточкам сверху.
            screen = QApplication.primaryScreen()
            if screen is not None:
                available = screen.availableGeometry()
                width = min(1500, max(1100, available.width() - 100))
                height = min(950, max(760, available.height() - 100))
                self.resize(width, height)
        window_state = settings.value("window/state")
        if window_state is not None:
            self.restoreState(window_state)
        if str(settings.value("ui/top_collapsed", "false")).lower() == "true":
            self.top_body.setVisible(False)
            self._apply_top_toggle_state(True)
            self.refresh_top_title()
        header_state = settings.value("table/header_state_v2")
        if header_state is not None:
            self.table.horizontalHeader().restoreState(header_state)

    def closeEvent(self, event) -> None:
        # Закрыть окно, пока поток чтения работает, значит уничтожить работающий QThread
        # (аварийное завершение). Ждём его окончания.
        self._reload_pending = False
        if self._loader is not None and self._loader.isRunning():
            self._loader.wait(30000)
        self._ui_save_timer.stop()
        self.save_ui_state()
        super().closeEvent(event)

    def save_ui_state(self) -> None:
        settings = ui_settings()
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("window/state", self.saveState())
        settings.setValue("table/header_state_v2", self.table.horizontalHeader().saveState())
        settings.sync()

    def schedule_ui_save(self, *_args) -> None:
        """Сохраняем вид через секунду после последнего изменения, а не только при закрытии:
        если окно закрыли аварийно/убили процесс, размеры и колонки не пропадут."""
        if getattr(self, "_ui_ready", False):
            self._ui_save_timer.start()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.schedule_ui_save()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self.schedule_ui_save()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    SETTINGS_TIP_CLOSED = "Настройки: папки с RSV и DBF, нормы отпуска"
    SETTINGS_TIP_OPEN = "Скрыть настройки"
    EMPTY_HINT = (
        "Выберите сотрудника: начните вводить ФИО или табельный номер в поле поиска выше.\n"
        "Здесь появится помесячная и годовая статистика по вредности."
    )

    def build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        main = QVBoxLayout(root)
        main.setContentsMargins(24, 16, 24, 16)
        main.setSpacing(10)

        # --- Заголовок + кнопка настроек ---
        header_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel(APP_TITLE)
        title.setObjectName("AppTitleCompact")
        title.setToolTip("Поиск сотрудника по ФИО, помесячная и годовая статистика по RSV")
        title_col.addWidget(title)
        header_row.addLayout(title_col, 1)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("IconButton")
        self.settings_btn.setFixedSize(36, 36)
        self.settings_btn.setToolTip(self.SETTINGS_TIP_CLOSED)
        self.settings_btn.setAccessibleName("Настройки: папки с данными и нормы отпуска")
        self.settings_btn.clicked.connect(self.toggle_paths_panel)
        header_row.addWidget(self.settings_btn, 0, Qt.AlignTop)

        # --- Компактная строка-сводка: текущие папки, нормы + быстрое обновление ---
        summary_row = QHBoxLayout()
        self.paths_summary_lbl = QLabel("")
        self.paths_summary_lbl.setObjectName("FieldCaption")
        self.paths_summary_lbl.setWordWrap(True)
        summary_row.addWidget(self.paths_summary_lbl, 1)
        quick_refresh_btn = QPushButton("↻ Обновить данные")
        quick_refresh_btn.setObjectName("UtilityButton")
        quick_refresh_btn.setToolTip("Перечитать файлы RSV и список сотрудников (F5)")
        quick_refresh_btn.setAccessibleName("Обновить данные")
        quick_refresh_btn.clicked.connect(self.reload_data)
        summary_row.addWidget(quick_refresh_btn)

        # --- Верхняя часть целиком — то, что должно ужиматься сплиттером ---
        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)
        top_layout.addLayout(header_row)
        top_layout.addLayout(summary_row)

        # --- Настройки (свёрнуты по умолчанию, открываются шестерёнкой):
        #     папки с RSV/DBF и нормы доп. отпуска (ст. 157 ТК). Нормы — общая настройка,
        #     не данные конкретного сотрудника, поэтому живут здесь, а не в карточке «Сотрудник».
        self.paths_card = QFrame()
        self.paths_card.setObjectName("Card")
        self.paths_card.setVisible(False)
        paths_outer = QVBoxLayout(self.paths_card)
        paths_outer.setContentsMargins(18, 14, 18, 14)
        paths_outer.setSpacing(12)

        paths_layout = QHBoxLayout()
        paths_layout.setSpacing(10)

        paths_label = QLabel("Папка с результатами (RSV):")
        paths_label.setObjectName("FieldLabel")
        self.out_dir_input = QLineEdit(self.env_data.get("OUT_DIR", "./"))
        self.out_dir_input.setAccessibleName("Папка с результатами RSV")
        paths_label.setBuddy(self.out_dir_input)
        browse_out_btn = QPushButton("Обзор…")
        browse_out_btn.setObjectName("BrowseButton")
        browse_out_btn.setAccessibleName("Выбрать папку с результатами RSV")
        browse_out_btn.clicked.connect(self.browse_out_dir)

        data_label = QLabel("Папка с DBF:")
        data_label.setObjectName("FieldLabel")
        self.data_dir_input = QLineEdit(self.env_data.get("DBF_DATA_DIR", "./dbf"))
        self.data_dir_input.setAccessibleName("Папка с DBF")
        data_label.setBuddy(self.data_dir_input)
        browse_data_btn = QPushButton("Обзор…")
        browse_data_btn.setObjectName("BrowseButton")
        browse_data_btn.setAccessibleName("Выбрать папку с DBF")
        browse_data_btn.clicked.connect(self.browse_data_dir)

        paths_layout.addWidget(paths_label)
        paths_layout.addWidget(self.out_dir_input, 2)
        paths_layout.addWidget(browse_out_btn)
        paths_layout.addSpacing(12)
        paths_layout.addWidget(data_label)
        paths_layout.addWidget(self.data_dir_input, 2)
        paths_layout.addWidget(browse_data_btn)
        paths_layout.addStretch()
        paths_outer.addLayout(paths_layout)

        norms_layout = QHBoxLayout()
        norms_layout.setSpacing(10)

        norms_title = QLabel("Норма доп. отпуска за вредность (дней/год):")
        norms_title.setObjectName("FieldLabel")
        norms_layout.addWidget(norms_title)
        norms_layout.addSpacing(6)

        self.norm_spinboxes: dict[float, QSpinBox] = {}
        for klass in (3.1, 3.2, 3.3):
            pair = QHBoxLayout()
            pair.setSpacing(6)
            lbl = QLabel(f"Класс {klass}:")
            lbl.setObjectName("FieldLabel")
            spin = QSpinBox()
            spin.setRange(0, 60)
            spin.setFixedWidth(84)
            spin.setValue(int(hr.DEFAULT_LEAVE_NORM_DAYS[klass]))
            spin.setAccessibleName(f"Норма отпуска для класса {klass}, дней в год")
            lbl.setBuddy(spin)
            pair.addWidget(lbl)
            pair.addWidget(spin)
            norms_layout.addLayout(pair)
            norms_layout.addSpacing(18)
            self.norm_spinboxes[klass] = spin

        save_norms_btn = QPushButton("Сохранить нормы")
        save_norms_btn.setObjectName("UtilityButton")
        save_norms_btn.setToolTip("Записать нормы в настройки и пересчитать отпуск выбранного сотрудника")
        save_norms_btn.clicked.connect(self.save_norm_days)
        norms_layout.addStretch()
        norms_layout.addWidget(save_norms_btn)
        paths_outer.addLayout(norms_layout)

        self.load_norm_days_from_env()
        top_layout.addWidget(self.paths_card)

        # --- Поиск сотрудника ---
        search_card = QFrame()
        search_card.setObjectName("Card")
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(16, 12, 16, 12)
        search_layout.setSpacing(8)

        # Заголовок карточки: кнопка сворачивания + подпись. В свёрнутом виде
        # подпись показывает выбранного сотрудника, чтобы не терять контекст.
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.top_toggle_btn = QPushButton("▾")
        self.top_toggle_btn.setObjectName("IconButton")
        self.top_toggle_btn.setFixedSize(30, 30)
        self.top_toggle_btn.clicked.connect(self.toggle_top_body)
        self._apply_top_toggle_state(False)
        title_row.addWidget(self.top_toggle_btn)
        self.search_title = QLabel("Сотрудник")
        self.search_title.setObjectName("SectionTitle")
        title_row.addWidget(self.search_title, 1)
        search_layout.addLayout(title_row)

        # Всё, что скрывается при сворачивании, — в одном контейнере.
        self.top_body = QWidget()
        body_layout = QVBoxLayout(self.top_body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        search_layout.addWidget(self.top_body)
        search_layout = body_layout  # дальше строки добавляются уже в контейнер

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Начните вводить ФИО или таб. №…")
        self.search_input.setAccessibleName("Поиск сотрудника по ФИО или табельному номеру")
        self.search_input.setToolTip("Ctrl+F — перейти к поиску. Enter — выбрать, если совпадение одно.")
        self.completer = QCompleter([])
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.search_input.setCompleter(self.completer)
        self.completer.activated[str].connect(self.on_employee_chosen)
        self.search_input.returnPressed.connect(self.on_search_enter)
        self.search_input.textChanged.connect(self._clear_search_hint)
        search_layout.addWidget(self.search_input)

        # Подсказка под полем: «не найдено» / «найдено N — уточните» (раньше Enter молчал).
        self.search_hint_lbl = QLabel("")
        self.search_hint_lbl.setObjectName("SearchHint")
        self.search_hint_lbl.setWordWrap(True)
        self.search_hint_lbl.setVisible(False)
        search_layout.addWidget(self.search_hint_lbl)

        # Одна строка: источник даты устройства слева, поле даты + кнопка справа
        info_row = QHBoxLayout()

        self.hire_source_lbl = QLabel("Сотрудник не выбран")
        self.hire_source_lbl.setObjectName("FieldCaption")
        self.hire_source_lbl.setWordWrap(True)
        info_row.addWidget(self.hire_source_lbl, 1)

        hire_label = QLabel("Дата приёма на работу:")
        hire_label.setObjectName("FieldLabel")
        info_row.addWidget(hire_label)

        self.hire_date_edit = QDateEdit()
        self.hire_date_edit.setCalendarPopup(True)
        self.hire_date_edit.setDisplayFormat("dd.MM.yyyy")
        # Минимальная дата — «пустое» значение: показывает «не указана» и не может
        # быть сохранена (раньше по умолчанию стояло 01.01.2000, и случайное
        # «Сохранить дату» записывало её как ручную правку).
        self.hire_date_edit.setMinimumDate(QDate(1949, 12, 31))
        self.hire_date_edit.setSpecialValueText("не указана")
        self.hire_date_edit.setDate(self.hire_date_edit.minimumDate())
        self.hire_date_edit.setEnabled(False)
        self.hire_date_edit.setAccessibleName("Дата приёма на работу")
        hire_label.setBuddy(self.hire_date_edit)
        info_row.addWidget(self.hire_date_edit)

        self.save_hire_btn = QPushButton("Сохранить дату")
        self.save_hire_btn.setObjectName("UtilityButton")
        self.save_hire_btn.setToolTip("Записать дату приёма на работу как ручную правку для этого сотрудника")
        self.save_hire_btn.setEnabled(False)
        self.save_hire_btn.clicked.connect(self.save_hire_date)
        info_row.addWidget(self.save_hire_btn)

        search_layout.addLayout(info_row)

        top_layout.addWidget(search_card)

        # --- Таблица по месяцам/годам ---
        table_card = QFrame()
        table_card.setObjectName("Card")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(16, 12, 16, 14)
        table_layout.setSpacing(8)

        table_title_row = QHBoxLayout()
        table_title_row.setSpacing(6)
        table_title = QLabel("Помесячная и годовая статистика")
        table_title.setObjectName("SectionTitle")
        table_title_row.addWidget(table_title)
        table_title_row.addStretch(1)
        link_qss = (
            f"QPushButton {{ background: transparent; color: {ui.PRIMARY}; border: none;"
            f" text-decoration: underline; padding: 2px 6px; min-height: 24px; font-size: 13px; }}"
            f"QPushButton:hover {{ color: {ui.PRIMARY_HOVER}; }}"
            f"QPushButton:focus {{ border: 2px solid {ui.FOCUS}; border-radius: 4px; }}"
        )
        self.collapse_all_btn = QPushButton("Свернуть все годы")
        self.expand_all_btn = QPushButton("Развернуть все годы")
        for btn, collapse in ((self.collapse_all_btn, True), (self.expand_all_btn, False)):
            btn.setStyleSheet(link_qss)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _=False, c=collapse: self.toggle_all_blocks(c))
            table_title_row.addWidget(btn)
        table_layout.addLayout(table_title_row)

        # Легенда: что значат заливки и буквы-метки в ячейках + как править.
        self.legend_lbl = QLabel(self._legend_html())
        self.legend_lbl.setObjectName("LegendText")
        self.legend_lbl.setTextFormat(Qt.RichText)
        self.legend_lbl.setWordWrap(True)
        table_layout.addWidget(self.legend_lbl)

        # Плашка важных предупреждений по выбранному сотруднику (раньше — серая строка внизу).
        self.banner_lbl = QLabel("")
        self.banner_lbl.setObjectName("Banner")
        self.banner_lbl.setWordWrap(True)
        self.banner_lbl.setVisible(False)
        table_layout.addWidget(self.banner_lbl)

        # Пустое состояние: пока нечего показывать, говорим, что делать.
        self.empty_lbl = QLabel(self.EMPTY_HINT)
        self.empty_lbl.setObjectName("EmptyState")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self.empty_lbl.setWordWrap(True)
        table_layout.addWidget(self.empty_lbl, 1)

        self.table = QTableWidget(0, 10)
        self.table.setAccessibleName("Помесячная и годовая статистика по вредности")
        column_headers = COLUMN_TITLES
        # Числовые колонки — вправо, текстовые (период) — влево, как в спецификации.
        self.COLUMN_ALIGN = [
            Qt.AlignLeft | Qt.AlignVCenter,
            Qt.AlignLeft | Qt.AlignVCenter,
            Qt.AlignRight | Qt.AlignVCenter,
            Qt.AlignRight | Qt.AlignVCenter,
            Qt.AlignRight | Qt.AlignVCenter,
            Qt.AlignRight | Qt.AlignVCenter,
            Qt.AlignRight | Qt.AlignVCenter,
            Qt.AlignRight | Qt.AlignVCenter,
            Qt.AlignRight | Qt.AlignVCenter,
            Qt.AlignLeft | Qt.AlignVCenter,     # «Тариф» — последняя (растянутая) колонка: влево, ближе к «Классу»
        ]
        self.table.setHorizontalHeaderLabels(column_headers)
        for col, align in enumerate(self.COLUMN_ALIGN):
            item = self.table.horizontalHeaderItem(col)
            if item is not None:
                item.setTextAlignment(int(align))
                item.setToolTip(COLUMN_TIPS[col])
        # Interactive вместо Stretch — колонки можно тянуть мышью, а не только
        # смотреть на то, что Qt сам решил сжать. Ширины запоминаются между
        # запусками через QSettings (см. restore_window_state/closeEvent).
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setMinimumSectionSize(64)
        header.setStretchLastSection(True)  # последняя колонка добирает остаток пустого места
        header.setFixedHeight(38)
        header.sectionResized.connect(lambda *_a: self._fit_wrapped_rows())
        default_widths = [70, 110, 100, 100, 90, 80, 110, 90, 70, 90]
        for col, w in enumerate(default_widths):
            self.table.setColumnWidth(col, w)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setEditTriggers(
            QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed
        )
        self.cell_delegate = CompactCellDelegate(self.table)
        self.table.setItemDelegate(self.cell_delegate)
        self.table.cellEntered.connect(self._on_cell_entered)
        self.table.viewport().installEventFilter(self)  # сброс подсветки колонки + пересчёт высоты строк-аннотаций
        self.table.installEventFilter(self)             # Enter/Space на заголовке года сворачивает его
        self.table.itemChanged.connect(self.on_cell_item_changed)
        self.table.setAlternatingRowColors(False)  # чередование теперь по годам, не по строкам — см. add_month_row
        self.table.setMouseTracking(True)  # для корректного hover-подсвечивания строк
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.cellClicked.connect(self.on_table_cell_clicked)
        table_layout.addWidget(self.table, 1)

        # --- Нижняя часть (таблица + статус) — то, что должно расти при растягивании окна ---
        bottom_container = QWidget()
        bottom_layout = QVBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)
        bottom_layout.addWidget(table_card, 1)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_lbl = QLabel("Готово")
        self.status_lbl.setObjectName("StatusPill")
        status_row.addWidget(self.status_lbl, 1)
        self.warnings_btn = QPushButton("Предупреждения…")
        self.warnings_btn.setObjectName("UtilityButton")
        self.warnings_btn.setToolTip("Показать предупреждения, найденные при чтении RSV")
        self.warnings_btn.setVisible(False)
        self.warnings_btn.clicked.connect(self.show_load_warnings)
        status_row.addWidget(self.warnings_btn)
        bottom_layout.addLayout(status_row)

        # --- Перетаскиваемая граница между верхом и таблицей ---
        splitter = self.main_splitter = QSplitter(Qt.Vertical)
        splitter.setObjectName("MainSplitter")
        splitter.addWidget(top_container)
        splitter.addWidget(bottom_container)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        # Верху — ровно столько места, сколько нужно по минимуму; весь остаток — таблице.
        splitter.setSizes([1, 5000])
        main.addWidget(splitter, 1)

        # Горячие клавиши: Ctrl+F — к поиску, F5 — обновить данные.
        QShortcut(QKeySequence(QKeySequence.Find), self, activated=self.focus_search)
        QShortcut(QKeySequence("F5"), self, activated=self.reload_data)

        # Явный порядок Tab: настройки → сотрудник → таблица → предупреждения.
        tab_chain = [
            self.settings_btn, quick_refresh_btn,
            self.out_dir_input, browse_out_btn, self.data_dir_input, browse_data_btn,
            *self.norm_spinboxes.values(), save_norms_btn,
            self.top_toggle_btn, self.search_input, self.hire_date_edit, self.save_hire_btn,
            self.collapse_all_btn, self.expand_all_btn, self.table, self.warnings_btn,
        ]
        for first, second in zip(tab_chain, tab_chain[1:]):
            QWidget.setTabOrder(first, second)

        self.update_paths_summary()
        self._set_table_empty(self.EMPTY_HINT)

    @staticmethod
    def _legend_html() -> str:
        """Легенда статусов ячеек: цвет + буква-метка + пояснение."""
        def chip(colors, letter: str) -> str:
            fg, bg = colors
            return (
                f'<span style="background-color:{bg}; color:{fg}; font-weight:600;">'
                f'&nbsp;{letter}&nbsp;</span>'
            )

        fg, bg = ui.STATUS_PROJECTED
        badges = ui.STATUS_BADGES
        parts = [
            f"{chip(ui.STATUS_OVERRIDE, badges['override'])} правка вручную",
            f"{chip(ui.STATUS_STALE, badges['stale'])} правка расходится с RSV",
            f"{chip(ui.STATUS_CARRIED, badges['carried'])} класс перенесён с прошлого месяца",
            f'<span style="background-color:{bg}; color:{fg};">&nbsp;&nbsp;&nbsp;&nbsp;</span> оценка (месяца ещё нет в RSV)',
        ]
        return (
            "&nbsp;&nbsp;&nbsp;&nbsp;".join(parts)
            + "<br>Двойной клик по ячейке — править; очистить ячейку — вернуть значение из RSV."
        )


    # ------------------------------------------------------------------
    # Загрузка данных
    # ------------------------------------------------------------------
    def toggle_top_body(self) -> None:
        self.set_top_collapsed(self.top_body.isVisible())

    def set_top_collapsed(self, collapsed: bool) -> None:
        self.top_body.setVisible(not collapsed)
        self._apply_top_toggle_state(collapsed)
        self.refresh_top_title()
        settings = ui_settings()
        settings.setValue("ui/top_collapsed", collapsed)
        settings.sync()
        # Верхняя панель ужалась — отдаём освободившееся место таблице.
        QTimer.singleShot(0, lambda: self.main_splitter.setSizes([1, 5000]))

    def _apply_top_toggle_state(self, collapsed: bool) -> None:
        self.top_toggle_btn.setText("▸" if collapsed else "▾")
        tip = "Развернуть блок «Сотрудник»" if collapsed else "Свернуть блок «Сотрудник»"
        self.top_toggle_btn.setToolTip(tip)
        self.top_toggle_btn.setAccessibleName(tip)

    def focus_search(self) -> None:
        """Ctrl+F: к полю поиска (разворачиваем блок «Сотрудник», если он свёрнут)."""
        if self.top_body.isHidden():
            self.set_top_collapsed(False)
        self.search_input.setFocus()
        self.search_input.selectAll()

    def refresh_top_title(self) -> None:
        collapsed = not self.top_body.isVisible()
        if collapsed and self.current_tn is not None:
            row = self.employees.loc[self.employees["tn"] == self.current_tn]
            fio = format_fio(row.iloc[0]["fio"]) if not row.empty else "?"
            hd = self.current_hire_date
            hire_txt = f"{hd.day:02d}.{hd.month:02d}.{hd.year}" if hd is not None else "не указана"
            title = f"{fio}  ·  таб. № {self.current_tn}  ·  дата приёма: {hire_txt}"
            td = self.current_termination_date
            if td is not None:
                title += f"  ·  уволен: {td.day:02d}.{td.month:02d}.{td.year}"
            self.search_title.setText(title)
        elif collapsed:
            self.search_title.setText("Сотрудник не выбран")
        else:
            self.search_title.setText("Сотрудник")

    def toggle_paths_panel(self) -> None:
        visible = not self.paths_card.isVisible()
        self.paths_card.setVisible(visible)
        self.settings_btn.setText("✕" if visible else "⚙")
        tip = self.SETTINGS_TIP_OPEN if visible else self.SETTINGS_TIP_CLOSED
        self.settings_btn.setToolTip(tip)
        self.settings_btn.setAccessibleName(tip)

    def update_paths_summary(self) -> None:
        def short(path_str: str, limit: int = 46) -> str:
            path_str = path_str.strip()
            if len(path_str) <= limit:
                return path_str
            return "…" + path_str[-(limit - 1):]

        out_text = short(self.out_dir_input.text())
        data_text = short(self.data_dir_input.text())
        norms = ", ".join(f"{klass} — {days}" for klass, days in self.saved_norm_days().items())
        self.paths_summary_lbl.setText(
            f"RSV: {out_text}   ·   DBF: {data_text}   ·   Нормы отпуска, дн./год: {norms}"
        )
        self.paths_summary_lbl.setToolTip(
            f"RSV: {self.out_dir_input.text().strip()}\nDBF: {self.data_dir_input.text().strip()}\n"
            f"Нормы доп. отпуска (дн./год по классам): {norms}"
        )

    def sync_env_paths(self) -> None:
        # Пишем ТОЛЬКО свои ключи — save_env_vars сливает их с текущим .env, так
        # что LEAVE_DAYS_* и настройки калькулятора не затираются устаревшим снимком.
        config = {
            "OUT_DIR": self.out_dir_input.text().strip(),
            "DBF_DATA_DIR": self.data_dir_input.text().strip(),
        }
        try:
            save_env_vars(config)
        except EnvFileError as exc:
            self._warn_env_file(exc)
            return
        self.env_data.update(config)

    def _warn_env_file(self, exc: Exception) -> None:
        """Ошибку .env показываем один раз на сообщение (reload_data зовёт запись часто)."""
        msg = str(exc)
        if getattr(self, "_last_env_warning", None) == msg:
            return
        self._last_env_warning = msg
        QMessageBox.warning(self, "Настройки не сохранены", msg)

    ENV_NORM_KEYS = {3.1: "LEAVE_DAYS_31", 3.2: "LEAVE_DAYS_32", 3.3: "LEAVE_DAYS_33"}

    def load_norm_days_from_env(self) -> None:
        for klass, spin in self.norm_spinboxes.items():
            key = self.ENV_NORM_KEYS[klass]
            default = int(hr.DEFAULT_LEAVE_NORM_DAYS[klass])
            try:
                spin.setValue(int(self.env_data.get(key, default)))
            except (TypeError, ValueError):
                spin.setValue(default)

    def saved_norm_days(self) -> dict[float, int]:
        """Нормы, сохранённые в .env (а не то, что сейчас набрано в полях)."""
        result: dict[float, int] = {}
        for klass in self.norm_spinboxes:
            default = int(hr.DEFAULT_LEAVE_NORM_DAYS[klass])
            try:
                result[klass] = int(self.env_data.get(self.ENV_NORM_KEYS[klass], default))
            except (TypeError, ValueError):
                result[klass] = default
        return result

    def get_norm_days(self) -> dict[float, float]:
        return {klass: spin.value() for klass, spin in self.norm_spinboxes.items()}

    def save_norm_days(self) -> None:
        config = {
            self.ENV_NORM_KEYS[klass]: str(spin.value())
            for klass, spin in self.norm_spinboxes.items()
        }
        try:
            save_env_vars(config)
        except EnvFileError as exc:
            QMessageBox.critical(self, "Нормы не сохранены", str(exc))
            return
        self.env_data.update(config)
        self.update_paths_summary()
        if self.current_tn is not None:
            self.select_employee(self.current_tn)
        self._flash_status("Нормы доп. отпуска за вредность сохранены")

    def browse_out_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Выберите папку с результатами RSV", self.out_dir_input.text()
        )
        if selected:
            self.out_dir_input.setText(selected)
            self.reload_data()

    def browse_data_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Выберите папку с базами DBF", self.data_dir_input.text()
        )
        if selected:
            self.data_dir_input.setText(selected)
            self.reload_data()

    def reload_data(self) -> None:
        """Запускает чтение данных в фоне. Повторный вызов во время чтения не
        запускает второй поток: загрузка перезапустится с актуальными путями, как
        только закончится текущая."""
        self.sync_env_paths()
        self.update_paths_summary()
        if self._loader is not None:
            self._reload_pending = True
            return

        out_dir = Path(self.out_dir_input.text().strip())
        data_dir = Path(self.data_dir_input.text().strip())

        self.search_input.setEnabled(False)
        self._set_status("Загрузка данных…", "working")

        self._loader = DataLoadWorker(out_dir, data_dir, self)
        self._loader.loaded.connect(self._on_data_loaded)
        self._loader.finished.connect(self._on_loader_finished)
        self._loader.start()

    def wait_for_load(self, timeout_ms: int = 30000) -> bool:
        """Блокирующее ожидание конца загрузки (для тестов и скриптов)."""
        started = time.monotonic()
        while self._loader is not None:
            if (time.monotonic() - started) * 1000 > timeout_ms:
                return False
            QThread.msleep(10)
            QCoreApplication.processEvents()
        return True

    def _on_loader_finished(self) -> None:
        loader, self._loader = self._loader, None
        if loader is not None:
            loader.deleteLater()
        if self._reload_pending:
            self._reload_pending = False
            self.reload_data()

    def _on_data_loaded(self, history, employees, messages, lschet_error) -> None:
        if self._reload_pending:
            return  # пути поменялись за время чтения — эти данные уже не актуальны
        self.search_input.setEnabled(True)
        self.history = history
        messages = list(messages)

        if lschet_error:
            self.employees = None
            QMessageBox.critical(
                self, "Ошибка чтения lschet.dbf",
                f"Не удалось прочитать список сотрудников:\n\n{lschet_error}",
            )
            self._set_status("Ошибка чтения lschet.dbf — список сотрудников недоступен", "error")
            self._set_banner("")
            self._set_table_empty(
                "Список сотрудников недоступен: не удалось прочитать lschet.dbf.\n"
                "Проверьте папку с DBF в настройках (⚙) и нажмите «Обновить данные»."
            )
            return
        self.employees = employees

        self.display_to_tn.clear()
        display_names = []
        for _, row in self.employees.iterrows():
            tn = row["tn"]
            if pd_isna(tn):
                continue
            display = f'{format_fio(row["fio"])}  (таб. № {int(tn)})'
            self.display_to_tn[display] = int(tn)
            display_names.append(display)

        self.completer.setModel(QStringListModel(sorted(display_names)))

        rsv_files_count = 0 if self.history is None or self.history.empty else \
            self.history[["file_year", "file_month"]].drop_duplicates().shape[0]

        status = f"Сотрудников: {len(display_names)}  •  файлов RSV прочитано: {rsv_files_count}"
        if messages:
            status += f"  •  предупреждений: {len(messages)}"
        self._base_status = status
        self._load_messages = messages
        self._set_status(status, "idle", "\n".join(messages))
        self.warnings_btn.setText(f"Предупреждения ({len(messages)})…")
        self.warnings_btn.setVisible(bool(messages))

        # Ошибки чтения файлов нельзя оставлять только счётчиком «предупреждений: N» —
        # пропавший месяц молча превратится в нули. Ошибки показываем сразу.
        read_errors = [m for m in messages if m.startswith("ОШИБКА")]
        if read_errors:
            shown = "\n\n".join(read_errors[:8])
            if len(read_errors) > 8:
                shown += f"\n\n… и ещё {len(read_errors) - 8}"
            QMessageBox.warning(
                self, "Не все файлы RSV удалось прочитать",
                f"{shown}\n\nМесяцы из этих файлов будут отмечены как «нет файла».",
            )

        if self.current_tn is not None:
            self.select_employee(self.current_tn)
        else:
            self._set_table_empty(self.EMPTY_HINT)   # убираем сообщение об ошибке прошлой загрузки

    # ------------------------------------------------------------------
    # Выбор сотрудника
    # ------------------------------------------------------------------
    def on_search_enter(self) -> None:
        text = self.search_input.text().strip()
        if not text:
            return
        if text in self.display_to_tn:
            self.on_employee_chosen(text)
            return
        # Введено не полное имя из списка: ищем по вхождению (ФИО или таб. №).
        needle = text.casefold()
        matches = [name for name in self.display_to_tn if needle in name.casefold()]
        if len(matches) == 1:
            self.search_input.setText(matches[0])
            self.on_employee_chosen(matches[0])
        elif not matches:
            self._show_search_hint(
                f"Сотрудник «{text}» не найден. Проверьте написание или введите часть фамилии.", error=True
            )
        else:
            self._show_search_hint(
                f"Найдено сотрудников: {len(matches)}. Уточните запрос или выберите из списка."
            )
            self.completer.complete()

    def _show_search_hint(self, text: str, error: bool = False) -> None:
        self.search_hint_lbl.setText(text)
        self.search_hint_lbl.setProperty("mode", "error" if error else "")
        self._repolish(self.search_hint_lbl)
        self.search_hint_lbl.setVisible(True)

    def _clear_search_hint(self, *_args) -> None:
        if self.search_hint_lbl.isVisible() or self.search_hint_lbl.text():
            self.search_hint_lbl.setText("")
            self.search_hint_lbl.setVisible(False)

    # ------------------------------------------------------------------
    # Общие помощники интерфейса
    # ------------------------------------------------------------------
    @staticmethod
    def _repolish(widget: QWidget) -> None:
        """Применить QSS-свойство (например, mode) к уже показанному виджету."""
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _set_status(self, text: str, mode: str = "idle", tooltip: str = "") -> None:
        """Строка статуса внизу. mode: idle | working | success | error (см. StatusPill в QSS)."""
        self.status_lbl.setText(text)
        self.status_lbl.setToolTip(tooltip)
        if self.status_lbl.property("mode") != mode:
            self.status_lbl.setProperty("mode", mode)
            self._repolish(self.status_lbl)

    def _flash_status(self, text: str) -> None:
        """Подтверждение действия в строке статуса вместо модального окна «Сохранено»
        (не прерывает работу, через несколько секунд возвращается обычный статус)."""
        self._flash_text = f"✓ {text}"
        self._set_status(self._flash_text, "success")
        self._flash_timer.start()

    def _end_flash(self) -> None:
        if self._flash_text and self.status_lbl.text() == self._flash_text:
            self._set_status(self._base_status or "Готово", "idle", "\n".join(self._load_messages))
        self._flash_text = ""

    def _set_banner(self, text: str) -> None:
        """Плашка важных предупреждений над таблицей (пустой текст — скрыть)."""
        self.banner_lbl.setText(text)
        self.banner_lbl.setVisible(bool(text))

    def _set_table_empty(self, message: str | None) -> None:
        """message=None — показать таблицу; иначе вместо неё — пояснение, что делать."""
        empty = message is not None
        self.empty_lbl.setVisible(empty)
        self.table.setVisible(not empty)
        if empty:
            self.empty_lbl.setText(message)

    def show_load_warnings(self) -> None:
        if not self._load_messages:
            return
        shown = self._load_messages[:25]
        text = "\n".join(shown)
        if len(self._load_messages) > 25:
            text += f"\n… и ещё {len(self._load_messages) - 25}"
        QMessageBox.information(self, "Предупреждения при чтении RSV", text)

    def _fit_wrapped_rows(self) -> None:
        """Подгоняет высоту строк-аннотаций под перенос слов при текущей ширине таблицы:
        длинные предупреждения больше не обрезаются многоточием."""
        if self._fitting_rows or not self._wrapped_rows:
            return
        last = self.table.columnCount() - 1
        width = (
            self.table.columnViewportPosition(last) + self.table.columnWidth(last)
            - self.table.columnViewportPosition(1)
        )
        if width < 80:
            return
        self._fitting_rows = True
        try:
            for row, label in self._wrapped_rows:
                label.ensurePolished()
                height = max(32, label.heightForWidth(width))
                if self.table.rowHeight(row) != height:
                    self.table.setRowHeight(row, height)
        finally:
            self._fitting_rows = False

    def on_employee_chosen(self, display_text: str) -> None:
        tn = self.display_to_tn.get(display_text)
        if tn is not None:
            self.select_employee(tn)

    def _warn_override_file(self, exc: Exception) -> None:
        """Показывает ошибку повреждённого файла правок — один раз на сообщение,
        чтобы не заваливать пользователя диалогами при каждом выборе сотрудника."""
        msg = str(exc)
        if getattr(self, "_last_override_warning", None) == msg:
            return
        self._last_override_warning = msg
        QMessageBox.critical(self, "Файл ручных правок недоступен", msg)

    def select_employee(self, tn: int) -> None:
        if self.employees is None:
            return  # lschet.dbf не прочитан — выбирать пока не из чего
        self.current_tn = tn

        try:
            hire_overrides = hr.load_hire_date_overrides()
        except hr.OverrideFileError as exc:
            self._warn_override_file(exc)
            hire_overrides = {}
        hire_date, source = hr.get_hire_date(tn, self.employees, hire_overrides)
        ignored_override = hr.describe_ignored_hire_override(tn, hire_overrides)
        self.current_source = source
        self.current_hire_date = hire_date

        termination_date, term_source = hr.get_termination_date(tn, self.employees, hire_date)
        self.current_termination_date = termination_date
        self.current_termination_source = term_source

        self.refresh_top_title()

        early_months = hr.find_data_before_hire(tn, self.history, hire_date)
        hire_label = f"Таб. № {tn}   •   дата приёма: {SOURCE_LABELS.get(source, source)}"
        early_warning = ""
        if early_months:
            first, last = early_months[0], early_months[-1]
            early_warning = (
                f"⚠ Есть RSV-данные РАНЬШЕ даты приёма: {len(early_months)} мес. "
                f"({first[1]:02d}.{first[0]}–{last[1]:02d}.{last[0]}) — в таблице они не показаны. "
                f"Если сотрудник принят повторно или дата указана неверно — поправьте её."
            )
            hire_label += "   ⚠"

        term_note = ""
        if termination_date is not None:
            hire_label += f"   •   уволен: {termination_date.day:02d}.{termination_date.month:02d}.{termination_date.year}"
            term_note = (
                f"Сотрудник уволен {termination_date.day:02d}.{termination_date.month:02d}.{termination_date.year} "
                f"— таймлайн и оценка отпуска не продлеваются дальше этой даты."
            )
        elif term_source == "data_uvl_invalid":
            hire_label += "   ⚠ дата увольнения не распознана"
            term_note = "⚠ В карточке есть дата увольнения, но она не прошла проверку на правдоподобие — проигнорирована."

        if ignored_override:
            hire_label += "   ⚠ ручная дата отброшена"
        self.hire_source_lbl.setText(hire_label)
        self.hire_source_lbl.setToolTip(
            "\n".join(p for p in (ignored_override, early_warning, term_note) if p)
        )
        self._early_warning = early_warning
        self._term_note = term_note

        self.hire_date_edit.setEnabled(True)
        self.save_hire_btn.setEnabled(True)
        if hire_date is not None:
            self.hire_date_edit.setDate(QDate(hire_date.year, hire_date.month, hire_date.day))
        else:
            self.hire_date_edit.setDate(self.hire_date_edit.minimumDate())  # «не указана»

        self.render_timeline(tn, hire_date, termination_date)

    def save_hire_date(self) -> None:
        if self.current_tn is None:
            return
        qd = self.hire_date_edit.date()
        if qd == self.hire_date_edit.minimumDate():
            QMessageBox.warning(self, "Дата не указана", "Выберите дату приёма на работу и повторите.")
            return
        date_str = f"{qd.year():04d}-{qd.month():02d}-{qd.day():02d}"
        try:
            hr.save_hire_date_override(self.current_tn, date_str)
        except ValueError as exc:
            QMessageBox.warning(self, "Некорректная дата приёма", str(exc))
            return
        except hr.OverrideFileError as exc:
            QMessageBox.critical(self, "Файл ручных правок недоступен", str(exc))
            return
        self.select_employee(self.current_tn)
        self._flash_status(f"Дата приёма сохранена: {qd.toString('dd.MM.yyyy')}")

    # ------------------------------------------------------------------
    # Таблица
    # ------------------------------------------------------------------
    def render_timeline(self, tn: int, hire_date, termination_date=None, keep_collapse: bool = False) -> None:
        # keep_collapse=True — перерисовка после правки ячейки: сохраняем, какие
        # рабочие годы были свёрнуты/развёрнуты, и положение прокрутки. Иначе
        # правка в любом, кроме последнего, году сворачивала бы этот год обратно.
        prev_collapsed: dict = {}
        scroll_pos = None
        if keep_collapse:
            prev_collapsed = {b["label"]: b["collapsed"] for b in getattr(self, "year_blocks", [])}
            scroll_pos = self.table.verticalScrollBar().value()

        self._suppress_item_changed = True
        try:
            self.table.setRowCount(0)
            self._wrapped_rows = []
            self._set_hover_col(-1)
            self.year_blocks = []
            self.header_row_to_block = {}
            self._set_banner("")

            if self.history is None or self.history.empty:
                self._set_table_empty(
                    "Нет ни одного файла RSV — статистику показать нечем.\n"
                    "Проверьте папку с результатами в настройках (⚙) и нажмите «Обновить данные»."
                )
                return

            timeline = hr.build_employee_timeline(
                tn, self.history, hire_date=hire_date, termination_date=termination_date
            )
            try:
                tn_overrides = hr.load_month_overrides().get(str(int(tn)), {})
            except hr.OverrideFileError as exc:
                self._warn_override_file(exc)
                tn_overrides = {}
            blocks = hr.build_work_year_blocks(
                timeline, norm_days=self.get_norm_days(), month_overrides=tn_overrides,
                termination_date=termination_date,
            )

            if not blocks:
                self._set_table_empty(
                    "По этому сотруднику нет ни одной фактической записи в найденных RSV-файлах.\n"
                    "Выберите другого сотрудника или проверьте папку с результатами в настройках (⚙)."
                )
                return
            self._set_table_empty(None)

            stale_count = sum(
                len(r.get("stale_fields") or {})
                for block in blocks for r in block["month_rows"]
            )
            banner_parts = [self._early_warning, getattr(self, "_term_note", "")]
            if stale_count:
                banner_parts.append(
                    f"⚠ Ручных правок, расходящихся с появившимся RSV: {stale_count} (ячейки с меткой "
                    f"«{ui.STATUS_BADGES['stale']}»). Введите значение заново, чтобы подтвердить, "
                    f"или очистите ячейку, чтобы взять значение из RSV."
                )
            self._set_banner("\n".join(part for part in banner_parts if part))

            for i, block in enumerate(blocks):
                if i > 0:
                    self.add_divider_row()
                tint = self.YEAR_TINTS[i % 2]
                bg = self.HEADER_TINTS[i % 2]
                header_row = self.add_year_header_row(block["label"], block["month_count"], bg)
                qt_block = {"label": block["label"], "header_row": header_row, "month_rows": [], "collapsed": False}
                self.header_row_to_block[header_row] = qt_block
                self.year_blocks.append(qt_block)
                # Мини-шапка с названиями колонок — прямо над данными этого года.
                # Кладём в month_rows, чтобы она сворачивалась вместе с месяцами.
                qt_block["month_rows"].append(self.add_column_header_row())

                leave_classes = (block["leave"] or {}).get("mixed_month_leave_class", {})
                for r in block["month_rows"]:
                    qt_block["month_rows"].append(self.add_month_row(r, tint=tint, leave_classes=leave_classes))

                self.finish_work_year_block(block)

            # По умолчанию сворачиваем все рабочие годы, кроме последнего (самого
            # свежего) — так видно всю историю одним взглядом на заголовки+итоги,
            # а листать помесячно нужно только тот год, что реально интересен.
            last_idx = len(self.year_blocks) - 1
            for idx, qt_block in enumerate(self.year_blocks):
                collapsed = prev_collapsed.get(qt_block["label"], idx < last_idx)
                if collapsed:
                    self.set_block_collapsed(qt_block, True)

            self._fit_wrapped_rows()
            # Ширина области таблицы окончательно известна только после показа/появления полосы прокрутки.
            QTimer.singleShot(0, self._fit_wrapped_rows)

            if scroll_pos is not None:
                self.table.verticalScrollBar().setValue(scroll_pos)
        finally:
            self._suppress_item_changed = False

    def on_cell_item_changed(self, item: QTableWidgetItem) -> None:
        if self._suppress_item_changed:
            return  # программное построение таблицы — не правка кадровика

        payload = item.data(Qt.UserRole)
        if not payload:
            return  # не редактируемая ячейка (или что-то не проставило метку)
        year, month, field, had_data = payload

        raw_text = item.text().strip()

        if raw_text == "":
            # Пустое значение — не "поставить 0", а убрать правку целиком:
            # ячейка вернётся к расчётному (RSV/прогноз) значению.
            try:
                hr.clear_month_override(self.current_tn, year, month, field)
            except hr.OverrideFileError as exc:
                QMessageBox.critical(self, "Файл ручных правок недоступен", str(exc))
            self._reload_after_edit()
            return

        try:
            value = self._parse_editable_value(field, raw_text)
        except ValueError as exc:
            QMessageBox.warning(self, "Некорректное значение", str(exc))
            self._reload_after_edit()  # откат к прежнему виду
            return

        try:
            hr.save_month_override(
                self.current_tn, year, month, field, value, had_data=had_data
            )
        except hr.OverrideFileError as exc:
            QMessageBox.critical(self, "Файл ручных правок недоступен", str(exc))
        self._reload_after_edit()

    def _reload_after_edit(self) -> None:
        # Пересборку таблицы откладываем на event loop: itemChanged срабатывает
        # ещё ДО того, как редактор ячейки закрылся, и немедленный setRowCount(0)
        # прямо в обработчике может столкнуться с ним же.
        tn, hire_date, term_date = self.current_tn, self.current_hire_date, self.current_termination_date
        QTimer.singleShot(0, lambda: self.render_timeline(tn, hire_date, term_date, keep_collapse=True))

    @staticmethod
    def _parse_editable_value(field: str, raw_text: str):
        if field == "bal_vredn":
            raw_text = raw_text.replace(",", ".")  # «3,1» с русской раскладки
            if raw_text not in ("3.1", "3.2", "3.3"):
                raise ValueError('Класс вредности должен быть одним из: 3.1, 3.2, 3.3 (или пусто — убрать правку)')
            return float(raw_text)

        try:
            value = int(raw_text)
        except ValueError:
            raise ValueError(f'Ожидалось целое число, введено: "{raw_text}"')
        if value < 0:
            raise ValueError("Значение не может быть отрицательным")
        return value

    def _set_hover_col(self, col: int) -> None:
        if self.cell_delegate.hover_col != col:
            self.cell_delegate.hover_col = col
            self.table.viewport().update()

    def _on_cell_entered(self, row: int, column: int) -> None:
        self._set_hover_col(column)

    def eventFilter(self, obj, event):
        if obj is self.table.viewport():
            if event.type() == QEvent.Leave:
                self._set_hover_col(-1)
            elif event.type() == QEvent.Resize:
                self._fit_wrapped_rows()
        elif obj is self.table and event.type() == QEvent.KeyPress:
            # Enter/Space на заголовке рабочего года сворачивает/разворачивает его
            # (раньше — только клик мышью). Пока открыт редактор ячейки, клавиши идут в него,
            # а не в таблицу, поэтому правка значений не затрагивается.
            block = self.header_row_to_block.get(self.table.currentRow())
            if block is not None:
                key = event.key()
                if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                    self.set_block_collapsed(block, not block["collapsed"])
                    return True
                if key == Qt.Key_Left and not block["collapsed"]:      # ← свернуть
                    self.set_block_collapsed(block, True)
                    return True
                if key == Qt.Key_Right and block["collapsed"]:         # → развернуть
                    self.set_block_collapsed(block, False)
                    return True
        return super().eventFilter(obj, event)

    def on_table_cell_clicked(self, row: int, column: int) -> None:
        block = self.header_row_to_block.get(row)
        if block is None:
            return
        self.set_block_collapsed(block, not block["collapsed"])

    def toggle_all_blocks(self, collapse: bool) -> None:
        for block in self.year_blocks:
            self.set_block_collapsed(block, collapse)

    def set_block_collapsed(self, block: dict, collapsed: bool) -> None:
        block["collapsed"] = collapsed
        for r in block["month_rows"]:
            self.table.setRowHidden(r, collapsed)
        header_item = self.table.item(block["header_row"], 0)
        if header_item is not None:
            header_item.setText("▶" if collapsed else "▼")
            state = "свёрнут" if collapsed else "развёрнут"
            header_item.setData(Qt.AccessibleTextRole, f"Рабочий год {block['label']}, {state}")

    # Чередующийся фон по РАБОЧИМ ГОДАМ (а не по строкам, как раньше) — так
    # видно, где заканчивается один год и начинается следующий, даже когда
    # оба развёрнуты и строки идут подряд.
    YEAR_TINTS = tuple(QColor(c) for c in ui.YEAR_ROW_TINTS)
    HEADER_TINTS = tuple(QColor(c) for c in ui.YEAR_HEADER_TINTS)

    def add_year_header_row(self, work_year_label: str, month_count: int, bg: QColor) -> int:
        text = f"Рабочий год {work_year_label}   ·   {month_count} мес.   (клик или Enter — свернуть/развернуть)"
        return self.add_span_row("▼", text, QColor(ui.TEXT), bg)

    def add_column_header_row(self) -> int:
        """Мини-шапка с названиями колонок внутри блока рабочего года: название
        стоит рядом с данными, а не только в шапке таблицы вверху."""
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        self.table.setRowHeight(row_idx, 28)
        font = QFont()
        font.setBold(True)
        font.setPointSizeF(max(font.pointSizeF() - 1.0, 8.0))
        for col, title in enumerate(COLUMN_TITLES):
            item = QTableWidgetItem(title)
            item.setFont(font)
            item.setForeground(QColor(ui.MINI_HEADER[0]))
            item.setBackground(QColor(ui.MINI_HEADER[1]))
            item.setTextAlignment(int(self.COLUMN_ALIGN[col]))
            item.setToolTip(COLUMN_TIPS[col])
            item.setData(GRID_ROLE, True)
            item.setFlags(Qt.ItemIsEnabled)  # не редактируется и не выделяется
            self.table.setItem(row_idx, col, item)
        return row_idx

    def add_divider_row(self) -> None:
        """Тонкая полоса между блоками разных рабочих лет — чисто визуальный
        разделитель, к сворачиванию/итогам отношения не имеет."""
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        self.table.setRowHeight(row_idx, 6)
        item = QTableWidgetItem("")
        item.setBackground(QColor(ui.DIVIDER))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row_idx, 0, item)
        self.table.setSpan(row_idx, 0, 1, self.table.columnCount())

    def finish_work_year_block(self, block: dict) -> None:
        """Закрывает блок рабочего года: строка ИТОГО + наглядный расчёт отпуска по классам."""
        self.add_year_total_row(block["label"], block["kol_rd_total"], block["vred_total"], block["monthly_total"])

        leave_entry = block["leave"]
        if leave_entry is None:
            return

        kol_rd_total = leave_entry["kol_rd_total"]
        classes = leave_entry["classes"]

        for cls in classes:
            self.add_leave_class_row(
                cls["klass"], cls["days"], cls["norm"], kol_rd_total, cls["vyshlo"],
                capped=cls.get("capped", False), vyshlo_raw=cls.get("vyshlo_raw"),
            )

        # Строки-аннотации: метка в первой колонке — слово или значок (а не только цвет),
        # текст переносится по словам.
        def note(label: str, text: str, colors) -> None:
            self.add_span_row(label, text, QColor(colors[0]), QColor(colors[1]), wrap=True)

        if leave_entry.get("days_exceed_norm"):
            note(
                "⚠",
                f'Сумма дней ({leave_entry["total_days"]:.0f}) больше нормы рабочих дней графика '
                f'({kol_rd_total:.0f}) — возможно, отпуск указан в календарных днях или норма '
                f'графика занижена. Начисленное ограничено нормой класса, результат стоит проверить.',
                ui.NOTE_WARN,
            )

        missing = block.get("missing_file_months") or []
        if missing:
            months_txt = ", ".join(f"{m:02d}.{y}" for y, m in missing[:12])
            if len(missing) > 12:
                months_txt += f" … (всего {len(missing)})"
            note(
                "⚠",
                f"Нет RSV-файла за: {months_txt}. Эти месяцы учтены как «вредности нет» "
                f"(норма дней — оценка), поэтому начисленный отпуск может быть занижен.",
                ui.NOTE_WARN,
            )

        if leave_entry["unclassified_days"] > 0:
            note(
                "Инфо",
                f'Не учтено в расчёте отпуска: {leave_entry["unclassified_days"]:.0f} дн. '
                f'(класс вредности ещё ни разу не был определён на этот момент)',
                ui.NOTE_NOTICE,
            )

        for y_m, m_m, split in leave_entry.get("mixed_class_months", []):
            parts = ", ".join(f"{c:.1f} — {d:.0f} дн." for c, d in sorted(split.items()))
            # Класс, к которому РЕАЛЬНО отнесён отпуск месяца, считает history_reader
            # (преобладающий за рабочий год). Берём его, а не «максимум дней в этом месяце» —
            # иначе на экране один класс, а в расчёте другой.
            usual = leave_entry.get("mixed_month_leave_class", {}).get((y_m, m_m))
            if usual is None:
                usual = max(split.items(), key=lambda kv: (kv[1], kv[0]))[0]
            note(
                "Инфо",
                f"Смена класса в {m_m:02d}.{y_m}: дни вредности {parts} Отпуск и «по среднему» "
                f"этого месяца отнесены к классу {usual:.1f} — он преобладает за рабочий год "
                f"по сумме дней вредности.",
                ui.NOTE_CLASS_CHANGE,
            )

        if len(classes) > 1:
            # Несколько классов за раб. год — показываем разбивку сложения по каждому,
            # чтобы было видно, из чего сложились «норма за год» и «начислено».
            norm_parts = " + ".join(f'{c["norm"]:.0f}' for c in classes)
            accrued_parts = " + ".join(fmt_num(c["vyshlo"]) for c in classes)
            summary_text = (
                f'Отпуск за вредность: норма за год {norm_parts} = {leave_entry["polozheno_total"]:.0f} дн.  ·  '
                f'начислено пропорционально отработанному {accrued_parts} = '
                f'{fmt_num(leave_entry["vyshlo_total"])} → {leave_entry["vyshlo_total_rounded"]} дн.'
            )
        else:
            summary_text = (
                f'Отпуск за вредность: норма за год {leave_entry["polozheno_total"]:.0f} дн.  ·  '
                f'начислено пропорционально отработанному {fmt_num(leave_entry["vyshlo_total"])} '
                f'→ {leave_entry["vyshlo_total_rounded"]} дн.'
            )

        note("ОТПУСК", summary_text, ui.SUMMARY)

    # Столбец → поле таймлайна, для тех колонок, что кадровик может править.
    # Правка теперь разрешена на ЛЮБОМ месяце, включая уже посчитанный по
    # RSV — правка кадровика всегда побеждает (см. apply_month_overrides).
    # "Итого" и "Тариф" остаются расчётными (не входят в этот словарь) —
    # это производные величины, а не исходные данные.
    EDITABLE_COLUMNS = {
        2: "kol_rd", 3: "vred_dni",
        4: "otp_dni", 5: "otp_bud_m", 6: "po_sredn",
        8: "bal_vredn",
    }

    # Подписи полей для тултипа "было / стало" у переопределённых ячеек.
    FIELD_LABELS = {
        "kol_rd": "Раб. дни", "vred_dni": "Вредность", "bal_vredn": "Класс",
        "otp_dni": "Отпуск", "otp_bud_m": "О/б/м", "po_sredn": "По среднему",
    }

    @staticmethod
    def _set_tip(item: QTableWidgetItem, text: str) -> None:
        """Подсказка и для мыши (тултип), и для программ экрана (описание ячейки)."""
        item.setToolTip(text)
        item.setData(Qt.AccessibleDescriptionRole, text)

    @staticmethod
    def _set_badge(item: QTableWidgetItem, key: str, colors) -> None:
        """Буква-метка статуса в углу ячейки (рисует CompactCellDelegate)."""
        item.setData(BADGE_ROLE, ui.STATUS_BADGES[key])
        item.setData(BADGE_COLOR_ROLE, colors[0])

    @staticmethod
    def _fmt_field_value(field: str, value) -> str:
        if value is None or (isinstance(value, float) and value != value):
            return "—"
        if field == "bal_vredn":
            return str(value)
        return str(round(value)) if isinstance(value, (int, float)) else str(value)

    def _override_tooltip(self, field: str, original_value, row, has_data: bool) -> str:
        label = self.FIELD_LABELS.get(field, field)
        was = self._fmt_field_value(field, original_value)
        now = self._fmt_field_value(field, row[field])
        source = "в RSV было" if has_data else "было (авто)"
        return f"{label}: {source} {was} → вручную изменено на {now}"

    def add_month_row(self, r, tint: QColor | None = None, leave_classes: dict | None = None) -> int:
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)

        has_data = bool(r["has_data"])
        overridden_fields = r.get("overridden_fields") or {}
        stale_fields = r.get("stale_fields") or {}
        is_projected = bool(r.get("is_projected", False))

        base_color = QColor(ui.TEXT) if has_data else QColor(ui.TEXT_FAINT)
        # Прогноз — не точечная правка одного поля, а вся строка целиком,
        # поэтому вместо цвета текста заливаем всю строку светло-зелёным
        # (перебивает обычное чередование по годам) — так заметнее, чем
        # просто цветной текст на белом. Текст берём потемнее самой заливки,
        # чтобы не потерять контраст (обычный серый "нет данных" на светлой
        # заливке был бы едва читаем).
        row_fill = None
        if is_projected:
            row_fill = QColor(ui.STATUS_PROJECTED[1])
            base_color = QColor(ui.STATUS_PROJECTED[0])

        month_label = MONTHS_RU_SHORT[int(r["month"])]
        no_file = hr._flag(r.get("no_file", False))
        if no_file:
            month_label += "  (нет файла)"
        elif is_projected:
            month_label += "  (оценка)"
        projection_note = r.get("projection_note")
        row_tooltip = None
        if is_projected and isinstance(projection_note, str) and projection_note:
            # часть заметок уже начинается со слова «Оценка:» — не дублируем
            row_tooltip = projection_note if projection_note.startswith(("Оценка", "RSV-файла")) \
                else f"Оценка: {projection_note}"

        values = [
            str(int(r["year"])),
            month_label,
            str(round(hr._nz(r["kol_rd"]))),
            str(round(hr._nz(r["vred_dni"]))),
            str(int(hr._nz(r["otp_dni"]))),
            str(int(hr._nz(r["otp_bud_m"]))),
            str(int(hr._nz(r["po_sredn"]))),
            str(round(hr._nz(r["monthly_total"]))),
            "" if r["bal_vredn_effective"] in (None,) or (isinstance(r["bal_vredn_effective"], float) and r["bal_vredn_effective"] != r["bal_vredn_effective"]) else str(r["bal_vredn_effective"]),
            "" if r["tar1"] in (None,) or (isinstance(r["tar1"], float) and r["tar1"] != r["tar1"]) else fmt_num(r["tar1"]),
        ]
        year, month = int(r["year"]), int(r["month"])

        bal_carried = bool(r.get("bal_vredn_carried", False))
        carried_tooltip = None
        if bal_carried:
            src_y, src_m = r.get("bal_vredn_source_year"), r.get("bal_vredn_source_month")
            if src_y is not None and src_m is not None and src_y == src_y and src_m == src_m:  # не NaN
                carried_tooltip = (
                    f"Класс: в этом месяце в RSV не было строки вредности — он перенесён "
                    f"с {int(src_m):02d}.{int(src_y)} (последний месяц, когда он был подтверждён по RSV)"
                )
            else:
                carried_tooltip = "Класс: перенесён с более раннего месяца, не подтверждён RSV в этом месяце"

        for col, val in enumerate(values):
            item = QTableWidgetItem(val)
            item.setData(GRID_ROLE, True)
            field = self.EDITABLE_COLUMNS.get(col)
            is_overridden_here = field is not None and field in overridden_fields
            # "Балл" перенесён по ffill, а не подтверждён RSV в этом месяце —
            # свой акцент, в том числе и внутри прогнозных (зелёных) строк:
            # для них класс тоже всегда перенесённый, раз в самом месяце
            # никакой RSV-строки нет и не может быть.
            is_carried_here = field == "bal_vredn" and bal_carried and not is_overridden_here

            if is_overridden_here:
                # Красим ТОЛЬКО эту ячейку — остальная строка сохраняет свой
                # обычный вид. Акцент — на ЗАЛИВКЕ (насыщенный жёлтый), а не
                # на цвете текста, который на белом фоне почти не заметен.
                item.setForeground(QColor(ui.STATUS_OVERRIDE[0]))
                item.setBackground(QColor(ui.STATUS_OVERRIDE[1]))
                self._set_badge(item, "override", ui.STATUS_OVERRIDE)
                bold_font = QFont()
                bold_font.setBold(True)
                item.setFont(bold_font)
                tip = self._override_tooltip(field, overridden_fields[field], r, has_data)
                if field in stale_fields:
                    # Правку вводили, пока настоящего RSV за месяц не было; теперь он
                    # есть и отличается — красная заливка вместо жёлтой.
                    was, now = stale_fields[field]
                    item.setForeground(QColor(ui.STATUS_STALE[0]))
                    item.setBackground(QColor(ui.STATUS_STALE[1]))
                    self._set_badge(item, "stale", ui.STATUS_STALE)
                    tip += (
                        f"\n⚠ Правку вводили, когда RSV за этот месяц ещё не было. "
                        f"Теперь в RSV: {self._fmt_field_value(field, was)}, "
                        f"в правке: {self._fmt_field_value(field, now)}. "
                        f"Введите значение заново, чтобы подтвердить, или очистите ячейку, "
                        f"чтобы взять значение из RSV."
                    )
                self._set_tip(item, tip)
            elif is_carried_here:
                # Класс вредности перенесён с более раннего месяца (ffill),
                # а не подтверждён RSV-строкой в ЭТОМ месяце — фиолетовый
                # акцент, отличимый от жёлтой правки и
                # зелёного прогноза.
                item.setForeground(QColor(ui.STATUS_CARRIED[0]))
                item.setBackground(QColor(ui.STATUS_CARRIED[1]))
                self._set_badge(item, "carried", ui.STATUS_CARRIED)
                bold_font = QFont()
                bold_font.setBold(True)
                item.setFont(bold_font)
                if carried_tooltip:
                    self._set_tip(item, carried_tooltip)
            else:
                item.setForeground(base_color)
                if row_fill is not None:
                    item.setBackground(row_fill)
                elif tint is not None:
                    item.setBackground(tint)
                if row_tooltip:
                    self._set_tip(item, row_tooltip)

            if field == "bal_vredn" and not is_overridden_here:
                split = hr.month_class_split(r)
                if split:
                    parts = "; ".join(f"{c:.1f} — {d:.0f} дн." for c, d in sorted(split.items()))
                    # Класс, к которому реально отнесён отпуск месяца, считает history_reader
                    # (преобладающий за рабочий год) — показываем его, а не «максимум дней в месяце».
                    usual = (leave_classes or {}).get((int(year), int(month)))
                    if usual is None:
                        usual = max(split.items(), key=lambda kv: (kv[1], kv[0]))[0]
                    self._set_tip(
                        item,
                        f"Смена класса в этом месяце: {parts} В ячейке показан класс с большим числом "
                        f"дней вредности за месяц; отпуск и «по среднему» месяца относятся к классу "
                        f"{usual:.1f} — он преобладает за рабочий год по сумме дней вредности.",
                    )

            item.setTextAlignment(int(self.COLUMN_ALIGN[col]))

            if field is not None:
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setData(Qt.UserRole, (year, month, field, has_data))
            else:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)

            self.table.setItem(row_idx, col, item)
        return row_idx

    def add_year_total_row(self, work_year_label: str, kol_rd_total: float, vred_total: float, monthly_total: float) -> None:
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        bold = QFont()
        bold.setBold(True)
        # «03.2024–02.2025» не влезает в колонку «Месяц» (…) — показываем «03.24–02.25», полный период в тултипе.
        short_label = re.sub(r"(\d{2})\.(\d{2})(\d{2})", r"\1.\3", work_year_label)
        values = [
            "ИТОГО", short_label, str(round(kol_rd_total)), str(round(vred_total)),
            "", "", "", str(round(monthly_total)), "", "",
        ]
        for col, val in enumerate(values):
            item = QTableWidgetItem(val)
            item.setData(GRID_ROLE, True)
            item.setFont(bold)
            item.setForeground(QColor(ui.SUMMARY[0]))
            item.setBackground(QColor(ui.SUMMARY[1]))
            item.setTextAlignment(int(self.COLUMN_ALIGN[col]))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            if col == 1:
                item.setToolTip(f"Итого за рабочий год {work_year_label}")
            self.table.setItem(row_idx, col, item)

    def add_leave_class_row(
        self, klass: float, days: float, norm: float, kol_rd_total: float, vyshlo: float,
        capped: bool = False, vyshlo_raw: float | None = None,
    ) -> None:
        days_txt = f"{days:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        text = f'  ↳ класс {klass}: ({days_txt} дн. × {norm:.0f}) / {kol_rd_total:.0f} раб. дн. = {fmt_num(vyshlo)} дн. отпуска'
        if capped and vyshlo_raw is not None:
            text = (
                f'  ↳ класс {klass}: ({days_txt} дн. × {norm:.0f}) / {kol_rd_total:.0f} раб. дн. = '
                f'{fmt_num(vyshlo_raw)} → ограничено нормой класса: {fmt_num(vyshlo)} дн. отпуска'
            )
        fg, bg = ui.NOTE_WARN if capped else ui.NOTE_PLAIN
        self.add_span_row("", text, QColor(fg), QColor(bg), wrap=True)

    def _make_wrapped_label(self, text: str, fg: QColor, bg: QColor) -> QLabel:
        """Текст аннотации с переносом слов. Ставится поверх объединённой ячейки и пропускает
        клики/наведение сквозь себя, так что строка ведёт себя как обычная (тултип, выбор)."""
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.PlainText)
        label.setContentsMargins(10, 6, 10, 6)
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        label.setStyleSheet(
            f"QLabel {{ background-color: {bg.name()}; color: {fg.name()}; font-size: 13px; }}"
        )
        return label

    def add_span_row(
        self, col0_text: str, span_text: str, fg_color: QColor,
        bg_color: QColor | None = None, tooltip: str | None = None, wrap: bool = False,
    ) -> int:
        """Строка-аннотация: короткая метка в первой колонке + текст на всю остальную ширину.

        wrap=True — длинный текст переносится по словам (иначе он обрезался бы многоточием,
        а полный текст был бы недоступен); высоту строки подгоняет _fit_wrapped_rows.
        У таких строк полный текст дублируется в тултипе и в описании для программ экрана."""
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        bold = QFont()
        bold.setBold(True)
        tip = tooltip if tooltip else (span_text if wrap else None)

        item0 = QTableWidgetItem(col0_text)
        item0.setFont(bold)
        item0.setForeground(fg_color)
        if bg_color is not None:
            item0.setBackground(bg_color)
        item0.setTextAlignment(Qt.AlignCenter)
        if tip:
            self._set_tip(item0, tip)
        item0.setFlags(item0.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row_idx, 0, item0)

        span_item = QTableWidgetItem(span_text)
        if wrap:
            # Видимый текст рисует QLabel поверх; свой текст ячейки прячем цветом фона.
            span_item.setForeground(bg_color if bg_color is not None else QColor(ui.WHITE))
        else:
            span_item.setFont(bold)
            span_item.setForeground(fg_color)
        if bg_color is not None:
            span_item.setBackground(bg_color)
        span_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if tip:
            self._set_tip(span_item, tip)
        span_item.setData(Qt.AccessibleTextRole, span_text)
        span_item.setFlags(span_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row_idx, 1, span_item)
        self.table.setSpan(row_idx, 1, 1, self.table.columnCount() - 1)

        if wrap:
            label = self._make_wrapped_label(
                span_text, fg_color, bg_color if bg_color is not None else QColor(ui.WHITE)
            )
            self.table.setCellWidget(row_idx, 1, label)
            self._wrapped_rows.append((row_idx, label))
        return row_idx


def pd_isna(value) -> bool:
    try:
        return value is None or value != value  # NaN != NaN
    except Exception:
        return value is None


def main() -> None:
    migrate_legacy_data()  # старые настройки/правки рядом с программой -> папка данных (до чтения .env)
    migrate_ui_settings_from_registry()  # прежний вид окна из реестра -> файл в папке данных
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    install_excepthook(APP_TITLE)

    window = HistoryWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()