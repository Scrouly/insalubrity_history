"""
conftest.py — тесты не должны трогать настоящие настройки и правки разработчика.

Папка данных (.env, month_overrides.json, ...) на время тестов подменяется временной:
переменная окружения выставляется ДО импорта app_env, поэтому константы путей
(ENV_FILE_PATH, CRASH_LOG_PATH, файлы правок) сразу указывают во временную папку.
"""
import atexit
import os
import shutil
import tempfile

_SESSION_DATA_DIR = tempfile.mkdtemp(prefix="insalubrity_tests_")
os.environ["INSALUBRITY_DATA_DIR"] = _SESSION_DATA_DIR
os.environ["INSALUBRITY_TESTING"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
atexit.register(shutil.rmtree, _SESSION_DATA_DIR, True)
