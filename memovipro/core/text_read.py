"""Lectura de texto de controles (la "escalera" estilo UiPath, sin GDI).

Escalón 1 (principal): el ÁRBOL de accesibilidad (UIA) — el mismo que usan
los selectores. Cada control expone su texto en Name / Value / y en sus
descendientes de tipo Text. Es instantáneo y exacto (no es OCR).

Escalón 2 (respaldo): OCR del rectángulo del control (Tesseract), para
cuando el árbol no expone texto (controles pintados como imagen, etc.).
Esa parte la orquesta el Player (necesita capturar pantalla); aquí vive
solo la lectura del árbol y la comparación de texto.
"""
from __future__ import annotations


def normalizar(texto: str) -> str:
    """Colapsa espacios/saltos de línea múltiples en espacios simples."""
    return " ".join((texto or "").split())


def extraer_texto_de_control(ctrl, incluir_descendientes: bool = True) -> str:
    """Lee el texto de un control pywinauto vía el árbol UIA.

    Combina, sin duplicar y preservando el orden:
      - window_text() (propiedad Name)
      - el valor del patrón Value (get_value / legacy Value)
      - el texto de los descendientes de tipo Text (etiquetas internas)

    Devuelve "" si no se pudo leer nada (el caller decidirá si cae a OCR).
    Blindado: cualquier fallo puntual de una fuente no rompe el resto.
    """
    partes: list[str] = []

    # 1. Name (window_text)
    try:
        t = (ctrl.window_text() or "").strip()
        if t:
            partes.append(t)
    except Exception:
        pass

    # 2. Value pattern (dos vías según versión de pywinauto)
    try:
        v = ctrl.get_value()
        if v:
            partes.append(str(v).strip())
    except Exception:
        pass
    try:
        lp = ctrl.legacy_properties() or {}
        v = lp.get("Value")
        if v:
            partes.append(str(v).strip())
    except Exception:
        pass

    # 3. Descendientes de tipo Text (etiquetas dentro del control)
    if incluir_descendientes:
        try:
            for d in ctrl.descendants(control_type="Text"):
                try:
                    t = (d.window_text() or "").strip()
                    if t:
                        partes.append(t)
                except Exception:
                    continue
        except Exception:
            pass

    # Dedup preservando orden.
    vistos: set[str] = set()
    out: list[str] = []
    for p in partes:
        p = p.strip()
        if p and p not in vistos:
            vistos.add(p)
            out.append(p)
    return normalizar(" ".join(out))


def texto_contiene(texto: str, buscado: str) -> bool:
    """¿`texto` contiene `buscado`? Comparación laxa: sin distinguir
    mayúsculas/minúsculas ni acentos (reutiliza la normalización del OCR
    para que 'Guardado' case con 'guardado' y 'Información' con
    'informacion')."""
    if not buscado:
        return True
    try:
        from .ocr import _norm_para_match
        return _norm_para_match(buscado) in _norm_para_match(texto)
    except Exception:
        return buscado.lower() in (texto or "").lower()
