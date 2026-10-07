"""Focus del banner su Windows.

Il banner nasce con WS_EX_NOACTIVATE (webview focus=False): così, quando compare, non ti ruba la tastiera
mentre scrivi in un altro programma. Lo stesso stile impedisce però al clic di attivarlo, e i tasti
continuano ad andare all'altra app. activate() lo toglie e porta il banner in primo piano: va chiamata
solo in risposta a un clic dell'utente (Windows lo permette solo a chi ha appena ricevuto input).
"""

import ctypes

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000

_user32 = ctypes.windll.user32
_user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
_user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
_user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_user32.GetForegroundWindow.restype = ctypes.c_void_p


def hwnd_of(window):
    return int(window.native.Handle.ToInt64())


def activate(window):
    """Rende il banner attivabile e lo porta in primo piano. True se ora ha la tastiera."""
    hwnd = hwnd_of(window)
    style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if style & WS_EX_NOACTIVATE:
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_NOACTIVATE)
    _user32.SetForegroundWindow(hwnd)
    return _user32.GetForegroundWindow() == hwnd
