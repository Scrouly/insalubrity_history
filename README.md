# История по вредности

Расчёт отпуска за вредные условия труда (ОАО «Доломит»): калькулятор RSV и окно «История по вредности».
Python 3.8 + PyQt5 (работает на Windows 7).

## Структура

```
src/          код программы (запуск: python src/insalubrity_history.py)
  insalubrity.py            расчёт RSV из DBF
  insalubrity_gui.py        окно калькулятора
  history_reader.py         чтение RSV-файлов, таймлайн, отпуск по классам
  insalubrity_history.py    окно «История по вредности»
  app_env.py                .env, папка данных, атомарная запись, crash.log
  find_zero_kol_rd_months.py  отчёт по сбойным месяцам (kol_rd=0)
  version.py                номер версии (менять перед выпуском)
tests/        тесты:  python -m pytest
packaging/    InsalubrityHistory.spec, Launcher.spec (PyInstaller) и иконка
scripts/      build.bat (тесты + сборка программы и запускателя), publish.bat (выпуск на сервер)
launcher/     запускатель для ПК кадровиков (окно обновления + запуск программы)
deploy/       install.bat — установка запускателя на ПК кадровика
docs/         DEPLOY.md — как раздавать и обновлять
requirements-win7.txt
```

Не в git (см. `.gitignore`): `.env`, `dbf/`, `rsv/`, файлы ручных правок, `backups/`, `dist/`, `build/`, `venv/`.

## Быстрый старт

```
py -3.8 -m venv venv
venv\Scripts\activate
pip install -r requirements-win7.txt
python -m pytest
python src\insalubrity_history.py
```

В PyCharm: папку `src` пометить как *Sources Root* (ПКМ -> Mark Directory as), `tests` — *Test Sources Root*.

## Выпуск обновления

1. Поднять номер в `src/version.py`.
2. `scripts\build.bat`
3. `scripts\publish.bat` (путь к серверу — в `publish_target.txt` в корне)

Подробнее: `docs/DEPLOY.md`.
