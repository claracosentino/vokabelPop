"""Logica di Vokabel-Pop (nessuna grafica): vocaboli, controllo risposte, progressi."""

import datetime
import json
import os
import random
import re
import sys
import threading
import time
import unicodedata
import uuid

BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))  # da .exe: cartella temporanea
# da .exe i dati dell'utente vanno in %APPDATA%: la cartella temporanea sparisce alla chiusura
DATA_DIR = os.path.join(os.environ.get("APPDATA", BASE), "Vokabel-Pop") if getattr(sys, "frozen", False) else BASE
os.makedirs(DATA_DIR, exist_ok=True)
VOCAB_FILE = os.path.join(BASE, "vocab.json")
PROGRESS_FILE = os.environ.get("VOKABEL_PROGRESS") or os.path.join(DATA_DIR, "progress.json")
# parole aggiunte o rimosse dall'utente: file a parte, così vocab.json resta intatto e «Azzera progressi» non le tocca
MY_WORDS_FILE = os.environ.get("VOKABEL_MYWORDS") or os.path.join(os.path.dirname(PROGRESS_FILE), "my_words.json")
MIN_WORDS = 4  # sotto questa soglia la scelta multipla non ha abbastanza opzioni
CUSTOM_CATEGORY = "Le mie parole"

DEFAULT_SETTINGS = {"interval_min": 10, "level_mode": "auto", "categories": []}  # categories vuota = tutte le sezioni
MAX_BOX = 4  # scatole Leitner 0..4
EASY_MAX_BOX = 1  # scatole 0-1 = scelta multipla, 2+ = risposta scritta
BOX_WEIGHTS = [8, 5, 3, 2, 1]  # le parole meno sapute escono più spesso
RECENT_AVOID = 4
ARTICLES = ("der", "die", "das")


# ---------------------------------------------------------------- testo

def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize_de(s):
    s = s.strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = strip_accents(s)
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


_IT_ARTICLE = re.compile(r"^(il|lo|la|i|gli|le|un|uno|una)\s+|^(l|un|dell|all)'\s*")


def normalize_it(s):
    s = strip_accents(s.strip().lower())
    s = s.replace("’", "'")
    s = _IT_ARTICLE.sub("", s)
    s = re.sub(r"[^\w\s']", " ", s)
    return " ".join(s.split())


