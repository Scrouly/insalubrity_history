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

import sys
from pathlib import Path
import re

from PyQt5.QtCore import QDate, QEvent, QSettings, QStringListModel, Qt, QTimer
from PyQt5.QtGui import QColor, QFont
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
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app_env import EnvFileError, install_excepthook, load_env_vars, save_env_vars
from insalubrity_gui import STYLESHEET

import history_reader as hr

MONTHS_RU_SHORT = [
    "", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
    "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек",
]

# Метка «эта ячейка — часть сетки данных» (месячные строки, ИТОГО, мини-шапка года):
# только у таких ячеек рисуются явные вертикальные линии и подсветка колонки под курсором.
GRID_ROLE = Qt.UserRole + 1

# Единые названия колонок: и в верхней шапке, и в мини-шапке каждого рабочего года.
# Однострочные — двухстрочный текст не влезал в шапку и обрезался; пояснения — в тултипе.
COLUMN_TITLES = ["Год", "Месяц", "Раб. дни", "Вредн.", "Отпуск", "О/б/м", "По средн.", "Итого", "Балл", "Тариф"]
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

SOURCE_LABELS = {
    "override": "указана кадровиком вручную",
    "dnepr": "из карточки сотрудника (DNEPR)",
    "dnepr_invalid": "в карточке (DNEPR) неправдоподобная дата — проигнорирована, укажите вручную",
    None: "не указана — таймлайн начат с первого найденного расчёта",
}

