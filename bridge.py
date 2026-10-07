"""Ponte Python <-> JavaScript per il banner.

Una BannerApi vive quanto una domanda: tiene lì parola, livello e opzioni, così
il JavaScript riceve solo ciò che deve mostrare e non può falsare l'esito.
Gli attributi con underscore non vengono esposti da pywebview.
"""

import winfocus
from core import MAX_BOX, check_german, check_italian, de_display, de_extra, it_prompt, mask


class BannerApi:
    def __init__(self, store, on_done):
        self._store = store
        self._on_done = on_done  # chiamata una sola volta con 'answered' | 'skip' | 'snooze'
        self._word, self._direction = store.pick()
        self._level = store.level_for(self._word)
        self._options, self._correct = [], None
        if self._level == "easy":
            self._options, self._correct = store.choices(self._word, self._direction)
        self._hint_used = False
        self._answered = False
        self._finished = False
        self._window = self._anchor = None

    # --- finestra

    def _attach(self, window, anchor):
        """anchor = (destra, basso) in pixel logici: l'angolo dello schermo a cui resta agganciato il banner."""
        self._window, self._anchor = window, anchor

    def activate(self):
        """Dal JS, dopo un clic nel banner: prende la tastiera (vedi winfocus.py)."""
        if self._finished or self._window is None:
            return False
        try:
            return winfocus.activate(self._window)
        except Exception:
            return False

    def fit(self, width, height):
        """Dal JS: adatta la finestra al contenuto e la riporta nell'angolo in basso a destra."""
        if self._finished:
            return True
        if self._window is None:
            return False  # la finestra non è ancora agganciata: il JS riprova
        width, height = int(width), int(height)
        right, bottom = self._anchor
        self._window.resize(width, height)
        self._window.move(int(right - width), int(bottom - height))
        return True

    # --- domanda

    def question(self):
        w = self._word
        it2de = self._direction == "it2de"
        return {
            "direction": self._direction,
            "level": self._level,
            "box": self._store.box(w["id"]),
            "max_box": MAX_BOX,
            "prompt": it_prompt(w) if it2de else None,
            "article": None if it2de else w.get("article"),
            "de": None if it2de else w["de"],
            "ask_article": it2de and bool(w.get("article")),
            "options": self._options,
        }

    def hint(self):
        self._hint_used = True
        w = self._word
        if self._direction == "it2de":
            return (w["article"] + " " if w.get("article") else "") + mask(w["de"])
        return mask(w["it"][0])

    # --- risposte

    def choose(self, index):
        if self._answered or not 0 <= index < len(self._options):
            return None
        return self._finish("ok" if self._options[index] == self._correct else "wrong", "", self._options[index])

    def submit(self, given):
        given = (given or "").strip()
        if self._answered or not given:
            return None
        if self._direction == "it2de":
            result, message = check_german(given, self._store.german_targets(self._word))
        else:
            result, message = check_italian(given, self._word)
        return self._finish(result, message, given)

    def give_up(self):
        if self._answered:
            return None
        return self._finish("wrong", "", "")

    def _finish(self, result, message, given):
        self._answered = True
        w = self._word
        self._store.record(w["id"], result, self._hint_used)
        good = result in ("ok", "typo")
        return {
            "result": result,
            "good": good,
            "message": message,
            "given": given,
            "hint_used": self._hint_used,
            "article": w.get("article"),
            "de": w["de"],
            "extra": de_extra(w),
            "it": w["it"][:3],
            "tip": w.get("tip", ""),
            "box": self._store.box(w["id"]),
            "max_box": MAX_BOX,
            "say": de_display(w),
        }

    # --- chiusura

    def dismiss(self, reason):
        """Dal JS: 'answered' (Ok o tempo scaduto), 'skip' o 'snooze'."""
        if self._finished:
            return
        self._finished = True
        if self._answered:
            reason = "answered"
        self._on_done(reason if reason in ("skip", "snooze") else "answered")
