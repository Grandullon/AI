from __future__ import annotations

import time
from pathlib import Path

try:
    from pywinauto import Desktop, keyboard as pwkeyboard
    _HAS_PYWINAUTO = True
except Exception:
    _HAS_PYWINAUTO = False


def _esperar_ventana(title_re: str, timeout_s: float):
    inicio = time.time()
    while time.time() - inicio < timeout_s:
        try:
            win = Desktop(backend="uia").window(title_re=title_re)
            if win.exists() and win.is_visible():
                return win
        except Exception:
            pass
        time.sleep(0.3)
    raise TimeoutError(f"Ventana no apareció: {title_re}")


def handle_save_as(nombre_destino: str, carpeta: str = "", timeout_s: float = 15.0) -> None:
    """Guarda el documento activo de LibreOffice como `nombre_destino` dentro de `carpeta`.

    Pasos:
      1. Pone foco en la ventana de LibreOffice Calc.
      2. Atajo Ctrl+Shift+S para abrir "Guardar como".
      3. Rellena el nombre de archivo y, si procede, la ruta.
      4. Confirma. Si aparece el popup "¿Mantener formato actual?", pulsa "Usar formato xxx".
    """
    if not _HAS_PYWINAUTO:
        raise RuntimeError("pywinauto no disponible (solo Windows)")

    calc = _esperar_ventana(r".*LibreOffice Calc.*", timeout_s)
    calc.set_focus()
    pwkeyboard.send_keys("^+s", pause=0.1)

    dialogo = _esperar_ventana(r"(?i)(Guardar como|Save as)", timeout_s)
    dialogo.set_focus()

    ruta_final = str(Path(carpeta) / nombre_destino) if carpeta else nombre_destino

    try:
        edit = dialogo.child_window(control_type="Edit").wrapper_object()
        edit.set_focus()
        pwkeyboard.send_keys("^a{DEL}", pause=0.05)
        pwkeyboard.send_keys(ruta_final, with_spaces=True, pause=0.01)
    except Exception:
        pwkeyboard.send_keys(ruta_final, with_spaces=True, pause=0.01)

    pwkeyboard.send_keys("{ENTER}", pause=0.1)

    try:
        confirm = _esperar_ventana(r"(?i)(Mantener formato|Keep current|Use .*Format)", timeout_s=3.0)
        for nombre in ("Usar formato xlsx", "Usar formato actual", "Use xlsx Format!", "Keep Current Format"):
            try:
                btn = confirm.child_window(title_re=f"(?i){nombre}", control_type="Button")
                if btn.exists():
                    btn.click_input()
                    return
            except Exception:
                continue
        pwkeyboard.send_keys("{ENTER}")
    except TimeoutError:
        pass