TERMINATION_SOURCE_LABELS = {
    "data_uvl": "по карточке сотрудника (DATA_UVL)",
    "data_uvl_invalid": "в карточке (DATA_UVL) неправдоподобная дата — проигнорирована",
    "data_uvl_before_hire": "в карточке есть более ранняя дата увольнения — проигнорирована (похоже на переприём)",
    None: None,
}


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

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if not index.data(GRID_ROLE):
            return
        r = option.rect
        painter.save()
        if index.column() == self.hover_col:
            painter.fillRect(r, QColor(49, 130, 206, 30))
        painter.setPen(QColor("#CBD5E0"))  # явная вертикальная линия между колонками
        painter.drawLine(r.right(), r.top(), r.right(), r.bottom())
        painter.restore()

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(False)
        editor.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        editor.setStyleSheet(
            "QLineEdit {"
            " padding: 0px 8px; min-height: 0px; margin: 0px;"
            " border: 2px solid #3182CE; border-radius: 0px;"
            " background: #FFFFFF; color: #1A202C; font-size: 13px;"
            " selection-background-color: #3182CE; selection-color: #FFFFFF;"
            "}"
        )
        return editor

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class HistoryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Расчёт отпуска за вредность")
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

        self.build_ui()
        self.restore_window_state()
        self.reload_data()

    def restore_window_state(self) -> None:
        settings = QSettings("Dolomit", "InsalubrityHistory")
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
            self.top_toggle_btn.setText("▸")
            self.refresh_top_title()
        header_state = settings.value("table/header_state_v2")
        if header_state is not None:
            self.table.horizontalHeader().restoreState(header_state)

    def closeEvent(self, event) -> None:
        settings = QSettings("Dolomit", "InsalubrityHistory")
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("window/state", self.saveState())
        settings.setValue("table/header_state_v2", self.table.horizontalHeader().saveState())
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        main = QVBoxLayout(root)
        main.setContentsMargins(24, 16, 24, 16)
        main.setSpacing(10)

        # --- Заголовок + кнопка настроек папок ---
        header_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Расчёт отпуска за вредность")
        title.setObjectName("AppTitle")
        title.setToolTip("Поиск сотрудника по ФИО, помесячная и годовая статистика по RSV")
        title_col.addWidget(title)
        header_row.addLayout(title_col, 1)

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("UtilityButton")
        self.settings_btn.setFixedSize(36, 36)
        self.settings_btn.setStyleSheet("padding: 0; min-height: 0; font-size: 16px;")
        self.settings_btn.setToolTip("Папки с RSV и DBF")
        self.settings_btn.clicked.connect(self.toggle_paths_panel)
        header_row.addWidget(self.settings_btn, 0, Qt.AlignTop)

        # --- Компактная строка-сводка: текущие папки + быстрое обновление ---
        summary_row = QHBoxLayout()
        self.paths_summary_lbl = QLabel("")
        self.paths_summary_lbl.setObjectName("FieldCaption")
        summary_row.addWidget(self.paths_summary_lbl, 1)
        quick_refresh_btn = QPushButton("↻ Обновить данные")
        quick_refresh_btn.setObjectName("UtilityButton")
        quick_refresh_btn.clicked.connect(self.reload_data)
        summary_row.addWidget(quick_refresh_btn)

        # --- Верхняя часть целиком — то, что должно ужиматься сплиттером ---
        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(8)
        top_layout.addLayout(header_row)
        top_layout.addLayout(summary_row)

        # --- Папка с результатами RSV / DBF — свёрнуто по умолчанию, открывается шестерёнкой ---
        self.paths_card = QFrame()
        self.paths_card.setObjectName("Card")
        self.paths_card.setVisible(False)
        paths_layout = QHBoxLayout(self.paths_card)
        paths_layout.setContentsMargins(18, 14, 18, 14)
        paths_layout.setSpacing(10)

        paths_label = QLabel("Папка с результатами (RSV):")
        paths_label.setObjectName("FieldLabel")
        self.out_dir_input = QLineEdit(self.env_data.get("OUT_DIR", "./"))
        browse_out_btn = QPushButton("Обзор…")
        browse_out_btn.setObjectName("BrowseButton")
        browse_out_btn.clicked.connect(self.browse_out_dir)

        data_label = QLabel("Папка с DBF:")
        data_label.setObjectName("FieldLabel")
        self.data_dir_input = QLineEdit(self.env_data.get("DBF_DATA_DIR", "./dbf"))
        browse_data_btn = QPushButton("Обзор…")
        browse_data_btn.setObjectName("BrowseButton")
        browse_data_btn.clicked.connect(self.browse_data_dir)

        refresh_btn = QPushButton("Обновить данные")
        refresh_btn.setObjectName("UtilityButton")
        refresh_btn.clicked.connect(self.reload_data)

        paths_layout.addWidget(paths_label)
        paths_layout.addWidget(self.out_dir_input, 2)
        paths_layout.addWidget(browse_out_btn)
        paths_layout.addSpacing(12)
        paths_layout.addWidget(data_label)
        paths_layout.addWidget(self.data_dir_input, 2)
        paths_layout.addWidget(browse_data_btn)
        paths_layout.addStretch()
        paths_layout.addWidget(refresh_btn)

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
        self.top_toggle_btn.setObjectName("UtilityButton")
        self.top_toggle_btn.setFixedSize(30, 30)
        # Общий стиль QPushButton (padding 0 14px, min-height 38px) съедает
        # всё место в маленькой квадратной кнопке — глиф не помещается.
        self.top_toggle_btn.setStyleSheet("padding: 0; min-height: 0; font-size: 14px;")
        self.top_toggle_btn.setToolTip("Свернуть/развернуть блок «Сотрудник» и нормы")
        self.top_toggle_btn.clicked.connect(self.toggle_top_body)
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
        self.search_input.setPlaceholderText("Начните вводить ФИО…")
        self.completer = QCompleter([])
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchContains)
        self.search_input.setCompleter(self.completer)
        self.completer.activated[str].connect(self.on_employee_chosen)
        self.search_input.returnPressed.connect(self.on_search_enter)
        search_layout.addWidget(self.search_input)

        # Одна строка: источник даты устройства слева, поле даты + кнопка справа
        info_row = QHBoxLayout()

        self.hire_source_lbl = QLabel("Сотрудник не выбран")
        self.hire_source_lbl.setObjectName("FieldCaption")
        info_row.addWidget(self.hire_source_lbl, 1)

        hire_label = QLabel("Дата устройства:")
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
        info_row.addWidget(self.hire_date_edit)

        self.save_hire_btn = QPushButton("Сохранить дату")
        self.save_hire_btn.setObjectName("UtilityButton")
        self.save_hire_btn.setEnabled(False)
        self.save_hire_btn.clicked.connect(self.save_hire_date)
        info_row.addWidget(self.save_hire_btn)

        search_layout.addLayout(info_row)

        # --- Тонкий разделитель + нормы доп. отпуска (ст. 157 ТК) второй
        # строкой в ТОЙ ЖЕ карточке — раньше это была отдельная карточка со
        # своей рамкой/паддингами, из-за чего верх занимал заметно больше
        # места, чем нужно таблице.
        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("background-color: #E2E8F0; max-height: 1px; border: none;")
        search_layout.addWidget(divider)

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
            lbl = QLabel(f"{klass}:")
            lbl.setObjectName("FieldLabel")
            spin = QSpinBox()
            spin.setRange(0, 60)
            spin.setFixedWidth(70)
            spin.setValue(int(hr.DEFAULT_LEAVE_NORM_DAYS[klass]))
            pair.addWidget(lbl)
            pair.addWidget(spin)
            norms_layout.addLayout(pair)
            norms_layout.addSpacing(18)
            self.norm_spinboxes[klass] = spin

        save_norms_btn = QPushButton("Сохранить нормы")
        save_norms_btn.setObjectName("UtilityButton")
        save_norms_btn.clicked.connect(self.save_norm_days)
        norms_layout.addStretch()
        norms_layout.addWidget(save_norms_btn)

        search_layout.addLayout(norms_layout)

        top_layout.addWidget(search_card)

        self.load_norm_days_from_env()

        # --- Таблица по месяцам/годам ---
        table_card = QFrame()
        table_card.setObjectName("Card")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(16, 12, 16, 14)
        table_layout.setSpacing(8)

        table_title = QLabel("Помесячная и годовая статистика")
        table_title.setObjectName("SectionTitle")
        table_layout.addWidget(table_title)

        self.table = QTableWidget(0, 10)
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
            Qt.AlignRight | Qt.AlignVCenter,
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
        default_widths = [70, 110, 100, 90, 90, 80, 90, 90, 70, 90]
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
        self.table.viewport().installEventFilter(self)  # сброс подсветки колонки при уходе курсора
        self.table.itemChanged.connect(self.on_cell_item_changed)
        self.table.setAlternatingRowColors(False)  # чередование теперь по годам, не по строкам — см. add_month_row
        self.table.setMouseTracking(True)  # для корректного hover-подсвечивания строк
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.cellClicked.connect(self.on_table_cell_clicked)
        table_layout.addWidget(self.table)

        # --- Нижняя часть (таблица + статус) — то, что должно расти при растягивании окна ---
        bottom_container = QWidget()
        bottom_layout = QVBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(10)
        bottom_layout.addWidget(table_card, 1)

        self.status_lbl = QLabel("Готово")
        self.status_lbl.setObjectName("SectionHint")
        bottom_layout.addWidget(self.status_lbl)

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

        self.update_paths_summary()

    # ------------------------------------------------------------------
    # Загрузка данных
    # ------------------------------------------------------------------
    def toggle_top_body(self) -> None:
        self.set_top_collapsed(self.top_body.isVisible())

    def set_top_collapsed(self, collapsed: bool) -> None:
        self.top_body.setVisible(not collapsed)
        self.top_toggle_btn.setText("▸" if collapsed else "▾")
        self.refresh_top_title()
        QSettings("Dolomit", "InsalubrityHistory").setValue("ui/top_collapsed", collapsed)
        # Верхняя панель ужалась — отдаём освободившееся место таблице.
        QTimer.singleShot(0, lambda: self.main_splitter.setSizes([1, 5000]))

    def refresh_top_title(self) -> None:
        collapsed = not self.top_body.isVisible()
        if collapsed and self.current_tn is not None:
            row = self.employees.loc[self.employees["tn"] == self.current_tn]
            fio = format_fio(row.iloc[0]["fio"]) if not row.empty else "?"
            hd = self.current_hire_date
            hire_txt = f"{hd.day:02d}.{hd.month:02d}.{hd.year}" if hd is not None else "не указана"
            title = f"{fio}  ·  таб. № {self.current_tn}  ·  дата устройства: {hire_txt}"
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
        self.settings_btn.setToolTip("Скрыть настройки папок" if visible else "Папки с RSV и DBF")

    def update_paths_summary(self) -> None:
        def short(path_str: str, limit: int = 46) -> str:
            path_str = path_str.strip()
            if len(path_str) <= limit:
                return path_str
            return "…" + path_str[-(limit - 1):]

        out_text = short(self.out_dir_input.text())
        data_text = short(self.data_dir_input.text())
        self.paths_summary_lbl.setText(f"RSV: {out_text}   ·   DBF: {data_text}")
        self.paths_summary_lbl.setToolTip(
            f"RSV: {self.out_dir_input.text().strip()}\nDBF: {self.data_dir_input.text().strip()}"
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
        QMessageBox.information(self, "Сохранено", "Нормы доп. отпуска за вредность сохранены.")
        if self.current_tn is not None:
            self.select_employee(self.current_tn)

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
        self.sync_env_paths()
        self.update_paths_summary()
        out_dir = Path(self.out_dir_input.text().strip())
        data_dir = Path(self.data_dir_input.text().strip())

        messages: list[str] = []
        self.history = hr.build_history(out_dir, log=messages.append)

        try:
            self.employees = hr.get_lschet_employees(data_dir)
        except Exception as exc:
            self.employees = None
            QMessageBox.critical(
                self, "Ошибка чтения lschet.dbf",
                f"Не удалось прочитать список сотрудников:\n\n{exc}",
            )
            self.status_lbl.setText("Ошибка чтения lschet.dbf — список сотрудников недоступен")
            return

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
        self.status_lbl.setText(status)
        self.status_lbl.setToolTip("\n".join(messages))

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

    # ------------------------------------------------------------------
    # Выбор сотрудника
    # ------------------------------------------------------------------
    def on_search_enter(self) -> None:
        text = self.search_input.text().strip()
        if text in self.display_to_tn:
            self.on_employee_chosen(text)

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
        hire_label = f"Таб. № {tn}   •   дата устройства: {SOURCE_LABELS.get(source, source)}"
        early_warning = ""
        if early_months:
            first, last = early_months[0], early_months[-1]
            early_warning = (
                f"⚠ Есть RSV-данные РАНЬШЕ даты устройства: {len(early_months)} мес. "
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
            QMessageBox.warning(self, "Дата не указана", "Выберите дату устройства и повторите.")
            return
        date_str = f"{qd.year():04d}-{qd.month():02d}-{qd.day():02d}"
        try:
            hr.save_hire_date_override(self.current_tn, date_str)
        except ValueError as exc:
            QMessageBox.warning(self, "Некорректная дата устройства", str(exc))
            return
        except hr.OverrideFileError as exc:
            QMessageBox.critical(self, "Файл ручных правок недоступен", str(exc))
            return
        QMessageBox.information(self, "Сохранено", f"Дата устройства сохранена: {date_str}")
        self.select_employee(self.current_tn)

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
            self._set_hover_col(-1)
            self.year_blocks = []
            self.header_row_to_block = {}

            if self.history is None or self.history.empty:
                self.status_lbl.setText("Нет ни одного файла RSV — статистику показать нечем")
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
                self.status_lbl.setText("По этому сотруднику нет ни одной фактической записи в найденных RSV-файлах")
                return

            stale_count = sum(
                len(r.get("stale_fields") or {})
                for block in blocks for r in block["month_rows"]
            )
            status_parts = [self._early_warning, getattr(self, "_term_note", "")]
            if stale_count:
                status_parts.append(
                    f"⚠ Ручных правок, расходящихся с появившимся RSV: {stale_count} "
                    f"(красные ячейки — подтвердите или очистите)"
                )
            status_parts = [p for p in status_parts if p]
            self.status_lbl.setText("   •   ".join(status_parts) if status_parts else self._base_status)

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

                for r in block["month_rows"]:
                    qt_block["month_rows"].append(self.add_month_row(r, tint=tint))

                self.finish_work_year_block(block)

            # По умолчанию сворачиваем все рабочие годы, кроме последнего (самого
            # свежего) — так видно всю историю одним взглядом на заголовки+итоги,
            # а листать помесячно нужно только тот год, что реально интересен.
            last_idx = len(self.year_blocks) - 1
            for idx, qt_block in enumerate(self.year_blocks):
                collapsed = prev_collapsed.get(qt_block["label"], idx < last_idx)
                if collapsed:
                    self.set_block_collapsed(qt_block, True)

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
        if obj is self.table.viewport() and event.type() == QEvent.Leave:
            self._set_hover_col(-1)
        return super().eventFilter(obj, event)

    def on_table_cell_clicked(self, row: int, column: int) -> None:
        block = self.header_row_to_block.get(row)
        if block is None:
            return
        self.set_block_collapsed(block, not block["collapsed"])

    def set_block_collapsed(self, block: dict, collapsed: bool) -> None:
        block["collapsed"] = collapsed
        for r in block["month_rows"]:
            self.table.setRowHidden(r, collapsed)
        header_item = self.table.item(block["header_row"], 0)
        if header_item is not None:
            header_item.setText("▶" if collapsed else "▼")

    # Чередующийся фон по РАБОЧИМ ГОДАМ (а не по строкам, как раньше) — так
    # видно, где заканчивается один год и начинается следующий, даже когда
    # оба развёрнуты и строки идут подряд.
    YEAR_TINTS = (QColor("#FFFFFF"), QColor("#F7FAFC"))
    HEADER_TINTS = (QColor("#EDF2F7"), QColor("#E2E8F0"))

    def add_year_header_row(self, work_year_label: str, month_count: int, bg: QColor) -> int:
        text = f"Рабочий год {work_year_label}   ·   {month_count} мес.   (нажмите, чтобы свернуть/развернуть)"
        return self.add_span_row("▼", text, QColor("#1A202C"), bg)

    def add_column_header_row(self) -> int:
        """Мини-шапка с названиями колонок внутри блока рабочего года: название
        стоит рядом с данными, а не только в шапке таблицы вверху."""
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        self.table.setRowHeight(row_idx, 28)
        font = QFont()
        font.setBold(True)
        font.setPointSizeF(max(font.pointSizeF() - 1.5, 7.0))
        for col, title in enumerate(COLUMN_TITLES):
            item = QTableWidgetItem(title)
            item.setFont(font)
            item.setForeground(QColor("#718096"))
            item.setBackground(QColor("#F1F5F9"))
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
        item.setBackground(QColor("#E2E8F0"))
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

        if leave_entry.get("days_exceed_norm"):
            self.add_span_row(
                "⚠",
                f'Сумма дней ({leave_entry["total_days"]:.0f}) больше нормы рабочих дней графика '
                f'({kol_rd_total:.0f}) — возможно, отпуск указан в календарных днях или норма '
                f'графика занижена. «Вышло» ограничено нормой класса, результат стоит проверить.',
                QColor("#9C4221"),
                QColor("#FFFAF0"),
            )

        missing = block.get("missing_file_months") or []
        if missing:
            months_txt = ", ".join(f"{m:02d}.{y}" for y, m in missing[:12])
            if len(missing) > 12:
                months_txt += f" … (всего {len(missing)})"
            self.add_span_row(
                "⚠",
                f"Нет RSV-файла за: {months_txt}. Эти месяцы учтены как «вредности нет» "
                f"(норма дней — оценка), поэтому «вышло» может быть занижено.",
                QColor("#9C4221"),
                QColor("#FFFAF0"),
            )

        if leave_entry["unclassified_days"] > 0:
            self.add_span_row(
                "",
                f'Не учтено в расчёте отпуска: {leave_entry["unclassified_days"]:.0f} дн. '
                f'(класс вредности ещё ни разу не был определён на этот момент)',
                QColor("#B7791F"),
                QColor("#FFFBEB"),
            )

        for y_m, m_m, split in leave_entry.get("mixed_class_months", []):
            parts = ", ".join(f"{c:.1f} — {d:.0f} дн." for c, d in sorted(split.items()))
            usual = max(split.items(), key=lambda kv: (kv[1], kv[0]))[0]
            self.add_span_row(
                "",
                f"Смена класса в {m_m:02d}.{y_m}: дни вредности {parts} Отпуск и «по среднему» "
                f"этого месяца отнесены к классу {usual:.1f}.",
                QColor("#553C9A"),
                QColor("#FAF5FF"),
            )

        if len(classes) > 1:
            # Несколько классов за раб. год — показываем разбивку сложения по каждому,
            # чтобы было видно, из чего сложилось "положено" и "вышло".
            polozheno_parts = " + ".join(f'{c["norm"]:.0f}' for c in classes)
            vyshlo_parts = " + ".join(f'{c["vyshlo"]:.2f}' for c in classes)
            summary_text = (
                f'Отпуск за вредность: положено {polozheno_parts} = {leave_entry["polozheno_total"]:.0f} дн., '
                f'вышло {vyshlo_parts} = {leave_entry["vyshlo_total"]:.2f} дн.'
            )
        else:
            summary_text = (
                f'Отпуск за вредность: положено {leave_entry["polozheno_total"]:.0f} дн., '
                f'вышло {leave_entry["vyshlo_total"]:.2f} дн.'
            )

        self.add_span_row("ОТПУСК", summary_text, QColor("#2C5282"), QColor("#EBF8FF"))

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
        "kol_rd": "Раб. дни", "vred_dni": "Вредность", "bal_vredn": "Балл",
        "otp_dni": "Отпуск", "otp_bud_m": "О/б/м", "po_sredn": "По средн.",
    }

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

    def add_month_row(self, r, tint: QColor | None = None) -> int:
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)

        has_data = bool(r["has_data"])
        overridden_fields = r.get("overridden_fields") or {}
        stale_fields = r.get("stale_fields") or {}
        is_data_fix = bool(r.get("is_data_fix", False))
        data_fix_note = r.get("data_fix_note")
        is_projected = bool(r.get("is_projected", False))

        base_color = QColor("#1A202C") if has_data else QColor("#A0AEC0")
        # Прогноз — не точечная правка одного поля, а вся строка целиком,
        # поэтому вместо цвета текста заливаем всю строку светло-зелёным
        # (перебивает обычное чередование по годам) — так заметнее, чем
        # просто цветной текст на белом. Текст берём потемнее самой заливки,
        # чтобы не потерять контраст (обычный серый "нет данных" на светлой
        # заливке был бы едва читаем).
        row_fill = None
        if is_projected:
            row_fill = QColor("#EDFDF3")
            base_color = QColor("#276749")

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
            "" if r["tar1"] in (None,) or (isinstance(r["tar1"], float) and r["tar1"] != r["tar1"]) else f'{r["tar1"]:.2f}',
        ]
        year, month = int(r["year"]), int(r["month"])

        bal_carried = bool(r.get("bal_vredn_carried", False))
        carried_tooltip = None
        if bal_carried:
            src_y, src_m = r.get("bal_vredn_source_year"), r.get("bal_vredn_source_month")
            if src_y is not None and src_m is not None and src_y == src_y and src_m == src_m:  # не NaN
                carried_tooltip = (
                    f"Балл: в этом месяце в RSV не было строки вредности — класс перенесён "
                    f"с {int(src_m):02d}.{int(src_y)} (последний месяц, когда он был подтверждён по RSV)"
                )
            else:
                carried_tooltip = "Балл: перенесён с более раннего месяца, не подтверждён RSV в этом месяце"

        for col, val in enumerate(values):
            item = QTableWidgetItem(val)
            item.setData(GRID_ROLE, True)
            field = self.EDITABLE_COLUMNS.get(col)
            is_overridden_here = field is not None and field in overridden_fields
            # Автопочинка (сейчас — только колонка kol_rd, см. fix_zero_kol_rd_months)
            # красится отдельным акцентом, но ручная правка кадровика на том
            # же поле имеет приоритет над этой пометкой.
            is_fixed_here = field == "kol_rd" and is_data_fix and not is_overridden_here
            # "Балл" перенесён по ffill, а не подтверждён RSV в этом месяце —
            # свой акцент, в том числе и внутри прогнозных (зелёных) строк:
            # для них класс тоже всегда перенесённый, раз в самом месяце
            # никакой RSV-строки нет и не может быть.
            is_carried_here = field == "bal_vredn" and bal_carried and not is_overridden_here

            if is_overridden_here:
                # Красим ТОЛЬКО эту ячейку — остальная строка сохраняет свой
                # обычный вид. Акцент — на ЗАЛИВКЕ (насыщенный жёлтый), а не
                # на цвете текста, который на белом фоне почти не заметен.
                item.setForeground(QColor("#7B341E"))
                item.setBackground(QColor("#FBD38D"))
                bold_font = QFont()
                bold_font.setBold(True)
                item.setFont(bold_font)
                tip = self._override_tooltip(field, overridden_fields[field], r, has_data)
                if field in stale_fields:
                    # Правку вводили, пока настоящего RSV за месяц не было; теперь он
                    # есть и отличается — красная заливка вместо жёлтой.
                    was, now = stale_fields[field]
                    item.setForeground(QColor("#742A2A"))
                    item.setBackground(QColor("#FEB2B2"))
                    tip += (
                        f"\n⚠ Правку вводили, когда RSV за этот месяц ещё не было. "
                        f"Теперь в RSV: {self._fmt_field_value(field, was)}, "
                        f"в правке: {self._fmt_field_value(field, now)}. "
                        f"Введите значение заново, чтобы подтвердить, или очистите ячейку, "
                        f"чтобы взять значение из RSV."
                    )
                item.setToolTip(tip)
            elif is_fixed_here:
                # Автоматическая починка сбоя календаря (kol_rd=0 в RSV при
                # реально отработанном месяце) — свой акцент заливкой,
                # отличимый и от жёлтой ручной правки, и от зелёного прогноза.
                item.setForeground(QColor("#234E52"))
                item.setBackground(QColor("#81E6D9"))
                bold_font = QFont()
                bold_font.setBold(True)
                item.setFont(bold_font)
                if isinstance(data_fix_note, str) and data_fix_note:
                    item.setToolTip(data_fix_note)
            elif is_carried_here:
                # Класс вредности перенесён с более раннего месяца (ffill),
                # а не подтверждён RSV-строкой в ЭТОМ месяце — фиолетовый
                # акцент, отличимый от жёлтой правки/бирюзовой починки/
                # зелёного прогноза.
                item.setForeground(QColor("#553C9A"))
                item.setBackground(QColor("#E9D8FD"))
                bold_font = QFont()
                bold_font.setBold(True)
                item.setFont(bold_font)
                if carried_tooltip:
                    item.setToolTip(carried_tooltip)
            else:
                item.setForeground(base_color)
                if row_fill is not None:
                    item.setBackground(row_fill)
                elif tint is not None:
                    item.setBackground(tint)
                if row_tooltip:
                    item.setToolTip(row_tooltip)

            if field == "bal_vredn" and not is_overridden_here:
                split = hr.month_class_split(r)
                if split:
                    parts = "; ".join(f"{c:.1f} — {d:.0f} дн." for c, d in sorted(split.items()))
                    usual = max(split.items(), key=lambda kv: (kv[1], kv[0]))[0]
                    item.setToolTip(
                        f"Смена класса в этом месяце: {parts} В ячейке показан класс с большим числом "
                        f"дней вредности; отпуск и «по среднему» месяца относятся к нему ({usual:.1f})."
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
        values = [
            "ИТОГО", work_year_label, str(round(kol_rd_total)), str(round(vred_total)),
            "", "", "", str(round(monthly_total)), "", "",
        ]
        for col, val in enumerate(values):
            item = QTableWidgetItem(val)
            item.setData(GRID_ROLE, True)
            item.setFont(bold)
            item.setForeground(QColor("#2C5282"))
            item.setBackground(QColor("#EBF8FF"))
            item.setTextAlignment(int(self.COLUMN_ALIGN[col]))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_idx, col, item)

    def add_leave_class_row(
        self, klass: float, days: float, norm: float, kol_rd_total: float, vyshlo: float,
        capped: bool = False, vyshlo_raw: float | None = None,
    ) -> None:
        text = f'  ↳ класс {klass}: ({days:.0f} дн. × {norm:.0f}) / {kol_rd_total:.0f} раб.дн. = {vyshlo:.2f} дн. отпуска'
        if capped and vyshlo_raw is not None:
            text = (
                f'  ↳ класс {klass}: ({days:.0f} дн. × {norm:.0f}) / {kol_rd_total:.0f} раб.дн. = '
                f'{vyshlo_raw:.2f} → ограничено нормой класса: {vyshlo:.2f} дн. отпуска'
            )
        self.add_span_row(
            "",
            text,
            QColor("#9C4221") if capped else QColor("#4A5568"),
            QColor("#FFFAF0") if capped else QColor("#F7FAFC"),
        )

    def add_span_row(
        self, col0_text: str, span_text: str, fg_color: QColor,
        bg_color: QColor | None = None, tooltip: str | None = None,
    ) -> int:
        """Строка-аннотация: короткая метка в первой колонке + текст на всю остальную ширину."""
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        bold = QFont()
        bold.setBold(True)

        item0 = QTableWidgetItem(col0_text)
        item0.setFont(bold)
        item0.setForeground(fg_color)
        if bg_color is not None:
            item0.setBackground(bg_color)
        item0.setTextAlignment(Qt.AlignCenter)
        if tooltip:
            item0.setToolTip(tooltip)
        item0.setFlags(item0.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row_idx, 0, item0)

        span_item = QTableWidgetItem(span_text)
        span_item.setFont(bold)
        span_item.setForeground(fg_color)
        if bg_color is not None:
            span_item.setBackground(bg_color)
        span_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if tooltip:
            span_item.setToolTip(tooltip)
        span_item.setFlags(span_item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row_idx, 1, span_item)
        self.table.setSpan(row_idx, 1, 1, self.table.columnCount() - 1)
        return row_idx


def pd_isna(value) -> bool:
    try:
        return value is None or value != value  # NaN != NaN
    except Exception:
        return value is None


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    install_excepthook("Расчёт отпуска за вредность")

    window = HistoryWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()