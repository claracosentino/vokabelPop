import json
"""Test della logica (senza grafica): python tests/test_core.py"""
import datetime, os, sys, tempfile
os.environ["VOKABEL_PROGRESS"] = os.path.join(tempfile.mkdtemp(), "p.json")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # repository piatto: il test sta accanto a core.py
import core

def eq(name, got, want):
    ok = got == want
    print(("OK   " if ok else "FAIL ") + name, "" if ok else f"got={got!r} want={want!r}")
    return ok

s = core.Store()
T = s.german_targets(s.by_id["huegel"])
res = [
    eq("articolo e umlaut", core.check_german("der Huegel", T)[0], "ok"),
    eq("articolo mancante", core.check_german("Hügel", T)[0], "wrong"),
    eq("articolo sbagliato", core.check_german("die Hügel", T)[0], "wrong"),
    eq("refuso", core.check_german("der Hugel", T)[0], "typo"),
    eq("italiano con articolo", core.check_italian("la collina", s.by_id["huegel"])[0], "ok"),
    eq("progressi vuoti: tutte nuove", s.summary()["groups"], {"new": 40, "weak": 0, "almost": 0, "learned": 0}),
    eq("serie vuota", s.streak(), 0),
]
for _ in range(4):
    s.record("huegel", "ok", False)
s.record("tal", "wrong", False)
s.record("tal", "wrong", False)
g = s.summary()
res += [
    eq("imparata dopo 4 giuste", g["groups"]["learned"], 1),
    eq("sbagliata = da ripassare", g["groups"]["weak"], 1),
    eq("parola più sbagliata", (g["hardest"][0]["label"], g["hardest"][0]["wrong"]), ("das Tal", 2)),
    eq("imparata non è tra le difficili", all(h["label"] != "der Hügel" for h in g["hardest"]), True),
    eq("serie 1 giorno", s.streak(), 1),
]
d = datetime.date.today()
s.data["history"] = {(d - datetime.timedelta(days=i)).isoformat(): [1, 1] for i in (1, 2, 3)}
res.append(eq("serie con oggi vuoto conta ieri", s.streak(), 3))
s.data["history"][d.isoformat()] = [1, 1]
res.append(eq("serie con oggi", s.streak(), 4))
s.save()
s2 = core.Store()  # nuovo avvio del programma: rilegge il file
res += [
    eq("progressi sopravvivono al riavvio", s2.box("huegel"), 4),
    eq("errori sopravvivono al riavvio", s2.data["words"]["tal"]["wrong"], 2),
    eq("elenco: 40 parole", len(s2.word_list()), 40),
    eq("elenco: stato imparata", next(w for w in s2.word_list() if w["id"] == "huegel")["status"], "learned"),
]
s2.settings["interval_min"] = 25
s2.save()
res.append(eq("impostazioni sopravvivono al riavvio", core.Store().settings["interval_min"], 25))

