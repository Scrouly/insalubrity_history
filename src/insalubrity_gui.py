"""
insalubrity_gui.py
==================
Современный графический интерфейс на PyQt5 для расчёта доплат
за вредные условия труда и формирования ведомости RSV.
"""

from __future__ import annotations

import sys
import html
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, QThread, QTimer, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QFont
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_env import (
    EnvFileError,
    install_excepthook,
    load_env_vars,
    save_env_vars,
    migrate_legacy_data,
)
from insalubrity import run as run_calc


MONTH_NAMES = [
    "01 — Январь",
    "02 — Февраль",
    "03 — Март",
    "04 — Апрель",
    "05 — Май",
    "06 — Июнь",
    "07 — Июль",
    "08 — Август",
    "09 — Сентябрь",
    "10 — Октябрь",
    "11 — Ноябрь",
    "12 — Декабрь",
]

STYLESHEET = """
* {
    font-family: "Segoe UI", "Arial", sans-serif;
}

QMainWindow, QWidget#Root {
    background: #F5F6F8;
    color: #1A202C;
}

QFrame#TopBar {
    background: transparent;
}

QLabel#AppTitle {
    color: #1A202C;
    font-size: 25px;
    font-weight: 700;
}

QLabel#AppSubtitle {
    color: #718096;
    font-size: 14px;
}

QLabel#SectionTitle {
    color: #1A202C;
    font-size: 16px;
    font-weight: 700;
}

QLabel#SectionHint {
    color: #4A5568;
    font-size: 13px;
}

QFrame#Card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
}

QFrame#MiniCard {
    background: #F7FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
}

QLabel#FieldLabel {
    color: #4A5568;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.4px;
}

QLabel#FieldCaption {
    color: #718096;
    font-size: 12px;
}

QLineEdit, QComboBox, QSpinBox, QDateEdit {
    background: #FFFFFF;
    color: #1A202C;
    border: 1px solid #CBD5E0;
    border-radius: 8px;
    padding: 8px 12px;
    min-height: 20px;
    selection-background-color: #3182CE;
    selection-color: #ffffff;
}

QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDateEdit:hover {
    border-color: #A0AEC0;
}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus {
    border: 1px solid #3182CE;
}

QLineEdit:disabled, QSpinBox:disabled, QDateEdit:disabled {
    background: #F7FAFC;
    color: #A0AEC0;
    border-color: #E2E8F0;
}

QSpinBox::up-button, QSpinBox::down-button {
    width: 18px;
    border: none;
    background: transparent;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox QAbstractItemView, QListView {
    background: #FFFFFF;
    color: #1A202C;
    border: 1px solid #E2E8F0;
    selection-background-color: #3182CE;
    selection-color: white;
    padding: 4px;
    outline: none;
}

QPushButton {
    min-height: 38px;
    border-radius: 8px;
    padding: 0 14px;
    font-size: 14px;
    font-weight: 600;
}

QPushButton#BrowseButton, QPushButton#UtilityButton {
    background: #F7FAFC;
    color: #2D3748;
    border: 1px solid #E2E8F0;
}

QPushButton#BrowseButton:hover, QPushButton#UtilityButton:hover {
    background: #EDF2F7;
    border-color: #CBD5E0;
}

QPushButton#BrowseButton:pressed, QPushButton#UtilityButton:pressed {
    background: #E2E8F0;
}

QPushButton#MainActionBtn {
    background: #3182CE;
    color: white;
    border: none;
    min-height: 48px;
    font-size: 14px;
    font-weight: 700;
}

QPushButton#MainActionBtn:hover {
    background: #2B6CB0;
}

QPushButton#MainActionBtn:pressed {
    background: #2C5282;
}

QPushButton#MainActionBtn:disabled {
    background: #E2E8F0;
    color: #A0AEC0;
}

QPushButton#FileButton {
    background: #FFFFFF;
    color: #2D3748;
    border: 1px solid #E2E8F0;
    min-height: 36px;
}

QPushButton#FileButton:hover {
    background: #F7FAFC;
    border-color: #CBD5E0;
}

QPushButton#FileButton:disabled {
    color: #A0AEC0;
    background: #F7FAFC;
    border-color: #E2E8F0;
}

QLabel#StatusPill {
    background: #EDF2F7;
    color: #718096;
    border: 1px solid #E2E8F0;
    border-radius: 11px;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 600;
}

QLabel#StatusPill[mode="success"] {
    color: #276749;
    border-color: #9AE6B4;
    background: #F0FFF4;
}

QLabel#StatusPill[mode="working"] {
    color: #2C5282;
    border-color: #90CDF4;
    background: #EBF8FF;
}

QLabel#StatusPill[mode="error"] {
    color: #C53030;
    border-color: #FEB2B2;
    background: #FFF5F5;
}

QLabel#MetricValue {
    color: #1A202C;
    font-size: 23px;
    font-weight: 700;
}

QLabel#MetricTitle {
    color: #718096;
    font-size: 12px;
    font-weight: 700;
}

QLabel#MetricNote {
    color: #A0AEC0;
    font-size: 11px;
}

QProgressBar {
    background: #E2E8F0;
    border: none;
    border-radius: 4px;
    min-height: 7px;
    max-height: 7px;
}

QProgressBar::chunk {
    background: #3182CE;
    border-radius: 4px;
}

QTextEdit#LogArea {
    background: #FFFFFF;
    color: #2D3748;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    padding: 10px;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 12px;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 6px;
}

QScrollBar::handle:vertical {
    background: #CBD5E0;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #A0AEC0;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QMessageBox {
    background: #FFFFFF;
    color: #1A202C;
    border: 1px solid #E2E8F0;
}

QMessageBox QLabel {
    background: transparent;
    color: #1A202C;
    font-size: 13px;
}

QMessageBox QPushButton {
    background: #F7FAFC;
    color: #1A202C;
    border: 1px solid #CBD5E0;
    border-radius: 8px;
    min-width: 88px;
    min-height: 34px;
    padding: 0 14px;
    font-size: 13px;
    font-weight: 600;
}

QMessageBox QPushButton:hover {
    background: #EDF2F7;
    border-color: #A0AEC0;
}

QMessageBox QPushButton:pressed {
    background: #E2E8F0;
}

QMessageBox QPushButton:default {
    background: #3182CE;
    color: #ffffff;
    border-color: #3182CE;
}

QMessageBox QPushButton:default:hover {
    background: #2B6CB0;
    border-color: #2B6CB0;
}

QTableWidget {
    background: #FFFFFF;
    color: #1A202C;
    gridline-color: #E2E8F0;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    outline: none;
    font-size: 13px;
}

QTableWidget::item {
    padding: 7px 10px;
}

QTableWidget::item:selected {
    background: #BEE3F8;
    color: #1A202C;
}

QTableWidget::item:hover {
    background: #F7FAFC;
}

QHeaderView::section {
    background: #F7FAFC;
    color: #4A5568;
    padding: 9px 8px;
    border: none;
    border-bottom: 1px solid #E2E8F0;
    border-right: 1px solid #EDF2F7;
    font-weight: 700;
    font-size: 12px;
}

QTableCornerButton::section {
    background: #F7FAFC;
    border: none;
}

QSplitter::handle {
    background: #E2E8F0;
}

QSplitter::handle:hover {
    background: #A0AEC0;
}

QSplitter::handle:vertical {
    height: 6px;
}
"""


class VrednWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(dict, int, int)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        data_dir: Path,
        month: int,
        year: int,
        s1: float,
        s2: float,
        s3: float,
        out_dir: Path,
    ):
        super().__init__()
        self.data_dir = data_dir
        self.month = month
        self.year = year
        self.s1 = s1
        self.s2 = s2
        self.s3 = s3
        self.out_dir = out_dir

    def run(self) -> None:
        try:
            self.log_signal.emit(
                f"Старт расчёта за {self.month:02d}.{self.year}..."
            )

            results = run_calc(
                data_dir=self.data_dir,
                month=self.month,
                year=self.year,
                stavka1=self.s1,
                stavka2=self.s2,
                stavka3=self.s3,
                out_dir=self.out_dir,
                log_callback=self.log_signal.emit,
            )

            self.finished_signal.emit(results, self.month, self.year)

        except Exception as exc:
            self.error_signal.emit(str(exc))


class VrednMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Расчёт вредных условий труда")
        self.resize(1100, 760)
        self.setMinimumSize(900, 640)
        self.setStyleSheet(STYLESHEET)

        self.env_data = load_env_vars()
        self.warning_count = 0
        self.last_rsv_path: Path | None = None
        self.worker: VrednWorker | None = None
        self._last_env_error: str | None = None
        # Запись .env не на каждый символ, а через 0.6 с после последнего изменения.
        self._env_timer = QTimer(self)
        self._env_timer.setSingleShot(True)
        self._env_timer.setInterval(600)
        self._env_timer.timeout.connect(self.sync_env)

        self.init_ui()
        self.apply_env_to_ui()
        self.bind_env_auto_save()
        self.animate_intro()

    def make_section_header(self, title: str, hint: str) -> QVBoxLayout:
        layout = QVBoxLayout()
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")

        hint_label = QLabel(hint)
        hint_label.setObjectName("SectionHint")

        layout.addWidget(title_label)
        layout.addWidget(hint_label)
        return layout

    def make_field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def make_metric_card(self, title: str, value: str, note: str) -> tuple[QFrame, QLabel]:
        card = QFrame()
        card.setObjectName("MiniCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("MetricTitle")

        value_label = QLabel(value)
        value_label.setObjectName("MetricValue")

        note_label = QLabel(note)
        note_label.setObjectName("MetricNote")

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(note_label)

        return card, value_label

    def init_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)

        main = QVBoxLayout(root)
        main.setContentsMargins(22, 18, 22, 18)
        main.setSpacing(12)

        # Header
        header = QHBoxLayout()
        header.setSpacing(12)

        title_block = QVBoxLayout()
        title_block.setSpacing(3)

        title = QLabel("Расчёт доплат за вредные условия труда")
        title.setObjectName("AppTitle")

        subtitle = QLabel(
            "Формирование ведомости RSV  •  настройки автоматически сохраняются"
        )
        subtitle.setObjectName("AppSubtitle")

        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block)
        header.addStretch()

        self.header_status = QLabel("ГОТОВ К РАБОТЕ")
        self.header_status.setObjectName("StatusPill")
        self.header_status.setProperty("mode", "success")
        header.addWidget(self.header_status, alignment=Qt.AlignTop)

        main.addLayout(header)

        # Main upper content
        content = QHBoxLayout()
        content.setSpacing(16)

        # Settings card
        settings_card = QFrame()
        settings_card.setObjectName("Card")
        settings = QVBoxLayout(settings_card)
        settings.setContentsMargins(18, 16, 18, 16)
        settings.setSpacing(12)

        settings_header = self.make_section_header(
            "Параметры расчёта",
            "Укажите источник DBF, период и тарифные ставки",
        )
        settings.addLayout(settings_header)

        dbf_label = self.make_field_label("ПАПКА С БАЗАМИ DBF")
        settings.addWidget(dbf_label)

        dbf_row = QHBoxLayout()
        dbf_row.setSpacing(8)

        self.data_dir_input = QLineEdit()
        self.data_dir_input.setMinimumHeight(42)
        self.data_dir_input.setPlaceholderText("./dbf")

        self.browse_dir_btn = QPushButton("Обзор")
        self.browse_dir_btn.setObjectName("BrowseButton")
        self.browse_dir_btn.clicked.connect(self.browse_data_dir)

        dbf_row.addWidget(self.data_dir_input, 1)
        dbf_row.addWidget(self.browse_dir_btn)
        settings.addLayout(dbf_row)

        period_grid = QGridLayout()
        period_grid.setHorizontalSpacing(12)
        period_grid.setVerticalSpacing(7)

        month_block = QVBoxLayout()
        month_block.setSpacing(6)
        month_block.addWidget(self.make_field_label("МЕСЯЦ"))

        self.month_combo = QComboBox()
        self.month_combo.setMinimumHeight(42)
        self.month_combo.addItems(MONTH_NAMES)
        month_block.addWidget(self.month_combo)

        year_block = QVBoxLayout()
        year_block.setSpacing(6)
        year_block.addWidget(self.make_field_label("ГОД"))

        self.year_combo = QComboBox()
        self.year_combo.setMinimumHeight(42)
        current_year = datetime.now().year
        self.year_combo.addItems(
            [str(year) for year in range(current_year + 1, current_year - 6, -1)]
        )
        self.year_combo.setCurrentText(str(current_year))
        year_block.addWidget(self.year_combo)

        period_grid.addLayout(month_block, 0, 0)
        period_grid.addLayout(year_block, 0, 1)
        period_grid.setColumnStretch(0, 3)
        period_grid.setColumnStretch(1, 2)

        settings.addLayout(period_grid)

        out_label = self.make_field_label("ПАПКА ДЛЯ EXCEL")
        settings.addWidget(out_label)

        out_row = QHBoxLayout()
        out_row.setSpacing(8)

        self.out_dir_input = QLineEdit()
        self.out_dir_input.setMinimumHeight(42)
        self.out_dir_input.setPlaceholderText("./")

        self.browse_out_btn = QPushButton("Обзор")
        self.browse_out_btn.setObjectName("BrowseButton")
        self.browse_out_btn.clicked.connect(self.browse_out_dir)

        out_row.addWidget(self.out_dir_input, 1)
        out_row.addWidget(self.browse_out_btn)
        settings.addLayout(out_row)

        rates_title = QHBoxLayout()
        rates_title.addWidget(self.make_field_label("ТАРИФНЫЕ СТАВКИ"))
        rates_title.addStretch()
        rates_hint = QLabel("Классы 3.1 / 3.2 / 3.3")
        rates_hint.setObjectName("FieldCaption")
        rates_title.addWidget(rates_hint)
        settings.addLayout(rates_title)

        rates_grid = QGridLayout()
        rates_grid.setHorizontalSpacing(10)

        self.s1_input = QLineEdit()
        self.s2_input = QLineEdit()
        self.s3_input = QLineEdit()
        for rate_input in (self.s1_input, self.s2_input, self.s3_input):
            rate_input.setMinimumHeight(42)

        self.s1_input.setPlaceholderText("0.29")
        self.s2_input.setPlaceholderText("0.41")
        self.s3_input.setPlaceholderText("0.58")

        rates_grid.addWidget(self.make_field_label("3.1"), 0, 0)
        rates_grid.addWidget(self.s1_input, 1, 0)
        rates_grid.addWidget(self.make_field_label("3.2"), 0, 1)
        rates_grid.addWidget(self.s2_input, 1, 1)
        rates_grid.addWidget(self.make_field_label("3.3"), 0, 2)
        rates_grid.addWidget(self.s3_input, 1, 2)

        settings.addLayout(rates_grid)

        self.start_btn = QPushButton("Выполнить расчёт и сформировать файлы")
        self.start_btn.setObjectName("MainActionBtn")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self.start_calculation)
        settings.addWidget(self.start_btn)

        content.addWidget(settings_card, 3)

        # Results card
        results_card = QFrame()
        results_card.setObjectName("Card")
        results = QVBoxLayout(results_card)
        results.setContentsMargins(18, 16, 18, 16)
        results.setSpacing(11)

        results_header = self.make_section_header(
            "Результат",
            "После расчёта здесь появятся контрольные показатели",
        )
        results.addLayout(results_header)

        metrics_grid = QGridLayout()
        metrics_grid.setSpacing(10)

        rsv_card, self.rsv_value = self.make_metric_card(
            "ВРЕДНОСТЬ", "—", "сумма дней"
        )
        rows_card, self.rows_value = self.make_metric_card(
            "СТРОК", "—", "сформировано записей"
        )

        metrics_grid.addWidget(rsv_card, 0, 0)
        metrics_grid.addWidget(rows_card, 0, 1)

        results.addLayout(metrics_grid)

        results.addWidget(QLabel("Доступные файлы"), alignment=Qt.AlignLeft)

        self.open_rsv_btn = QPushButton("Открыть  •  RSV")
        self.open_rsv_btn.setObjectName("FileButton")
        self.open_rsv_btn.setEnabled(False)
        self.open_rsv_btn.clicked.connect(self.open_rsv_file)

        self.open_folder_btn = QPushButton("Открыть папку результатов")
        self.open_folder_btn.setObjectName("UtilityButton")
        self.open_folder_btn.clicked.connect(self.open_output_folder)

        results.addWidget(self.open_rsv_btn)
        results.addWidget(self.open_folder_btn)
        results.addStretch()

        self.status_lbl = QLabel("Готов к запуску")
        self.status_lbl.setObjectName("SectionHint")
        results.addWidget(self.status_lbl)

        content.addWidget(results_card, 2)
        main.addLayout(content)

        # Progress + log card
        log_card = QFrame()
        log_card.setObjectName("Card")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(18, 12, 18, 12)
        log_layout.setSpacing(7)

        log_header = QHBoxLayout()

        log_title = QLabel("Журнал выполнения")
        log_title.setObjectName("SectionTitle")

        log_header.addWidget(log_title)
        log_header.addStretch()

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedWidth(185)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        log_header.addWidget(self.progress_bar)

        log_layout.addLayout(log_header)

        self.log_area = QTextEdit()
        self.log_area.setObjectName("LogArea")
        self.log_area.setReadOnly(True)
        self.log_area.setMinimumHeight(125)
        self.log_area.setPlaceholderText(
            "После запуска здесь появится журнал расчёта..."
        )
        log_layout.addWidget(self.log_area)

        main.addWidget(log_card, 1)

    def apply_env_to_ui(self) -> None:
        self.data_dir_input.setText(self.env_data.get("DBF_DATA_DIR", "./dbf"))
        self.out_dir_input.setText(self.env_data.get("OUT_DIR", "./"))

        try:
            month_value = int(self.env_data.get("CALC_MONTH", "5"))
        except (TypeError, ValueError):
            month_value = 5
        if 1 <= month_value <= 12:
            self.month_combo.setCurrentIndex(month_value - 1)

        year_value = self.env_data.get("CALC_YEAR", str(datetime.now().year))
        year_index = self.year_combo.findText(year_value)
        if year_index >= 0:
            self.year_combo.setCurrentIndex(year_index)

        self.s1_input.setText(self.env_data.get("STAVKA1", "0.29"))
        self.s2_input.setText(self.env_data.get("STAVKA2", "0.41"))
        self.s3_input.setText(self.env_data.get("STAVKA3", "0.58"))

    def bind_env_auto_save(self) -> None:
        self.data_dir_input.textChanged.connect(self.schedule_env_sync)
        self.out_dir_input.textChanged.connect(self.schedule_env_sync)
        self.month_combo.currentIndexChanged.connect(self.schedule_env_sync)
        self.year_combo.currentTextChanged.connect(self.schedule_env_sync)
        self.s1_input.textChanged.connect(self.schedule_env_sync)
        self.s2_input.textChanged.connect(self.schedule_env_sync)
        self.s3_input.textChanged.connect(self.schedule_env_sync)

    def schedule_env_sync(self) -> None:
        self._env_timer.start()  # перезапуск отсчёта при каждом изменении

    def sync_env(self) -> None:
        self._env_timer.stop()
        config = {
            "DBF_DATA_DIR": self.data_dir_input.text().strip(),
            "OUT_DIR": self.out_dir_input.text().strip(),
            "CALC_MONTH": str(self.month_combo.currentIndex() + 1),
            "CALC_YEAR": self.year_combo.currentText().strip(),
            "STAVKA1": self.s1_input.text().strip(),
            "STAVKA2": self.s2_input.text().strip(),
            "STAVKA3": self.s3_input.text().strip(),
        }
        try:
            save_env_vars(config)  # слияние: чужие ключи (LEAVE_DAYS_*) сохраняются
            self._last_env_error = None
        except EnvFileError as exc:
            msg = str(exc)
            if msg != self._last_env_error:  # один диалог на одну и ту же ошибку
                self._last_env_error = msg
                QMessageBox.warning(self, "Настройки не сохранены", msg)

    def closeEvent(self, event) -> None:
        # Закрыть окно при работающем QThread = «QThread: Destroyed while thread
        # is still running» (падение при выходе) и недописанный RSV-файл.
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "Расчёт выполняется",
                "Дождитесь окончания расчёта — окно можно закрыть после его завершения.",
            )
            event.ignore()
            return
        if self._env_timer.isActive():
            self.sync_env()  # не потерять последние введённые значения
        super().closeEvent(event)

    def animate_intro(self) -> None:
        # Лёгкое появление основной формы без лишних анимаций во время работы.
        effect = QGraphicsOpacityEffect(self.centralWidget())
        self.centralWidget().setGraphicsEffect(effect)

        self.intro_anim = QPropertyAnimation(effect, b"opacity", self)
        self.intro_anim.setDuration(450)
        self.intro_anim.setStartValue(0.0)
        self.intro_anim.setEndValue(1.0)
        self.intro_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.intro_anim.start()

    def set_status(self, text: str, mode: str = "") -> None:
        self.header_status.setText(text)
        self.header_status.setProperty("mode", mode)
        self.header_status.style().unpolish(self.header_status)
        self.header_status.style().polish(self.header_status)
        self.header_status.update()

    def browse_data_dir(self) -> None:
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку с базами DBF",
            self.data_dir_input.text(),
        )
        if selected_dir:
            self.data_dir_input.setText(selected_dir)

    def browse_out_dir(self) -> None:
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Выберите папку для сохранения Excel",
            self.out_dir_input.text(),
        )
        if selected_dir:
            self.out_dir_input.setText(selected_dir)

    def append_log(self, text: str) -> None:
        upper = text.upper()

        if "ОШИБКА" in upper or "ВНИМАНИЕ" in upper:
            color = "#C53030"
            self.warning_count += 1
        elif "ГОТОВО" in upper or "УСПЕХ" in upper:
            color = "#276749"
        elif "КОНТРОЛЬНАЯ СУММА" in upper:
            color = "#B7791F"
        elif "СТАРТ" in upper or "ЗАГРУЗКА" in upper:
            color = "#2B6CB0"
        else:
            color = "#4A5568"

        # Раньше текст лога вставлялся как HTML без экранирования — строки трейсбека
        # с "<module>" или "&" в путях терялись/ломали разметку лога. pre-wrap
        # сохраняет ведущие пробелы (отступы трейсбека), но переносит длинные строки.
        safe_text = html.escape(text)
        self.log_area.append(
            f'<span style="color:{color}; white-space:pre-wrap;">{safe_text}</span>'
        )
        scrollbar = self.log_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def start_calculation(self) -> None:
        data_dir = Path(self.data_dir_input.text().strip())
        out_dir = Path(self.out_dir_input.text().strip())

        if not data_dir.exists():
            QMessageBox.critical(
                self,
                "Папка не найдена",
                f"Папка с базами DBF не найдена:\n\n{data_dir}",
            )
            return

        out_dir.mkdir(parents=True, exist_ok=True)

        month = self.month_combo.currentIndex() + 1
        year = int(self.year_combo.currentText())

        try:
            s1 = float(self.s1_input.text().replace(",", ".").strip())
            s2 = float(self.s2_input.text().replace(",", ".").strip())
            s3 = float(self.s3_input.text().replace(",", ".").strip())
        except ValueError:
            QMessageBox.warning(
                self,
                "Ошибка ввода",
                "Тарифные ставки должны быть числами.",
            )
            return

        rates = {"3.1": s1, "3.2": s2, "3.3": s3}
        bad = [name for name, v in rates.items() if not (v > 0) or v != v or v in (float("inf"), float("-inf"))]
        if bad:
            QMessageBox.warning(
                self,
                "Ошибка ввода",
                f"Тарифная(ые) ставка(и) {', '.join(bad)} должна(ы) быть положительным конечным числом.",
            )
            return
        if not (s1 < s2 < s3):
            reply = QMessageBox.question(
                self,
                "Проверьте ставки",
                f"Обычно ставки идут по возрастанию классов: 3.1 < 3.2 < 3.3.\n"
                f"Сейчас введено: 3.1={s1}, 3.2={s2}, 3.3={s3}.\n\n"
                f"Строки с балльностью не удастся классифицировать и они попадут "
                f"в «ВНИМАНИЕ» без класса 3.1/3.2/3.3. Продолжить как есть?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        self.sync_env()

        self.start_btn.setEnabled(False)
        self.start_btn.setText("Расчёт выполняется…")
        self.set_status("ВЫПОЛНЕНИЕ", "working")
        self.status_lbl.setText("Идёт обработка DBF и формирование Excel…")
        self.progress_bar.setRange(0, 0)
        self.log_area.clear()
        self.warning_count = 0

        self.rsv_value.setText("…")
        self.rows_value.setText("…")

        self.worker = VrednWorker(
            data_dir=data_dir,
            month=month,
            year=year,
            s1=s1,
            s2=s2,
            s3=s3,
            out_dir=out_dir,
        )

        self.worker.log_signal.connect(self.append_log)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.error_signal.connect(self.on_error)
        self.worker.start()

    def on_finished(self, results: dict, month: int, year: int) -> None:
        self.start_btn.setEnabled(True)
        self.start_btn.setText("Выполнить расчёт и сформировать файлы")

        sum_rsv = results["sum_rsv"]

        self.status_lbl.setText(
            f"Расчёт за {month:02d}.{year} завершён"
        )
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)

        self.last_rsv_path = Path(results["rsv_path"])

        self.open_rsv_btn.setEnabled(self.last_rsv_path.exists())

        self.rsv_value.setText(str(sum_rsv))
        self.rows_value.setText(str(results["rows_rsv"]))

        self.set_status("РАСЧЁТ УСПЕШНО ЗАВЕРШЁН", "success")

        warn_line = (
            f"\n\n⚠ Предупреждений в журнале: {self.warning_count} — "
            f"проверьте журнал выполнения." if self.warning_count else ""
        )
        QMessageBox.information(
            self,
            "Расчёт завершён",
            f"Ведомость за {month:02d}.{year} сформирована.\n\n"
            f"RSV: {self.last_rsv_path}\n"
            f"Сумма дней вредности: {sum_rsv}{warn_line}",
        )

    def on_error(self, err_msg: str) -> None:
        self.start_btn.setEnabled(True)
        self.start_btn.setText("Выполнить расчёт и сформировать файлы")
        self.status_lbl.setText("Во время расчёта произошла ошибка")

        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)

        self.set_status("ОШИБКА", "error")
        self.append_log(f"КРИТИЧЕСКАЯ ОШИБКА: {err_msg}")

        QMessageBox.critical(
            self,
            "Ошибка выполнения",
            f"Не удалось выполнить расчёт:\n\n{err_msg}",
        )

    def open_output_folder(self) -> None:
        out_dir = Path(self.out_dir_input.text().strip())

        if out_dir.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_dir.resolve())))
        else:
            QMessageBox.warning(
                self,
                "Внимание",
                "Папка выгрузки ещё не создана.",
            )

    def open_rsv_file(self) -> None:
        if self.last_rsv_path and self.last_rsv_path.exists():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.last_rsv_path.resolve()))
            )


def main() -> None:
    migrate_legacy_data()  # старые настройки рядом с программой -> папка данных (до чтения .env)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    install_excepthook("Расчёт вредных условий труда")

    window = VrednMainWindow()

    # Подбираем стартовый размер под доступную область экрана,
    # чтобы нижняя часть интерфейса не обрезалась при запуске.
    screen = app.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        width = min(1100, max(900, available.width() - 80))
        height = min(760, max(640, available.height() - 80))
        window.resize(width, height)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()