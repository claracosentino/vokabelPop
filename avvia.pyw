# Doppio clic su questo file per avviare Vokabel-Pop senza finestra nera.
import os
import runpy
import sys

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
runpy.run_path(os.path.join(base, "app.py"), run_name="__main__")