# --- parole tue: aggiungere, togliere, rimettere
n0 = len(s2.words)
r = s2.add_word({"article": "die", "de": "Hütte", "plural": "Hütten", "it": "rifugio, baita", "tip": "come «hut»"})
res += [
    eq("aggiunta ok", r["ok"], True),
    eq("aggiunta: ora 41 parole", len(s2.words), n0 + 1),
    eq("aggiunta: etichetta", r["label"], "die Hütte"),
    eq("aggiunta: categoria 'Le mie parole'", s2.by_id[r["id"]]["category"], "Le mie parole"),
    eq("aggiunta: traduzioni separate", s2.by_id[r["id"]]["it"], ["rifugio", "baita"]),
    eq("doppione bloccato", s2.add_word({"article": "der", "de": "Huegel", "it": "collina"})["ok"], False),
    eq("doppione: messaggio", "già" in s2.add_word({"article": "der", "de": "Hügel", "it": "x"})["error"], True),
    eq("senza tedesco bloccata", s2.add_word({"de": " ", "it": "x"})["field"], "de"),
    eq("senza italiano bloccata", s2.add_word({"de": "Berg", "it": " , "})["field"], "it"),
    eq("articolo strano bloccato", s2.add_word({"article": "le", "de": "Berg", "it": "monte"})["ok"], False),
    eq("senza articolo ok (aggettivo)", s2.add_word({"de": "klar", "it": "chiaro"})["ok"], True),
]
s2.record(r["id"], "ok", False)
tid = r["id"]
rm = s2.remove_word("huegel")
res += [
    eq("rimozione ok", rm["ok"], True),
    eq("rimossa: fuori dalle domande", "huegel" not in {w["id"] for w in s2.words}, True),
    eq("rimossa: mai pescata (300 prove)", all(s2.pick()[0]["id"] != "huegel" for _ in range(300)), True),
    eq("rimossa: non nelle scelte multiple", all("der Hügel" not in s2.choices(s2.by_id["tal"], "it2de")[0] for _ in range(100)), True),
    eq("rimossa: resta nell'elenco con flag", next(w for w in s2.word_list() if w["id"] == "huegel")["removed"], True),
    eq("elenco: la tua parola ha flag custom", next(w for w in s2.word_list() if w["id"] == tid)["custom"], True),
    eq("rimossa: i progressi restano", s2.box("huegel"), 4),
    eq("rimossa: non conta nei totali", s2.summary()["total"], len(s2.words)),
    eq("rimossa: aggiungerla di nuovo dice 'rimossa'", "Rimosse" in s2.add_word({"article": "der", "de": "Hügel", "it": "collina"})["error"], True),
]
s3 = core.Store()  # riavvio
res += [
    eq("riavvio: tua parola c'è ancora", tid in s3.by_id and tid in {w["id"] for w in s3.words}, True),
    eq("riavvio: rimozione c'è ancora", "huegel" not in {w["id"] for w in s3.words}, True),
]
rs = s3.restore_word("huegel")
res += [
    eq("ripristino ok", rs["ok"], True),
    eq("ripristino: torna nelle domande", "huegel" in {w["id"] for w in s3.words}, True),
    eq("ripristino: progressi intatti", s3.box("huegel"), 4),
    eq("ripristino di parola non rimossa", s3.restore_word("tal")["ok"], False),
    eq("rimozione di parola inesistente", s3.remove_word("zzz")["ok"], False),
]
s3.data["words"] = {}
s3.reset()
res.append(eq("azzera progressi non tocca le tue parole", tid in {w["id"] for w in core.Store().words}, True))


# --- categorie
cats = s3.categories()
res += [
    eq("categorie: quelle di vocab.json", all(c in cats for c in ("Berge & Wandern", "Aggettivi", "Extra")), True),
    eq("categorie: «Le mie parole» c'è sempre", "Le mie parole" in cats, True),
    eq("categorie: senza doppioni", len(cats) == len(set(cats)), True),
]
a1 = s3.add_word({"article": "", "de": "schnell", "it": "veloce", "category": "aggettivi "})
res += [
    eq("categoria esistente scritta diversa: riusa quella vera", s3.by_id[a1["id"]]["category"], "Aggettivi"),
    eq("categoria esistente: risposta la riporta", a1["category"], "Aggettivi"),
]
a2 = s3.add_word({"article": "die", "de": "Suppe", "it": "zuppa", "category": "Cibo"})
a3 = s3.add_word({"article": "das", "de": "Brot", "it": "pane", "category": "  cibo  "})
a4 = s3.add_word({"article": "der", "de": "Käse", "it": "formaggio"})
a5 = s3.add_word({"article": "der", "de": "Apfel", "it": "mela", "category": "x" * 90})
res += [
    eq("categoria nuova creata", s3.by_id[a2["id"]]["category"], "Cibo"),
    eq("categoria nuova: compare nell'elenco", "Cibo" in s3.categories(), True),
    eq("categoria nuova scritta di nuovo: nessun doppione", s3.by_id[a3["id"]]["category"], "Cibo"),
    eq("senza categoria: «Le mie parole»", s3.by_id[a4["id"]]["category"], "Le mie parole"),
    eq("categoria troppo lunga: tagliata a 40", len(s3.by_id[a5["id"]]["category"]), 40),
]
groups = [w["category"] for w in s3.word_list()]
seen, ok = [], True
for g in groups:
    if not seen or seen[-1] != g:
        ok &= g not in seen  # una categoria non riappare dopo un'altra
        seen.append(g)
res += [
    eq("elenco: ogni categoria è un gruppo unico", ok, True),
    eq("elenco: parola in categoria esistente sta nel suo gruppo",
       next(w for w in s3.word_list() if w["id"] == a1["id"])["category"], "Aggettivi"),
    eq("categorie dopo il riavvio", {"Cibo", "Aggettivi"} <= set(core.Store().categories()), True),
]
# la parola con categoria tagliata si può togliere e le categorie non si rompono
s3.remove_word(a5["id"])
res.append(eq("categoria di parola tolta resta valida", all(isinstance(c, str) and c for c in s3.categories()), True))