def levenshtein(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def match(given, target):
    """'ok' se uguali, 'typo' se differiscono di una lettera (parole lunghe), altrimenti None."""
    if not given:
        return None
    if given == target:
        return "ok"
    if len(target) >= 5 and levenshtein(given, target) <= 1:
        return "typo"
    return None


RANK = {"ok": 3, "typo": 2, "wrong": 0}


def check_german(answer, targets):
    """Controlla una risposta tedesca. targets = vocaboli accettati (sinonimi inclusi).
    Restituisce (esito, messaggio) con esito in 'ok' | 'typo' | 'wrong'."""
    tokens = normalize_de(answer).split()
    art = tokens[0] if tokens and tokens[0] in ARTICLES else None
    word = " ".join(tokens[1:] if art else tokens)
    best = ("wrong", "")
    for e in targets:
        m = match(word, normalize_de(e["de"]))
        if not m:
            continue
        need = e.get("article")
        if need and art is None:
            cand = ("wrong", f"Manca l'articolo! È «{need} {e['de']}».")
        elif need and art != need:
            cand = ("wrong", f"Articolo sbagliato: è «{need}», non «{art}».")
        else:
            cand = (m, "")
        if RANK[cand[0]] > RANK[best[0]] or (cand[0] == "wrong" and not best[1]):
            best = cand
    return best


def check_italian(answer, entry):
    parts = [normalize_it(p) for p in re.split(r"[,/;]| oppure | o ", answer)]
    parts = [p for p in parts if p]
    accepted = [normalize_it(t) for t in entry["it"]]
    is_adj = entry.get("category") == "Aggettivi"
    best = "wrong"
    for p in parts:
        for t in accepted:
            m = match(p, t)
            # per gli aggettivi va bene anche alta/alti/alte
            if not m and is_adj and len(p) > 3 and p[:-1] == t[:-1] and p[-1] in "aeio":
                m = "ok"
            if m and RANK[m] > RANK[best]:
                best = m
    return best, ""


# ---------------------------------------------------------------- vocaboli

def de_display(e):
    return f"{e['article']} {e['de']}" if e.get("article") else e["de"]


def de_extra(e):
    if e.get("plural"):
        return f"Pl. die {e['plural']}"
    if e.get("no_plural"):
        return "senza plurale"
    return e.get("extra", "")


def it_prompt(e):
    return e.get("prompt_it") or e["it"][0]


def prompt_in(a, b):
    """True se la parola italiana mostrata per a è anche una traduzione di b (sinonimi)."""
    accepted = {normalize_it(t) for t in b["it"]}
    return any(normalize_it(p) in accepted for p in it_prompt(a).split(","))


def mask(word):
    return " ".join(w[0] + "_" * (len(w) - 1) for w in word.split())


def _valid_entry(w):
    return (isinstance(w, dict)
            and all(isinstance(w.get(k), str) and w[k] for k in ("id", "de", "category"))
            and isinstance(w.get("it"), list) and bool(w["it"]))


class Store:
    def __init__(self):
        self._io = threading.RLock()
        with open(VOCAB_FILE, encoding="utf-8") as f:
            self.base = json.load(f)["words"]
        self.mine = self._load_mine()
        self._rebuild()
        self.data = {"settings": dict(DEFAULT_SETTINGS), "words": {}, "history": {}, "last_dir": "de2it"}
        if os.path.exists(PROGRESS_FILE):
            try:
                with open(PROGRESS_FILE, encoding="utf-8") as f:
                    saved = json.load(f)
                for k in self.data:
                    if k in saved:
                        self.data[k] = saved[k]
                self.data["settings"] = {**DEFAULT_SETTINGS, **self.data["settings"]}
            except (OSError, ValueError):
                pass  # file rovinato: si riparte da zero
        self.recent = []

    @property
    def settings(self):
        return self.data["settings"]

    def save(self):
        with self._io:  # le chiamate dalla finestra arrivano su thread diversi: una scrittura alla volta
            tmp = PROGRESS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, PROGRESS_FILE)

    # --- elenco parole: quelle di vocab.json + le tue, meno quelle rimosse

    def _load_mine(self):
        mine = {"added": [], "removed": []}
        if os.path.exists(MY_WORDS_FILE):
            try:
                with open(MY_WORDS_FILE, encoding="utf-8") as f:
                    saved = json.load(f)
                mine["added"] = [w for w in saved.get("added", []) if _valid_entry(w)]
                mine["removed"] = [i for i in saved.get("removed", []) if isinstance(i, str)]
            except (OSError, ValueError, AttributeError):
                try:
                    os.replace(MY_WORDS_FILE, MY_WORDS_FILE + ".bad")  # file rovinato: tienilo da parte
                except OSError:
                    pass
        return mine

    def _save_mine(self):
        with self._io:
            tmp = MY_WORDS_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.mine, f, ensure_ascii=False, indent=1)
            os.replace(tmp, MY_WORDS_FILE)

    def _rebuild(self):
        removed = set(self.mine["removed"])
        all_words = self.base + self.mine["added"]
        self.by_id = {w["id"]: w for w in all_words}
        self.all_words = all_words
        self.words = [w for w in all_words if w["id"] not in removed]  # quelle usate nelle domande

    def categories(self):
        """Categorie presenti nell'elenco, nell'ordine in cui compaiono; «Le mie parole» c'è sempre."""
        cats = list(dict.fromkeys(w["category"] for w in self.all_words))
        if CUSTOM_CATEGORY not in cats:
            cats.append(CUSTOM_CATEGORY)
        return cats

    def _canonical_category(self, name):
        """«aggettivi» e «Aggettivi » sono la stessa categoria: riusa il nome già esistente."""
        key = lambda s: strip_accents(" ".join(s.lower().split()))
        for c in self.categories():
            if key(c) == key(name):
                return c
        return " ".join(name.split())

    def add_word(self, raw):
        """Aggiunge una parola tua. Restituisce {'ok': True, 'id', 'label'} o {'ok': False, 'error', 'field'}."""
        raw = raw or {}
        text = lambda k, n: str(raw.get(k) or "").strip()[:n]
        de, article, plural = text("de", 60), text("article", 3).lower() or None, text("plural", 60) or None
        tip, category = text("tip", 400), text("category", 40) or CUSTOM_CATEGORY
        it = [t.strip()[:60] for t in re.split(r"[,;]", str(raw.get("it") or "")) if t.strip()][:6]
        if not de:
            return {"ok": False, "field": "de", "error": "Scrivi la parola in tedesco."}
        if article and article not in ARTICLES:
            return {"ok": False, "field": "de", "error": "L’articolo deve essere der, die o das."}
        if not it:
            return {"ok": False, "field": "it", "error": "Scrivi almeno una traduzione in italiano."}
        entry = {"id": "u" + uuid.uuid4().hex[:8], "category": self._canonical_category(category), "de": de,
                 "article": article, "plural": plural, "it": it}
        if tip:
            entry["tip"] = tip
        removed = set(self.mine["removed"])
        for w in self.all_words:
            if normalize_de(w["de"]) == normalize_de(de) and w.get("article") == article:
                msg = (f"«{de_display(w)}» c’è già, ma l’hai rimossa: la trovi in «Rimosse»."
                       if w["id"] in removed else f"«{de_display(w)}» c’è già nell’elenco.")
                return {"ok": False, "field": "de", "error": msg}
        self.mine["added"].append(entry)
        self._save_mine()
        self._rebuild()
        return {"ok": True, "id": entry["id"], "label": de_display(entry), "category": entry["category"]}

    def remove_word(self, wid):
        """Toglie una parola dalle domande (reversibile con restore_word)."""
        w = next((x for x in self.words if x["id"] == wid), None)
        if w is None:
            return {"ok": False, "error": "Parola non trovata."}
        if len(self.words) <= MIN_WORDS:
            return {"ok": False, "error": f"Servono almeno {MIN_WORDS} parole per fare le domande."}
        self.mine["removed"].append(wid)
        self._save_mine()
        self._rebuild()
        return {"ok": True, "label": de_display(w)}

    def restore_word(self, wid):
        if wid not in self.mine["removed"]:
            return {"ok": False, "error": "Parola non trovata."}
        self.mine["removed"].remove(wid)
        self._save_mine()
        self._rebuild()
        return {"ok": True, "label": de_display(self.by_id[wid])}

    def stat(self, wid):
        return self.data["words"].setdefault(wid, {"box": 0, "seen": 0, "right": 0, "wrong": 0, "last": 0})

    def box(self, wid):
        return self.data["words"].get(wid, {}).get("box", 0)

    def box_counts(self):
        counts = [0] * (MAX_BOX + 1)
        for w in self.words:
            counts[self.box(w["id"])] += 1
        return counts

    def today(self):
        return self.data["history"].get(datetime.date.today().isoformat(), [0, 0])

    def status(self, wid):
        """'new' (mai vista), 'weak' (da ripassare), 'almost' (quasi), 'learned' (imparata)."""
        s = self.data["words"].get(wid)
        if not s or not s.get("seen"):
            return "new"
        return "learned" if s["box"] >= MAX_BOX else "almost" if s["box"] >= 2 else "weak"

    def word_list(self):
        """Tutte le parole (anche le rimosse) con il loro stato, per la scheda «Parole»."""
        removed = set(self.mine["removed"])
        mine = {w["id"] for w in self.mine["added"]}
        order = {}
        for w in self.all_words:
            order.setdefault(w["category"], len(order))  # gruppi nell'ordine in cui compaiono
        out = []
        for w in sorted(self.all_words, key=lambda w: order[w["category"]]):
            s = self.data["words"].get(w["id"], {})
            out.append({
                "id": w["id"], "category": w["category"],
                "article": w.get("article"), "de": w["de"], "extra": de_extra(w),
                "it": w["it"][:3], "tip": w.get("tip", ""),
                "status": self.status(w["id"]),
                "right": s.get("right", 0), "wrong": s.get("wrong", 0),
                "custom": w["id"] in mine, "removed": w["id"] in removed,
            })
        return out

    def summary(self):
        """Riepilogo per la scheda «Progressi»: gruppi di parole, più difficili, serie di giorni."""
        groups = {"new": 0, "weak": 0, "almost": 0, "learned": 0}
        hard = []
        for w in self.words:
            st = self.status(w["id"])
            groups[st] += 1
            s = self.data["words"].get(w["id"], {})
            if s.get("wrong") and st != "learned":
                hard.append((s["wrong"], s["box"], w))
        hard.sort(key=lambda t: (-t[0], t[1]))
        return {
            "total": len(self.words),
            "groups": groups,
            "hardest": [{"label": de_display(w), "it": it_prompt(w), "wrong": n} for n, _, w in hard[:5]],
            "streak": self.streak(),
        }

    def streak(self):
        """Giorni consecutivi con almeno una risposta (oggi conta solo se hai già risposto)."""
        h = self.data["history"]
        day = datetime.date.today()
        if not h.get(day.isoformat(), [0, 0])[1]:
            day -= datetime.timedelta(days=1)
        n = 0
        while h.get(day.isoformat(), [0, 0])[1]:
            n += 1
            day -= datetime.timedelta(days=1)
        return n

    # --- sezioni da cui escono le domande

    def quiz_words(self):
        """Parole da cui pescare le domande: quelle delle sezioni scelte (o tutte). Mai vuoto."""
        cats = set(self.settings.get("categories") or [])
        pool = [w for w in self.words if w["category"] in cats] if cats else self.words
        return pool or self.words

    def scope_info(self):
        """Sezioni con quante parole attive hanno e quali sono scelte, per la scheda Studio."""
        counts = {}
        for w in self.all_words:
            counts.setdefault(w["category"], 0)
        for w in self.words:
            counts[w["category"]] += 1
        selected = [c for c in (self.settings.get("categories") or []) if c in counts]
        active = sum(counts[c] for c in selected) if selected else len(self.words)
        return {
            "categories": [{"name": c, "count": n} for c, n in counts.items() if n or c in selected],
            "selected": selected,
            "words": active,
            "fallback": bool(selected) and active == 0,  # le sezioni scelte non hanno più parole: si usa tutto
        }

    def set_scope(self, names):
        """Sceglie le sezioni (lista vuota = tutte). Se le scegli tutte, equivale a «tutte»."""
        valid = {w["category"] for w in self.words}
        chosen = [c for c in dict.fromkeys(names or []) if isinstance(c, str) and c in valid]
        self.settings["categories"] = [] if set(chosen) >= valid else chosen
        self.save()

    def pick(self):
        quiz = self.quiz_words()
        pool = [w for w in quiz if w["id"] not in self.recent] or quiz
        weights = [BOX_WEIGHTS[self.box(w["id"])] for w in pool]
        w = random.choices(pool, weights)[0]
        self.recent = (self.recent + [w["id"]])[-RECENT_AVOID:]
        direction = "it2de" if self.data["last_dir"] == "de2it" else "de2it"
        self.data["last_dir"] = direction
        return w, direction

    def level_for(self, w):
        mode = self.settings["level_mode"]
        if mode == "easy":
            return "easy"
        if mode == "hard":
            return "hard"
        return "easy" if self.box(w["id"]) <= EASY_MAX_BOX else "hard"

    def german_targets(self, w):
        """Tutti i vocaboli accettati come risposta tedesca (es. Quatsch/Schwachsinn)."""
        return [w] + [x for x in self.words if x is not w and prompt_in(w, x)]

    def choices(self, w, direction):
        others = [x for x in self.words if x is not w]
        random.shuffle(others)
        others.sort(key=lambda x: x["category"] != w["category"])  # prima la stessa categoria
        if direction == "it2de":
            correct = de_display(w)
            banned = {de_display(x) for x in self.german_targets(w)}
            opts = []
            if w.get("article"):
                wrong_arts = [a for a in ARTICLES if a != w["article"]]
                if w.get("plural") == w["de"] and "die" in wrong_arts:
                    wrong_arts.remove("die")  # 'die Hügel' sarebbe il plurale: troppo ambiguo
                opts.append(f"{random.choice(wrong_arts)} {w['de']}")
            cands = [de_display(x) for x in others]
        else:
            correct = it_prompt(w)
            banned = {it_prompt(o) for o in others if prompt_in(o, w) or prompt_in(w, o)}
            opts = []
            cands = [it_prompt(x) for x in others]
        for c in cands:
            if len(opts) >= 3:
                break
            if c != correct and c not in banned and c not in opts:
                opts.append(c)
        opts.append(correct)
        random.shuffle(opts)
        return opts, correct

    def record(self, wid, result, hint_used):
        s = self.stat(wid)
        s["seen"] += 1
        s["last"] = int(time.time())
        good = result in ("ok", "typo")
        if good:
            s["right"] += 1
            if not hint_used:
                s["box"] = min(MAX_BOX, s["box"] + 1)
        else:
            s["wrong"] += 1
            s["box"] = 0
        day = self.data["history"].setdefault(datetime.date.today().isoformat(), [0, 0])
        day[0] += int(good)
        day[1] += 1
        self.save()

    def reset(self):
        self.data["words"] = {}
        self.data["history"] = {}
        self.save()
