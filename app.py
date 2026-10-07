"""Vokabel-Pop: banner di vocaboli tedeschi, interfaccia HTML/CSS con pywebview.

Uso:
    pythonw app.py              avvia l'app (finestra di controllo + banner al timer)
    pythonw app.py --minimized  parte ridotta a icona (avvio di Windows)
    python  app.py --now        fa comparire subito una domanda
"""

import ctypes
import os
import socket
import sys
import threading
import time
import traceback

import webview

from bridge import BannerApi
from core import DATA_DIR, Store

BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
# le pagine stanno in ui/; se tutti i file sono nella stessa cartella (repository piatto) si usa quella
UI = BASE if os.path.exists(os.path.join(BASE, "control.html")) else os.path.join(BASE, "ui")
LOG_FILE = os.path.join(DATA_DIR, "error.log")

PORT = int(os.environ.get("VOKABEL_PORT", 47613))  # una sola istanza alla volta
SNOOZE_SEC = 120
BANNER_W, BANNER_H, MARGIN = 400, 300, 16


def log_error():
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + traceback.format_exc() + "\n")


def work_area_logical():
    """Area dello schermo senza barra delle applicazioni, in pixel logici (come li vuole pywebview)."""
    from ctypes import wintypes
    r = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
    try:
        scale = ctypes.windll.user32.GetDpiForSystem() / 96
    except Exception:
        scale = 1
    return r.right / scale, r.bottom / scale


class ControlApi:
    """Metodi chiamabili dalla finestra di controllo (ui/control.js)."""

    def __init__(self, app):
        self._app = app

    def status(self):
        a = self._app
        s = a.store
        today = s.today()
        if a.paused:
            state = "paused"
        elif a.banner is not None:
            state = "asking"
        else:
            state = "waiting"
        return {
            "state": state,
            "seconds_left": max(0, int(a.next_at - time.time())),
            "interval": s.settings["interval_min"],
            "level_mode": s.settings["level_mode"],
            "scope": s.scope_info(),
            "summary": s.summary(),
            "today": {"right": today[0], "seen": today[1]},
        }

    def words(self):
        return self._app.store.word_list()

    def categories(self):
        from core import CUSTOM_CATEGORY
        return {"list": self._app.store.categories(), "default": CUSTOM_CATEGORY}

    def add_word(self, entry):
        return self._app.store.add_word(entry)

    def remove_word(self, wid):
        return self._app.store.remove_word(wid)

    def restore_word(self, wid):
        return self._app.store.restore_word(wid)

    def ask_now(self):
        self._app.show_banner()

    def toggle_pause(self):
        a = self._app
        a.paused = not a.paused
        if not a.paused:
            a.next_at = time.time() + a.interval()
        return a.paused

    def set_interval(self, minutes):
        a = self._app
        minutes = max(1, min(240, int(minutes)))
        a.store.settings["interval_min"] = minutes
        a.store.save()
        a.next_at = time.time() + minutes * 60

    def set_scope(self, names):
        s = self._app.store
        s.set_scope(names)
        return s.scope_info()

    def set_level(self, mode):
        if mode in ("auto", "easy", "hard"):
            self._app.store.settings["level_mode"] = mode
            self._app.store.save()

    def reset(self):
        self._app.store.reset()

    def quit(self):
        self._app.quit()


class App:
    def __init__(self, ask_now=False, minimized=False):
        self.store = Store()
        self.paused = False
        self.quitting = False
        self.banner = None  # finestra del banner attivo, se c'è
        self.lock = threading.Lock()
        self.next_at = time.time() + (2 if ask_now else self.interval())

        self.control = webview.create_window(
            "Vokabel-Pop",
            url=os.path.join(UI, "control.html"),
            js_api=ControlApi(self),
            width=640, height=650, min_size=(560, 520),
            background_color="#faf7f1",
            minimized=minimized,
        )
        self.control.events.closing += self._on_control_closing

    def interval(self):
        return self.store.settings["interval_min"] * 60

    # --- finestra di controllo

    def _on_control_closing(self):
        """La X riduce a icona; si esce davvero solo con «Esci»."""
        if self.quitting:
            return True
        self.control.minimize()
        return False

    def show_control(self):
        self.control.restore()
        self.control.show()

    def quit(self):
        self.quitting = True
        for w in list(webview.windows):
            threading.Thread(target=w.destroy, daemon=True).start()

    # --- banner

    def show_banner(self):
        with self.lock:
            if self.banner is not None:
                return
            api = BannerApi(self.store, self._banner_done)
            right, bottom = work_area_logical()
            self.banner = webview.create_window(
                "Vokabel-Pop banner",
                url=os.path.join(UI, "banner.html"),
                js_api=api,
                width=BANNER_W, height=BANNER_H,
                x=int(right - BANNER_W - MARGIN), y=int(bottom - BANNER_H - MARGIN),
                frameless=True, easy_drag=False, resizable=False,
                on_top=True, focus=False,
                background_color="#faf7f1",
            )
            api._attach(self.banner, (right - MARGIN, bottom - MARGIN))

    def _banner_done(self, reason):
        win = self.banner
        self.banner = None
        self.next_at = time.time() + (SNOOZE_SEC if reason == "snooze" else self.interval())
        if win is not None:
            # dopo un attimo: pywebview deve prima restituire al JS il valore della chiamata dismiss()
            threading.Timer(0.4, win.destroy).start()

    # --- timer e messaggi dalle altre istanze

    def background(self, server):
        threading.Thread(target=self._listen, args=(server,), daemon=True).start()
        while not self.quitting:
            time.sleep(1)
            if not self.paused and self.banner is None and time.time() >= self.next_at:
                try:
                    self.show_banner()
                except Exception:
                    log_error()
                    self.next_at = time.time() + 60

    def _listen(self, server):
        while True:
            try:
                conn, _ = server.accept()
                with conn:
                    msg = conn.recv(16).decode(errors="ignore")
                self.show_banner() if msg == "now" else self.show_control()
            except OSError:
                return
            except Exception:
                log_error()


def acquire_instance(message):
    """Socket di blocco se siamo la prima istanza; altrimenti avvisa quella già aperta."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", PORT))
        s.listen(2)
        return s
    except OSError:
        s.close()
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1) as c:
                c.sendall(message.encode())
        except OSError:
            pass
        return None


def main():
    args = sys.argv[1:]
    ask_now = "--now" in args
    server = acquire_instance("now" if ask_now else "show")
    if server is None:
        return
    app = App(ask_now=ask_now, minimized="--minimized" in args)
    webview.start(app.background, server)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_error()
        raise