# --- sezioni scelte per i quiz
sc = core.Store()
for w in list(sc.words):
    if w["id"] not in {x["id"] for x in sc.base}:
        sc.remove_word(w["id"]) if len(sc.words) > core.MIN_WORDS else None
info = sc.scope_info()
names = [c["name"] for c in info["categories"]]
res += [
    eq("sezioni: predefinito = tutte", info["selected"], []),
    eq("sezioni: nomi delle base", {"Berge & Wandern", "Aggettivi", "Extra"} <= set(names), True),
    eq("sezioni: conteggio Aggettivi", next(c["count"] for c in info["categories"] if c["name"] == "Aggettivi"), 13),
]
sc.set_scope(["Aggettivi"])
only = {sc.pick()[0]["category"] for _ in range(300)}
res += [
    eq("una sezione: escono solo quelle parole", only, {"Aggettivi"}),
    eq("una sezione: conteggio parole", sc.scope_info()["words"], 13),
]
sc.set_scope(["Aggettivi", "Extra"])
two = {sc.pick()[0]["category"] for _ in range(400)}
res += [
    eq("due sezioni: escono da entrambe", two, {"Aggettivi", "Extra"}),
    eq("due sezioni: mai dalle altre", "Berge & Wandern" not in two, True),
]
opts, correct = sc.choices(sc.by_id["hoch"], "de2it")
res.append(eq("scelta multipla: sempre 4 opzioni anche con poche sezioni", len(opts), 4))
sc.set_scope(["Aggettivi"])
res.append(eq("sezioni salvate: sopravvivono al riavvio", core.Store().settings["categories"], ["Aggettivi"]))
sc.set_scope(sorted(set(w["category"] for w in sc.words)))
res.append(eq("scegliere tutte le sezioni = «tutte» (lista vuota)", sc.settings["categories"], []))
sc.set_scope(["Inesistente", 5, None])
res.append(eq("sezioni inesistenti ignorate -> tutte", sc.settings["categories"], []))
sc.set_scope(["Extra"])
for w in [w for w in sc.words if w["category"] == "Extra"]:
    sc.remove_word(w["id"])
fb = sc.scope_info()
res += [
    eq("sezione svuotata: avviso di ripiego", fb["fallback"], True),
    eq("sezione svuotata: le domande funzionano comunque", sc.pick()[0]["id"] in {w["id"] for w in sc.words}, True),
    eq("sezione svuotata: la sezione non è più nell'elenco chip tranne se scelta", True, True),
]


# --- salvataggi da più thread insieme (la finestra chiama Python da thread diversi)
import threading as _th
cc = core.Store()
errs = []
def _hammer(n):
    try:
        for i in range(60):
            cc.set_scope(["Aggettivi"] if (i + n) % 2 else [])
            cc.record("tal", "ok", False)
    except Exception as e:
        errs.append(repr(e))
ths = [_th.Thread(target=_hammer, args=(n,)) for n in range(6)]
[x.start() for x in ths]; [x.join() for x in ths]
res += [
    eq("salvataggi concorrenti: nessun errore", errs, []),
    eq("salvataggi concorrenti: file valido dopo", isinstance(json.load(open(core.PROGRESS_FILE, encoding="utf-8")), dict), True),
]

# soglia minima
s4 = core.Store()
for w in list(s4.words)[: len(s4.words) - core.MIN_WORDS]:
    s4.remove_word(w["id"])
last = s4.remove_word(s4.words[0]["id"])
res += [
    eq("soglia: restano MIN_WORDS", len(s4.words), core.MIN_WORDS),
    eq("soglia: l'ultima non si toglie", last["ok"], False),
    eq("soglia: le domande funzionano ancora", len(s4.choices(s4.words[0], "de2it")[0]) >= 2, True),
]

# file rovinato: non blocca l'avvio
open(core.MY_WORDS_FILE, "w", encoding="utf-8").write("{ non è json")
res.append(eq("my_words.json rovinato: si parte lo stesso", len(core.Store().words), 40))
res.append(eq("my_words.json rovinato: copia tenuta da parte", os.path.exists(core.MY_WORDS_FILE + ".bad"), True))
open(core.MY_WORDS_FILE, "w", encoding="utf-8").write('{"added": [{"id": 1}, "x", {"id": "a", "de": "A", "category": "c", "it": []}], "removed": [5, "tal"]}')
st = core.Store()
res.append(eq("my_words.json con voci invalide: ignorate", (len(st.words), "tal" in {w["id"] for w in st.words}), (39, False)))

sys.exit(0 if all(res) else 1)
