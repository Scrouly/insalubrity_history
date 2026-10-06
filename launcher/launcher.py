"""
launcher.py — запускатель программы на компьютере кадровика.

При каждом старте: проверяет сервер; если там новая версия — показывает окно
«Обновление программы» с ходом копирования; затем запускает программу.
Если обновлять нечего, окно не показывается вовсе (или мелькает не дольше долей секунды —
оно появляется только если проверка затянулась).

Запуск для отладки:  python launcher.py --base <папка с server.txt и app/>
"""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import updater

SHOW_DELAY_MS = 700      # окно появляется, только если проверка идёт дольше этого
POLL_MS = 40
TITLE = "Расчёт отпуска за вредность"


def base_dir(argv: list[str]) -> Path:
    if "--base" in argv:
        return Path(argv[argv.index("--base") + 1])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


class Worker(threading.Thread):
    """Проверка и обновление в фоне, чтобы окно не зависало."""

    def __init__(self, base: Path, events: "queue.Queue") -> None:
        super().__init__(daemon=True)
        self.base = base
        self.events = events

    def run(self) -> None:
        base = self.base
        try:
            info = updater.check_update(base)
            if info is None:
                self.events.put(("ready",))
                return
            if updater.is_app_running():
                updater.write_log(base, f"Версия {info.server_version} на сервере, но программа запущена — обновление отложено")
                self.events.put(("ready",))
                return
            updater.write_log(base, f"Обновление {info.local_version} -> {info.server_version}")
            self.events.put(("updating", info))
            updater.apply_update(base, info, lambda done, total, name: self.events.put(("progress", done, total, name)))
            updater.write_log(base, f"Обновлено до {info.server_version}")
            self.events.put(("ready",))
        except updater.UpdateError as exc:
            updater.write_log(base, f"ОШИБКА: {exc}")
            self.events.put(("failed", str(exc)))
        except Exception as exc:  # неожиданная ошибка не должна оставить пользователя без программы
            updater.write_log(base, f"ОШИБКА: {type(exc).__name__}: {exc}")
            self.events.put(("failed", f"{type(exc).__name__}: {exc}"))


class LauncherApp:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.exit_code = 0
        self.shown = False

        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(TITLE)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)   # посреди обновления закрывать нельзя

        frame = ttk.Frame(self.root, padding=18)
        frame.pack(fill="both", expand=True)
        self.title_var = tk.StringVar(value="Запуск программы...")
        self.detail_var = tk.StringVar(value="Проверка обновлений")
        ttk.Label(frame, textvariable=self.title_var, font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.detail_var, font=("Segoe UI", 9)).pack(anchor="w", pady=(4, 10))
        self.bar = ttk.Progressbar(frame, mode="indeterminate", length=380)
        self.bar.pack(fill="x")
        self.percent_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.percent_var, font=("Segoe UI", 9)).pack(anchor="e", pady=(6, 0))

        self.events: "queue.Queue" = queue.Queue()
        Worker(base, self.events).start()
        self.root.after(SHOW_DELAY_MS, self.show)
        self.root.after(POLL_MS, self.poll)

    # --- окно ---------------------------------------------------------------------
    def show(self) -> None:
        if self.shown:
            return
        self.shown = True
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 3
        self.root.geometry(f"+{x}+{y}")
        self.root.deiconify()
        self.root.lift()
        if str(self.bar.cget("mode")) == "indeterminate":
            self.bar.start(12)

    def poll(self) -> None:
        last_progress = None
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    last_progress = event
                elif kind == "updating":
                    self.on_updating(event[1])
                elif kind == "ready":
                    self.finish()
                    return
                elif kind == "failed":
                    self.on_failed(event[1])
                    return
        except queue.Empty:
            pass
        if last_progress is not None:
            self.on_progress(*last_progress[1:])
        self.root.after(POLL_MS, self.poll)

    # --- события --------------------------------------------------------------------
    def on_updating(self, info: updater.UpdateInfo) -> None:
        first = info.local_version is None
        self.title_var.set("Установка программы" if first else "Обновление программы")
        self.detail_var.set(
            f"Версия {info.server_version}" if first
            else f"Текущая версия {info.local_version}, новая {info.server_version}"
        )
        self.bar.stop()
        self.bar.configure(mode="determinate", maximum=100, value=0)
        self.show()

    def on_progress(self, done: int, total: int, name: str) -> None:
        percent = int(done * 100 / total) if total else 100
        self.bar["value"] = percent
        mb = 1024 * 1024
        self.percent_var.set(f"{percent} %   {done / mb:.0f} из {total / mb:.0f} МБ")
        self.root.update_idletasks()

    def finish(self) -> None:
        try:
            updater.launch_app(self.base)
        except updater.UpdateError as exc:
            self.fatal(str(exc))
            return
        except Exception as exc:
            self.fatal(f"{type(exc).__name__}: {exc}")
            return
        self.root.destroy()

    def on_failed(self, message: str) -> None:
        app_exists = (self.base / "app" / updater.APP_EXE).exists()
        if app_exists:
            messagebox.showwarning(
                TITLE,
                f"Обновить программу не удалось:\n{message}\n\nЗапускается текущая версия.",
            )
            self.finish()
        else:
            self.fatal(
                f"Программа не установлена, а скопировать её с сервера не удалось:\n{message}\n\n"
                f"Проверьте доступ к серверу и запустите ярлык ещё раз."
            )

    def fatal(self, message: str) -> None:
        updater.write_log(self.base, f"КРИТИЧЕСКАЯ ОШИБКА: {message}")
        messagebox.showerror(TITLE, message)
        self.exit_code = 1
        self.root.destroy()


def main() -> int:
    app = LauncherApp(base_dir(sys.argv))
    app.root.mainloop()
    return app.exit_code


if __name__ == "__main__":
    sys.exit(main())
