[1mdiff --git a/insalubrity_history.py b/insalubrity_history.py[m
[1mindex 66b53b4..30ef920 100644[m
[1m--- a/insalubrity_history.py[m
[1m+++ b/insalubrity_history.py[m
[36m@@ -139,7 +139,7 @@[m [mclass CompactCellDelegate(QStyledItemDelegate):[m
 class HistoryWindow(QMainWindow):[m
     def __init__(self):[m
         super().__init__()[m
[31m-        self.setWindowTitle("История по вредности")[m
[32m+[m[32m        self.setWindowTitle("Расчёт отпуска за вредность")[m
         self.setStyleSheet(STYLESHEET)[m
 [m
         self.env_data = load_env_vars()[m
[36m@@ -209,7 +209,7 @@[m [mclass HistoryWindow(QMainWindow):[m
         header_row = QHBoxLayout()[m
         title_col = QVBoxLayout()[m
         title_col.setSpacing(2)[m
[31m-        title = QLabel("История по вредности")[m
[32m+[m[32m        title = QLabel("Расчёт отпуска за вредность")[m
         title.setObjectName("AppTitle")[m
         title.setToolTip("Поиск сотрудника по ФИО, помесячная и годовая статистика по RSV")[m
         title_col.addWidget(title)[m
[36m@@ -1299,7 +1299,7 @@[m [mdef main() -> None:[m
     app = QApplication(sys.argv)[m
     app.setStyle("Fusion")[m
     app.setFont(QFont("Segoe UI", 10))[m
[31m-    install_excepthook("История по вредности")[m
[32m+[m[32m    install_excepthook("Расчёт отпуска за вредность")[m
 [m
     window = HistoryWindow()[m
     window.show()[m
