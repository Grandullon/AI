"""Grabador de macros.

Diseño en dos fases para no bloquear la GUI:

1) **Captura cruda (rápida)** — los listeners de `pynput` solo almacenan
   coordenadas y teclas. No se llama a pywinauto durante la grabación.
   Esto hace que:
   - El usuario no note retardo entre clics.
   - `stop()` retorne casi al instante (no espera resolución de selectores).

2) **Resolución de selectores (lenta)** — una vez detenida la grabación,
   `Recorder.construir_macro(eventos, resolver_selectores=True)` recorre
   los clics e intenta resolver cada uno a `click_control` con selector
   simbólico vía pywinauto UI Automation. Esto debe ejecutarse en un
   QThread aparte (lo hace `RecordDialog`).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

try:
    from pynput import keyboard, mouse
    _HAS_PYNPUT = True
except Exception:
    _HAS_PYNPUT = False

try:
    from pywinauto import Desktop
    _HAS_PYWINAUTO = True
except Exception:
    _HAS_PYWINAUTO = False

try:
    from loguru import logger
except Exception:
    class _NullLogger:
        def debug(self, *a, **kw): pass
        def info(self, *a, **kw): pass
        def warning(self, *a, **kw): pass
        def exception(self, *a, **kw): pass
    logger = _NullLogger()

from .keyboard_utils import escape_send_keys
from .step_model import Macro, Selector, Step, StepType


# Teclas que no deben aparecer en la macro grabada (controles del propio recorder).
TECLAS_IGNORADAS = {"f9"}

# Detección de doble clic: dos clics del mismo botón en la misma posición
# (con tolerancia DOUBLE_CLICK_RADIUS_PX) dentro de DOUBLE_CLICK_THRESHOLD_S
# se fusionan en un único evento marcado como `double=True`.
def _umbral_doble_clic_s() -> float:
    """Tiempo de doble clic configurado en Windows, en segundos.

    Usar el del sistema y no un número inventado importa: es el mismo que
    aplica la aplicación que se está grabando, así que lo que nosotros
    fusionamos en un doble clic es exactamente lo que ella va a
    interpretar como tal. Fuera de Windows, medio segundo (el valor por
    defecto de Windows)."""
    try:
        import ctypes
        ms = int(ctypes.windll.user32.GetDoubleClickTime())
        if 100 <= ms <= 5000:
            return ms / 1000.0
    except Exception:
        pass
    return 0.5


DOUBLE_CLICK_THRESHOLD_S = _umbral_doble_clic_s()
DOUBLE_CLICK_RADIUS_PX = 8


@dataclass
class _BufferTexto:
    texto: str = ""
    ultimo_ts: float = 0.0
    primer_ts: float = 0.0  # timestamp del PRIMER carácter (para el delay del paso)


@dataclass
class EventoCrudo:
    tipo: str  # 'click' | 'type_text' | 'send_keys' | 'scroll' | 'drag'
    x: int = 0
    y: int = 0
    x2: int = 0  # destino del drag
    y2: int = 0
    dx: int = 0  # desplazamiento de rueda horizontal
    dy: int = 0  # desplazamiento de rueda vertical (positivo = arriba)
    button: str = "left"  # 'left' | 'right' | 'middle'
    double: bool = False
    modifiers: str = ""  # ej. "ctrl" | "ctrl+shift" | "" (sin modificadores)
    valor: str = ""
    descripcion: str = ""
    timestamp: float = 0.0
    img_png: bytes | None = None  # thumbnail PNG alrededor del clic (matching)
    # Sobre que rellena el hilo de miniaturas. La captura NO puede hacerse
    # dentro del enganche del ratón (ver _arrancar_miniaturas), así que el
    # evento se crea con el sobre vacío y se lee al construir la macro.
    img_holder: dict | None = None
    # Selector/ancla resueltos EN EL MOMENTO del clic por el hilo
    # resolutor. Si está a None, `construir_macro` los resuelve al final
    # (peor: la pantalla ya ha cambiado).
    resuelto: tuple | None = None


# Distancia mínima en píxeles para considerar que un press+release es un drag,
# no un click. Por debajo se trata como click (con tolerancia para "manos
# inestables" al hacer doble clic, p.ej.).
DRAG_DIST_THRESHOLD_PX = 8


def _button_corto(button) -> str:
    """Normaliza un botón de pynput ('Button.left') a 'left'/'right'/'middle'."""
    s = str(button).replace("Button.", "").lower().strip()
    if "right" in s:
        return "right"
    if "middle" in s:
        return "middle"
    return "left"


# Códigos de tecla de Windows para consultar el estado REAL de los
# modificadores. Se usan los específicos de izquierda/derecha porque el
# genérico VK_MENU no distingue Alt de AltGr, y en teclado español AltGr
# tiene que seguir siendo transparente (produce @ # € [ ] { }).
_VK_LATERALES = {
    "ctrl": (0xA2, 0xA3),    # VK_LCONTROL, VK_RCONTROL
    "alt": (0xA4,),          # VK_LMENU  (el derecho es AltGr)
    "altgr": (0xA5,),        # VK_RMENU
    "shift": (0xA0, 0xA1),   # VK_LSHIFT, VK_RSHIFT
    "win": (0x5B, 0x5C),     # VK_LWIN, VK_RWIN
}


# Segundos que hay que llevar creyendo que un modificador está pulsado
# antes de hacer caso a Windows y descartarlo. Es un seguro: la consulta
# al sistema lee el teclado FÍSICO, y hay escenarios (escritorio remoto,
# teclados virtuales, entrada inyectada por otro programa) donde podría
# no reflejar una tecla que sí está pulsada de verdad. Con este margen,
# una combinación normal —que dura décimas de segundo— nunca se ve
# afectada aunque la consulta falle; solo se descarta lo que lleva
# pegado tanto rato que ya no puede ser un atajo.
UMBRAL_PEGADO_S = 10.0


def _modificadores_realmente_pulsados() -> set[str] | None:
    """Qué modificadores están pulsados AHORA MISMO según Windows.

    Devuelve None fuera de Windows o si la consulta falla (entonces el
    llamador se queda con su propio estado).

    Hace falta porque el enganche de teclado puede perderse una suelta:
    si aparece un aviso de seguridad de Windows (UAC), si el sistema
    desengancha el hook por lentitud, o en algunos cambios de ventana con
    Alt+Tab. Cuando eso pasa, el modificador se queda "pegado" y a partir
    de ahí TODO lo que se teclee se graba como atajos (%h, %o, %l, %a en
    vez de "hola"), lo que estropea la grabación entera sin avisar.
    """
    try:
        import ctypes
        estado = ctypes.windll.user32.GetAsyncKeyState
    except Exception:
        return None
    try:
        pulsados = set()
        for nombre, vks in _VK_LATERALES.items():
            if any(estado(vk) & 0x8000 for vk in vks):
                pulsados.add(nombre)
        return pulsados
    except Exception:
        return None


def _modifier_for(nombre: str) -> str | None:
    """Devuelve 'ctrl' | 'shift' | 'alt' | 'altgr' | 'win' si `nombre` es
    una tecla modificadora.

    pynput entrega ctrl_l, ctrl_r, shift_l, shift_r, alt_l, alt_r, alt_gr,
    y para la tecla Windows usa cmd / cmd_l / cmd_r (nombrado así por
    compatibilidad con macOS). Los unificamos a un nombre lógico por
    familia.

    AltGr se mantiene SEPARADO de Alt: en teclado español AltGr produce
    caracteres (@ # € [ ] { } \\) y debe ser transparente para el buffer
    de texto — si lo tratáramos como Alt, teclear '@' se grabaría como
    el atajo Alt+@ en vez de como texto.
    """
    n = nombre.lower()
    if n in ("ctrl", "ctrl_l", "ctrl_r"):
        return "ctrl"
    if n in ("shift", "shift_l", "shift_r"):
        return "shift"
    if n == "alt_gr":
        return "altgr"
    if n in ("alt", "alt_l", "alt_r"):
        return "alt"
    if n in ("cmd", "cmd_l", "cmd_r", "win", "win_l", "win_r"):
        return "win"
    return None


def _normalizar_mods(mods: set[str]) -> set[str]:
    """Normaliza 'altgr' para serializar/construir tokens.

    En Windows AltGr ≡ Ctrl+Alt (el sistema envía un Ctrl sintético junto
    a AltGr). Cuando hay que expresar AltGr como modificador de un atajo
    o de un clic, lo convertimos a alt (+ctrl, que normalmente ya está
    en el set por el evento sintético)."""
    if "altgr" not in mods:
        return set(mods)
    out = set(mods) - {"altgr"}
    out |= {"alt", "ctrl"}
    return out


def _modifiers_sendkeys_prefix(mods: set[str]) -> str:
    """Construye el prefijo SendKeys (estilo pywinauto): ^ + % para Ctrl/Shift/Alt.

    NOTA: La tecla Win NO se puede expresar con prefijo SendKeys
    estándar. Para combinaciones con Win usa `_construir_send_keys_token`.
    """
    prefix = ""
    if "ctrl" in mods:
        prefix += "^"
    if "alt" in mods:
        prefix += "%"
    if "shift" in mods:
        prefix += "+"
    return prefix


def _construir_send_keys_token(mods: set[str], base: str) -> str:
    """Construye el token completo de send_keys con los modificadores aplicados.

    - Sin Win: usa el prefijo SendKeys estándar (^a, +{TAB}, %{F4}, ^+s)
    - Con Win: usa la sintaxis explícita con {VK_LWIN down}...{VK_LWIN up}
      porque pywinauto.keyboard no acepta `#` como atajo para Win.

    Ejemplos:
        ({ctrl}, "a") → "^a"
        ({ctrl, shift}, "s") → "^+s"
        ({win}, "d") → "{VK_LWIN down}d{VK_LWIN up}"
        ({win}, "{UP}") → "{VK_LWIN down}{UP}{VK_LWIN up}"
        ({win}, "1") → "{VK_LWIN down}1{VK_LWIN up}"
        ({win, ctrl}, "d") → "{VK_CONTROL down}{VK_LWIN down}d{VK_LWIN up}{VK_CONTROL up}"
    """
    mods = _normalizar_mods(mods)
    if not mods:
        return base
    if "win" not in mods:
        return _modifiers_sendkeys_prefix(mods) + base
    # Win presente: wrap con down/up explícitos.
    pre = ""
    post = ""
    if "ctrl" in mods:
        pre += "{VK_CONTROL down}"
        post = "{VK_CONTROL up}" + post
    if "alt" in mods:
        pre += "{VK_MENU down}"
        post = "{VK_MENU up}" + post
    if "shift" in mods:
        pre += "{VK_SHIFT down}"
        post = "{VK_SHIFT up}" + post
    pre += "{VK_LWIN down}"
    post = "{VK_LWIN up}" + post
    return pre + base + post


def _friendly_combo(mods: set[str], base: str) -> str:
    """Descripción legible: 'Win+D', 'Ctrl+Shift+S', 'Win+↑'."""
    mods = _normalizar_mods(mods)
    pretty_arrows = {"{UP}": "↑", "{DOWN}": "↓", "{LEFT}": "←", "{RIGHT}": "→"}
    pretty_base = pretty_arrows.get(base, base.strip("{}").upper() if base.startswith("{") else base.upper())
    partes = []
    if "ctrl" in mods:
        partes.append("Ctrl")
    if "alt" in mods:
        partes.append("Alt")
    if "shift" in mods:
        partes.append("Shift")
    if "win" in mods:
        partes.append("Win")
    partes.append(pretty_base)
    return "+".join(partes)


def _modifiers_str(mods: set[str]) -> str:
    """Serializa el set a 'ctrl+shift' (orden estable)."""
    mods = _normalizar_mods(mods)
    orden = ["ctrl", "alt", "shift", "win"]
    presentes = [m for m in orden if m in mods]
    return "+".join(presentes)


def _ventana_relativa_desde_punto(elem, x: int, y: int) -> dict | None:
    """Calcula la posición del clic relativa a la ventana top-level.

    Devuelve {"title", "fx", "fy"} donde fx/fy son fracciones [0..1] del
    ancho/alto de la ventana. Guardar fracciones (en vez de píxeles
    absolutos) hace que el clic sobreviva a que la ventana se mueva,
    cambie de tamaño o de escalado DPI (porque el rect físico de la
    ventana escala con el DPI).
    """
    try:
        top = elem.top_level_parent()
        r = top.rectangle()
        w = r.width()
        h = r.height()
        if w <= 0 or h <= 0:
            return None
        titulo = (top.window_text() or "").strip()
        if not titulo:
            return None
        fx = (x - r.left) / w
        fy = (y - r.top) / h
        # Solo tiene sentido si el punto cae dentro de la ventana
        if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
            return None
        # Guardamos también el TAMAÑO de la ventana. Con él, al reproducir
        # se puede distinguir "la ventana solo se ha movido" (traslación
        # pura, siempre correcta) de "la ventana ha cambiado de tamaño",
        # donde escalar por fracciones se equivoca en las aplicaciones
        # Win32 clásicas, que anclan sus controles arriba-izquierda.
        # Programa dueño de la ventana: lo usa la comprobación "¿estoy
        # donde creo?" al reproducir. Va aquí porque ya tenemos el
        # elemento de nivel superior resuelto.
        proceso = ""
        try:
            from .proceso import nombre_proceso_de_hwnd
            proceso = nombre_proceso_de_hwnd(top.handle)
        except Exception:
            proceso = ""
        return {
            "title": titulo,
            "proceso": proceso,
            "fx": round(fx, 4), "fy": round(fy, 4),
            "w": int(w), "h": int(h),
            "dx": int(x - r.left), "dy": int(y - r.top),
        }
    except Exception:
        return None


def _ancla_desde_punto(elem, x: int, y: int) -> dict | None:
    """Texto que identifica el sitio clicado, estilo UiPath.

    Solo se graba ancla cuando has clicado SOBRE algo que tiene texto
    propio: un botón, un rótulo, una opción de menú. Se lee del árbol UIA
    (no OCR), así que es instantáneo y exacto.

    Se lee SOLO el rótulo (la propiedad Name), nunca el contenido: el
    contenido de un campo es un dato del paciente — cambia en cada
    ejecución, no identifica nada, y no debe acabar escrito en el fichero
    de la macro.

    NO se sube a los elementos que lo contienen ni se concatenan los
    rótulos de dentro. Se intentó, y era peligroso: el texto acababa
    siendo el de un panel entero o el título del diálogo, y al reproducir
    el desplazamiento se aplicaba desde el centro de OTRA cosa — un clic
    seguro de sí mismo a cientos de píxeles del sitio correcto. Un ancla
    equivocada es peor que no tener ancla, porque no falla: acierta en el
    sitio que no es.

    Devuelve None si no hay texto propio fiable; entonces el paso se
    reproduce como siempre (ventana, imagen, coordenadas).
    """
    if elem is None:
        return None
    from .text_anchor import construir_ancla
    from .text_read import texto_de_rotulo
    texto = texto_de_rotulo(elem)
    if texto:
        try:
            r = elem.rectangle()
            ancla = construir_ancla(
                texto, (r.left, r.top, r.right, r.bottom), x, y,
            )
        except Exception:
            ancla = None
        if ancla:
            ancla["modo"] = "encima"
            return ancla
    # El control no tiene rótulo propio (un campo vacío, una celda): el
    # sitio lo identifica el rótulo de al lado.
    return _ancla_vecina(elem, x, y)


def _ancla_vecina(elem, x: int, y: int) -> dict | None:
    """Rótulo de al lado que identifica el sitio (el "anchor" de UiPath).

    Para un campo vacío, lo que identifica dónde hay que escribir no es el
    campo (no tiene texto) sino el rótulo que tiene al lado: "Primer
    apellido". Buscamos entre los hermanos el control con rótulo propio
    MÁS CERCANO al clic, y guardamos el desplazamiento respecto a ÉL.

    La clave está en que se guarda el rectángulo del propio rótulo, no el
    del contenedor: al reproducir se busca un control con ese mismo
    rótulo, así que los dos lados miden desde el mismo sitio. Hacerlo con
    el contenedor fue el error que desviaba los clics cientos de píxeles.
    """
    from .text_anchor import construir_ancla, rect_utilizable
    from .text_read import texto_de_rotulo
    try:
        padre = elem.parent()
    except Exception:
        return None
    if padre is None:
        return None
    try:
        hermanos = padre.children()
    except Exception:
        return None

    mejor = None
    mejor_dist = None
    for h in hermanos[:60]:          # tope: no recorrer formularios enormes
        try:
            texto = texto_de_rotulo(h)
            if not texto:
                continue
            r = h.rectangle()
            rect = (r.left, r.top, r.right, r.bottom)
            if not rect_utilizable(rect):
                continue
            cx, cy = (r.left + r.right) // 2, (r.top + r.bottom) // 2
            dist = abs(x - cx) + abs(y - cy)     # distancia de manzana
            if mejor_dist is None or dist < mejor_dist:
                ancla = construir_ancla(texto, rect, x, y)
                if ancla:
                    ancla["modo"] = "vecino"
                    mejor, mejor_dist = ancla, dist
        except Exception:
            continue
    return mejor


# Tipos de control que representan UNA FILA/ELEMENTO de una lista, un
# árbol o una tabla. El nombre que identifica la cosa está en ellos.
_CONTENEDORES_ITEM = {"ListItem", "TreeItem", "DataItem", "TableItem"}


def _elemento_significativo(elem):
    """Sube de una CELDA a la fila que la contiene.

    En listas y tablas (el Explorador de Windows es el ejemplo claro),
    el punto exacto donde clicas no es la fila sino una celda de
    propiedad. Esa celda se llama como la COLUMNA, no como el dato: al
    clicar en la carpeta "macros" lo que hay justo debajo del ratón es un
    control llamado "Nombre" (el título de la columna), con identificador
    `System.ItemNameDisplay`. Así que la macro guardaba "Click en Nombre"
    y, al reproducir, ese selector casaba con la celda de nombre de
    CUALQUIER fila — es decir, abría el archivo equivocado.

    La fila que la contiene sí se llama "macros". Subimos hasta ella.

    Es un cambio acotado: solo actúa si hay una fila de lista/árbol/tabla
    por encima. Un campo de un formulario normal no tiene ninguna, así
    que no se toca nada.
    """
    if elem is None:
        return elem
    try:
        if elem.element_info.control_type in _CONTENEDORES_ITEM:
            return elem            # ya estamos en la fila
    except Exception:
        return elem
    actual = elem
    for _ in range(3):             # la celda suele estar a 1-2 niveles
        try:
            actual = actual.parent()
        except Exception:
            return elem
        if actual is None:
            return elem
        try:
            if actual.element_info.control_type not in _CONTENEDORES_ITEM:
                continue
            # Solo merece la pena si la fila tiene nombre propio; si no,
            # nos quedamos con el elemento original.
            if (actual.window_text() or "").strip():
                return actual
        except Exception:
            return elem
    return elem


def _selector_desde_punto(x: int, y: int):
    """Resuelve (x,y) a un selector simbólico + respaldos robustos.

    Devuelve (selector_o_None, descripción, win_rel_o_None, ancla_o_None):
      - win_rel: {"title", "fx", "fy"}, coordenadas relativas a la ventana.
      - ancla:   {"texto", "dx", "dy"}, el TEXTO que hay en ese sitio y a
        qué distancia cayó el clic (ver core/text_anchor).
    Si falla cualquier paso, los campos correspondientes son None.
    """
    if not _HAS_PYWINAUTO:
        return None, f"({x},{y})", None, None
    try:
        elem = Desktop(backend="uia").from_point(x, y)
    except Exception:
        return None, f"({x},{y})", None, None
    # La posición de la ventana se calcula con el elemento ORIGINAL (es
    # el que está bajo el ratón); la identidad, con la fila que lo
    # contiene si la hay (ver _elemento_significativo).
    win_rel = _ventana_relativa_desde_punto(elem, x, y)
    elem = _elemento_significativo(elem)
    ancla = _ancla_desde_punto(elem, x, y)
    try:
        name = (elem.window_text() or "").strip()
    except Exception:
        name = ""
    try:
        ctrl_type = elem.element_info.control_type
    except Exception:
        ctrl_type = None
    try:
        auto_id = elem.element_info.automation_id
    except Exception:
        auto_id = None
    try:
        class_name = elem.class_name()
    except Exception:
        class_name = None
    sel = Selector(
        control_type=ctrl_type,
        name=name or None,
        auto_id=auto_id or None,
        class_name=class_name or None,
    )
    if sel.is_empty():
        return None, f"({x},{y})", win_rel, ancla
    desc = name or ctrl_type or class_name or f"({x},{y})"
    return sel, desc, win_rel, ancla


class Recorder:
    """Captura eventos crudos sin tocar pywinauto durante la grabación.

    Para obtener la `Macro` resuelta hay que llamar después a
    `Recorder.construir_macro(events, resolver_selectores=True)`.
    """


    def __init__(self):
        self.eventos_crudos: list[EventoCrudo] = []
        self._buf = _BufferTexto()
        self._lock = threading.Lock()
        self._grabando = False
        self._mouse_listener = None
        self._kb_listener = None
        # Estado vivo de teclas modificadoras pulsadas. Se rellena en
        # _on_press y se vacía en _on_release. Los clics y las teclas
        # con Ctrl/Alt activo lo consultan para etiquetarse.
        self._modifiers: set[str] = set()
        # Press de ratón pendiente de release (para detectar drag).
        self._press_pendiente: dict | None = None
        # Rectángulos de pantalla (left, top, w, h) cuyos eventos de ratón
        # NO deben grabarse: las propias ventanas de MemoviPro (el diálogo
        # de grabación y el panel flotante). Sin esto, el clic en "Detener"
        # o un arrastre del panel acaban como pasos de la macro. La UI
        # (RecordDialog) actualiza esta lista periódicamente.
        self.zonas_excluidas: list[tuple[int, int, int, int]] = []
        # Clics que se han tirado por caer sobre el propio MemoviPro.
        self.clics_descartados: int = 0

    # Propiedad usada por la GUI para el contador en vivo.
    @property
    def pasos(self) -> list[EventoCrudo]:
        return self.eventos_crudos

    def start(self) -> None:
        if not _HAS_PYNPUT:
            raise RuntimeError("pynput no disponible")
        self._grabando = True
        self.eventos_crudos = []
        self._buf = _BufferTexto()
        self._modifiers = set()
        self._modifiers_desde = {}
        self._press_pendiente = None
        self.clics_descartados = 0
        self._arrancar_miniaturas()
        self._arrancar_resolutor()
        self._mouse_listener = mouse.Listener(
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        self._kb_listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._mouse_listener.start()
        self._kb_listener.start()
        logger.info("Recorder.start · listeners pynput arrancados")

    # ---- Captura de miniaturas (fuera del enganche del ratón) ----
    #
    # Cada clic guarda una miniatura de lo que había alrededor, que sirve
    # de respaldo al reproducir. Capturarla es una operación de pantalla
    # que tarda milisegundos y a veces decenas.
    #
    # Antes se hacía DENTRO del callback del ratón, y ese es el motivo de
    # que a veces se perdieran pulsaciones: Windows tiene un tiempo máximo
    # para los enganches de bajo nivel y, si se supera, DESENGANCHA el
    # hook sin avisar. A partir de ahí la grabación sigue "en marcha" en
    # la pantalla pero ya no capta nada. Aunque no se llegue al límite, un
    # callback lento hace que el sistema descarte eventos.
    #
    # Ahora el callback solo apunta las coordenadas y sale; la captura la
    # hace este hilo unos milisegundos después. Se pierde un pelín de
    # inmediatez (la pantalla podría haber empezado a repintarse), pero
    # una miniatura imperfecta es un respaldo menos, mientras que un clic
    # perdido rompe la macro entera.
    MINIATURAS_TIMEOUT_S = 10.0

    def _arrancar_miniaturas(self) -> None:
        import queue
        self._cola_miniaturas = queue.Queue()
        self._hilo_miniaturas = threading.Thread(
            target=self._bucle_miniaturas, name="recorder-miniaturas", daemon=True,
        )
        self._hilo_miniaturas.start()

    def _bucle_miniaturas(self) -> None:
        from .image_match import capturar_region_png
        cola = self._cola_miniaturas
        while True:
            try:
                tarea = cola.get()
            except Exception:
                return
            if tarea is None:
                return
            sobre, x, y = tarea
            try:
                sobre["png"] = capturar_region_png(x, y)
            except Exception:
                sobre["png"] = None

    def _encolar_miniatura(self, x: int, y: int) -> dict:
        """Apunta la captura y devuelve el sobre donde llegará."""
        sobre: dict = {"png": None}
        cola = getattr(self, "_cola_miniaturas", None)
        if cola is not None:
            try:
                cola.put((sobre, int(x), int(y)))
            except Exception:
                pass
        return sobre

    def _parar_miniaturas(self) -> None:
        cola = getattr(self, "_cola_miniaturas", None)
        hilo = getattr(self, "_hilo_miniaturas", None)
        if cola is None or hilo is None:
            return
        try:
            cola.put(None)
            hilo.join(timeout=self.MINIATURAS_TIMEOUT_S)
        except Exception:
            pass
        self._cola_miniaturas = None
        self._hilo_miniaturas = None

    # ---- Resolución EN VIVO del elemento clicado ----
    #
    # Hasta ahora el selector y el ancla se calculaban al terminar la
    # grabación, preguntando "¿qué hay en estas coordenadas?" sobre la
    # pantalla de ESE momento. Si el formulario había cambiado —lo normal
    # en una grabación larga— se guardaba el elemento equivocado. Un
    # selector caduco al menos falla y cae a coordenadas; un ancla caduca
    # es peor: clica muy convencida en otro sitio.
    #
    # Ahora cada clic se encola y un hilo aparte lo resuelve en cuanto
    # puede, con la pantalla todavía como estaba. El hilo va aparte a
    # propósito: consultar el árbol UIA tarda décimas de segundo y hacerlo
    # dentro del enganche del ratón frenaría la grabación entera.

    # Tiempo máximo de espera al parar para que el resolutor termine la
    # cola. Lo que no dé tiempo se resuelve al construir la macro.
    RESOLUTOR_TIMEOUT_S = 20.0

    def _arrancar_resolutor(self) -> None:
        import queue
        self._cola_resolver = queue.Queue()
        self._resolutor = threading.Thread(
            target=self._bucle_resolutor, name="recorder-resolutor", daemon=True,
        )
        self._resolutor.start()

    def _bucle_resolutor(self) -> None:
        cola = self._cola_resolver
        while True:
            try:
                tarea = cola.get()
            except Exception:
                return
            if tarea is None:       # señal de parada
                return
            evt, x, y = tarea
            try:
                evt.resuelto = _selector_desde_punto(x, y)
            except Exception as exc:
                logger.debug("Resolución en vivo falló en ({},{}): {}", x, y, exc)
            finally:
                try:
                    cola.task_done()
                except Exception:
                    pass

    def _encolar_resolucion(self, evt: EventoCrudo) -> None:
        cola = getattr(self, "_cola_resolver", None)
        if cola is None:
            return
        try:
            cola.put((evt, evt.x, evt.y))
        except Exception:
            pass

    def _parar_resolutor(self) -> None:
        """Deja terminar lo que queda en la cola y para el hilo."""
        cola = getattr(self, "_cola_resolver", None)
        hilo = getattr(self, "_resolutor", None)
        if cola is None or hilo is None:
            return
        try:
            cola.put(None)
            hilo.join(timeout=self.RESOLUTOR_TIMEOUT_S)
        except Exception:
            pass
        pendientes = sum(
            1 for e in self.eventos_crudos
            if e.tipo == "click" and e.resuelto is None
        )
        if pendientes:
            logger.info(
                "{} clic(s) sin resolver en vivo: se resolverán al construir la macro",
                pendientes,
            )
        self._cola_resolver = None
        self._resolutor = None

    def stop(self) -> list[EventoCrudo]:
        """Detiene los listeners y devuelve los eventos crudos.

        Espera a que los hilos de pynput finalicen antes de retornar
        (timeout 2s cada uno). Esto es importante en Windows: los
        WH_KEYBOARD_LL / WH_MOUSE_LL siguen instalados hasta que el
        hilo dueño termina, y mientras estén instalados los diálogos
        nativos de Windows (file dialog, etc.) pueden congelarse.
        """
        self._grabando = False
        listeners = [l for l in (self._mouse_listener, self._kb_listener) if l is not None]
        for lst in listeners:
            try:
                lst.stop()
            except Exception as exc:
                logger.debug("Fallo al detener un listener de captura: {}", exc)
        for lst in listeners:
            try:
                if lst.is_alive():
                    lst.join(timeout=2.0)
            except Exception as exc:
                logger.debug("Fallo al esperar (join) a un listener de captura: {}", exc)
        self._mouse_listener = None
        self._kb_listener = None
        self._parar_miniaturas()
        self._parar_resolutor()
        with self._lock:
            self._flush_text()
        logger.info(
            "Recorder.stop · {} eventos crudos capturados (clicks={}, type_text={}, send_keys={}, scroll={}, drag={})",
            len(self.eventos_crudos),
            sum(1 for e in self.eventos_crudos if e.tipo == "click"),
            sum(1 for e in self.eventos_crudos if e.tipo == "type_text"),
            sum(1 for e in self.eventos_crudos if e.tipo == "send_keys"),
            sum(1 for e in self.eventos_crudos if e.tipo == "scroll"),
            sum(1 for e in self.eventos_crudos if e.tipo == "drag"),
        )
        return list(self.eventos_crudos)

    def _punto_excluido(self, x: int, y: int) -> bool:
        """¿El punto cae dentro de una ventana propia de MemoviPro?"""
        for (left, top, w, h) in list(self.zonas_excluidas):
            if left <= x <= left + w and top <= y <= top + h:
                return True
        return False

    # ---- Callbacks ----
    # Todos los callbacks van blindados con try/except: pynput DETIENE el
    # listener si un callback lanza una excepción, y el resultado sería
    # una grabación que sigue "en marcha" en la UI pero ya no captura
    # nada (síntoma real reportado). Mejor perder un evento y loguearlo
    # que perder el resto de la grabación en silencio.
    def _on_click(self, x, y, button, pressed):
        try:
            self._on_click_impl(x, y, button, pressed)
        except Exception:
            logger.exception("Error en el callback de clic; evento descartado")

    def _on_click_impl(self, x, y, button, pressed):
        """Maneja press y release del ratón.

        En el press guardamos la posición y el botón en `_press_pendiente`.
        En el release decidimos si fue un click (release cerca del press)
        o un drag (release significativamente lejos del press).
        """
        if not self._grabando:
            return
        if self._punto_excluido(int(x), int(y)):
            # Clic sobre el propio MemoviPro (botón Detener, arrastre del
            # panel flotante...): no es parte de la macro. Si había un
            # press pendiente (arrastre que termina sobre el panel), se
            # descarta también.
            #
            # Se CUENTAN porque son una causa real de "he pulsado y no lo
            # ha grabado": si el panel flotante tapa el botón que quieres
            # pulsar, el clic desaparece sin decir nada. El contador sale
            # en la ventana de grabación para que se vea al momento.
            with self._lock:
                self._press_pendiente = None
                if pressed:
                    self.clics_descartados += 1
                    logger.info(
                        "Clic en ({},{}) descartado: cae sobre una ventana de "
                        "MemoviPro. Aparta el panel si tapa lo que quieres pulsar.",
                        int(x), int(y),
                    )
            return
        btn = _button_corto(button)
        if pressed:
            # Encolar la miniatura para que la capture OTRO hilo. Aquí
            # dentro no se puede: ver _arrancar_miniaturas.
            sobre = self._encolar_miniatura(int(x), int(y))
            with self._lock:
                self._press_pendiente = {
                    "x": int(x), "y": int(y),
                    "button": btn,
                    "modifiers": _modifiers_str(self._modifiers),
                    "timestamp": time.time(),
                    "img_holder": sobre,
                }
            return
        # ----- Release -----
        with self._lock:
            pendiente = self._press_pendiente
            self._press_pendiente = None
            if pendiente is None or pendiente["button"] != btn:
                return  # release huérfano: ignorar
            self._flush_text()
            dx_abs = abs(int(x) - pendiente["x"])
            dy_abs = abs(int(y) - pendiente["y"])
            if dx_abs > DRAG_DIST_THRESHOLD_PX or dy_abs > DRAG_DIST_THRESHOLD_PX:
                # Es un drag (arrastrar).
                self._emitir_drag(pendiente, int(x), int(y))
            else:
                # Click normal. Usamos la posición del press (más natural;
                # un usuario que mueve 2-3 px sin querer no debe cambiar
                # el objetivo).
                self._emitir_click(pendiente)

    def _emitir_click(self, pendiente: dict) -> None:
        """Emite un click. Asume _lock ya adquirido por el caller."""
        ahora = pendiente["timestamp"]  # usamos timestamp del press
        btn = pendiente["button"]
        mods = pendiente["modifiers"]
        x = pendiente["x"]
        y = pendiente["y"]
        # ¿Es la segunda mitad de un doble clic? (modificadores y botón coinciden)
        if self.eventos_crudos:
            ultimo = self.eventos_crudos[-1]
            if (
                ultimo.tipo == "click"
                and not ultimo.double
                and ultimo.button == btn
                and ultimo.modifiers == mods
                and (ahora - ultimo.timestamp) < DOUBLE_CLICK_THRESHOLD_S
                and abs(ultimo.x - x) <= DOUBLE_CLICK_RADIUS_PX
                and abs(ultimo.y - y) <= DOUBLE_CLICK_RADIUS_PX
            ):
                ultimo.double = True
                ultimo.descripcion = self._descripcion_click(ultimo.x, ultimo.y, btn, mods, double=True)
                return
        evt = EventoCrudo(
            tipo="click",
            x=x, y=y,
            button=btn,
            modifiers=mods,
            descripcion=self._descripcion_click(x, y, btn, mods, double=False),
            timestamp=ahora,
            img_holder=pendiente.get("img_holder"),
        )
        self.eventos_crudos.append(evt)
        # Resolver YA, con la pantalla como está ahora (en otro hilo, para
        # no frenar la grabación).
        self._encolar_resolucion(evt)

    def _emitir_drag(self, pendiente: dict, x_release: int, y_release: int) -> None:
        """Emite un drag de (press.x, press.y) a (release.x, release.y)."""
        mods_label = pendiente["modifiers"].upper() + " " if pendiente["modifiers"] else ""
        btn_suffix = "" if pendiente["button"] == "left" else f" [{pendiente['button']}]"
        desc = (
            f"{mods_label}Drag {pendiente['x']},{pendiente['y']} → "
            f"{x_release},{y_release}{btn_suffix}"
        )
        self.eventos_crudos.append(EventoCrudo(
            tipo="drag",
            x=pendiente["x"], y=pendiente["y"],
            x2=x_release, y2=y_release,
            button=pendiente["button"],
            modifiers=pendiente["modifiers"],
            descripcion=desc,
            timestamp=pendiente["timestamp"],
        ))

    def _on_scroll(self, x, y, dx, dy):
        try:
            self._on_scroll_impl(x, y, dx, dy)
        except Exception:
            logger.exception("Error en el callback de scroll; evento descartado")

    def _on_scroll_impl(self, x, y, dx, dy):
        """Captura la rueda del ratón. Cada notch es un evento independiente."""
        if not self._grabando:
            return
        if self._punto_excluido(int(x), int(y)):
            return
        with self._lock:
            self._flush_text()
            mods = _modifiers_str(self._modifiers)
            direccion = "↑" if dy > 0 else ("↓" if dy < 0 else ("→" if dx > 0 else "←"))
            mods_label = mods.upper() + " " if mods else ""
            desc = f"{mods_label}Scroll {direccion} ({x},{y})"
            self.eventos_crudos.append(EventoCrudo(
                tipo="scroll",
                x=int(x), y=int(y),
                dx=int(dx), dy=int(dy),
                modifiers=mods,
                descripcion=desc,
                timestamp=time.time(),
            ))

    @staticmethod
    def _descripcion_click(x: int, y: int, btn: str, mods: str, double: bool) -> str:
        partes = []
        if mods:
            partes.append(mods.replace("+", "+").upper())
        partes.append("Doble click" if double else "Click")
        if btn != "left":
            partes.append(f"[{btn}]")
        partes.append(f"({x},{y})")
        return " ".join(partes)

    def _on_press(self, key):
        try:
            self._on_press_impl(key)
        except Exception:
            logger.exception("Error en el callback de tecla; evento descartado")

    def _on_press_impl(self, key):
        if not self._grabando:
            return
        nombre = str(key).replace("Key.", "").replace("'", "")
        if nombre in TECLAS_IGNORADAS:
            return
        # Tecla modificadora: solo actualizar estado, sin emitir evento.
        # OJO: aquí NO se hace flush del buffer de texto. El flush ocurre
        # más abajo solo si la siguiente tecla resulta ser un atajo. Hacer
        # flush en cada press de modificador fragmentaba el texto: cada
        # Shift de una mayúscula (y el Ctrl sintético que Windows envía
        # con AltGr) partía "Hola Mundo" en varios pasos type_text.
        mod = _modifier_for(nombre)
        if mod is not None:
            with self._lock:
                self._modifiers.add(mod)
                # Cuándo empezó a estar pulsado (para detectar "pegados").
                if not hasattr(self, "_modifiers_desde"):
                    self._modifiers_desde = {}
                # Reloj MONÓTONO: aquí medimos cuánto rato llevamos con la
                # tecla pulsada, no a qué hora fue. Así no lo afecta un
                # cambio de hora del sistema ni el horario de verano.
                self._modifiers_desde.setdefault(mod, time.monotonic())
            return
        with self._lock:
            self._descartar_modificadores_pegados()
            char = self._tecla_a_char(key)
            # La barra espaciadora llega como Key.space (sin .char). La
            # tratamos como el carácter ' ' para que "hola mundo" sea UN
            # solo type_text — como paso send_keys suelto el espacio se
            # perdía al reproducir (send_keys sin with_spaces los descarta).
            if char is None and nombre == "space":
                char = " "
            # Ctrl+letra llega en Windows como carácter de control
            # (\x01..\x1a), no como la letra. Recuperamos la letra real
            # para grabar "^a" y no el token irreproducible "^\x01".
            if char is not None and ord(char) < 32:
                if "ctrl" in self._modifiers and 1 <= ord(char) <= 26:
                    char = chr(ord(char) + 96)
                else:
                    char = None  # control char sin mapeo → probar como tecla especial
            # Modificadores "efectivos" para decidir texto vs atajo:
            # - shift es transparente (solo cambia mayúsculas/símbolos).
            # - AltGr es transparente (produce caracteres: @ # € [ ] { })
            #   igual que el Ctrl sintético que Windows envía junto a AltGr.
            efectivos = self._modifiers - {"shift", "altgr"}
            if "altgr" in self._modifiers:
                efectivos -= {"ctrl"}
            if char is not None and not efectivos:
                ahora = time.time()
                if not self._buf.texto:
                    self._buf.primer_ts = ahora  # arranque de una ráfaga de texto
                self._buf.texto += char
                self._buf.ultimo_ts = ahora
                return
            self._flush_text()
            if char is not None:
                # Escapar metacaracteres de send_keys en la base del atajo:
                # Ctrl+'+' debe grabarse como "^{+}" — "^+" es un prefijo
                # Ctrl+Shift sin tecla y revienta al reproducir.
                base = "{SPACE}" if char == " " else escape_send_keys(char)
            else:
                base = self._tecla_a_send_keys(key)
                if not base:
                    logger.debug("Tecla sin mapeo send_keys descartada: {}", nombre)
                    return
            token = _construir_send_keys_token(self._modifiers, base)
            descripcion = "Tecla " + _friendly_combo(self._modifiers, base)
            self.eventos_crudos.append(EventoCrudo(
                tipo="send_keys",
                valor=token,
                descripcion=descripcion,
                timestamp=time.time(),
            ))

    def _descartar_modificadores_pegados(self) -> None:
        """Quita los modificadores que llevan pegados demasiado tiempo.

        Si se pierde la suelta de una tecla (un aviso de seguridad de
        Windows, el sistema desenganchando el hook, ciertos Alt+Tab), el
        modificador se queda pulsado para siempre en nuestro estado y a
        partir de ahí todo lo tecleado se graba como atajos: "hola" sale
        como %h %o %l %a y la grabación entera queda inservible.

        Solo se QUITA, nunca se añade, y solo cuando se cumplen las DOS
        condiciones: que Windows diga que la tecla no está pulsada y que
        llevemos más de UMBRAL_PEGADO_S creyéndolo. Lo segundo es el
        seguro explicado arriba: sin él, un escenario donde la consulta al
        sistema no viera la tecla convertiría todos los atajos en texto,
        que es un daño mayor que el que se quiere evitar.

        Asume el lock adquirido por el llamador.
        """
        reales = _modificadores_realmente_pulsados()
        if reales is None:
            return                      # fuera de Windows: no sabemos nada
        desde = getattr(self, "_modifiers_desde", None)
        if not desde:
            return                      # sin cuándo se pulsó, no juzgamos
        ahora = time.monotonic()
        pegados = {
            m for m in (self._modifiers - reales)
            if ahora - desde.get(m, ahora) > UMBRAL_PEGADO_S
        }
        if not pegados:
            return
        logger.warning(
            "Modificadores pegados descartados tras {}s: {} "
            "(se perdió la suelta de la tecla)",
            int(UMBRAL_PEGADO_S), sorted(pegados),
        )
        self._modifiers -= pegados
        for m in pegados:
            desde.pop(m, None)

    def _on_release(self, key):
        try:
            self._on_release_impl(key)
        except Exception:
            logger.exception("Error en el callback de release de tecla")

    def _on_release_impl(self, key):
        if not self._grabando:
            return
        nombre = str(key).replace("Key.", "").replace("'", "")
        mod = _modifier_for(nombre)
        if mod is None:
            return
        with self._lock:
            self._modifiers.discard(mod)
            desde = getattr(self, "_modifiers_desde", None)
            if desde:
                desde.pop(mod, None)

    def _flush_text(self) -> None:
        if not self._buf.texto:
            return
        # El timestamp del paso es el del PRIMER carácter: así el delay
        # antes del type_text refleja la pausa REAL previa a empezar a
        # teclear, no la pausa + toda la duración del tecleo (que hacía
        # que el replay esperase de más y luego tecleara de golpe).
        ts = self._buf.primer_ts or self._buf.ultimo_ts or time.time()
        self.eventos_crudos.append(EventoCrudo(
            tipo="type_text",
            valor=self._buf.texto,
            descripcion=f'Escribir "{self._buf.texto[:30]}"',
            timestamp=ts,
        ))
        self._buf = _BufferTexto()

    @staticmethod
    def _tecla_a_char(key) -> str | None:
        try:
            if hasattr(key, "char") and key.char is not None and len(key.char) == 1:
                return key.char
        except Exception:
            pass
        return None

    @staticmethod
    def _tecla_a_send_keys(key) -> str | None:
        nombre = str(key).replace("Key.", "").replace("'", "")
        mapping = {
            "enter": "{ENTER}", "tab": "{TAB}", "esc": "{ESC}",
            "space": "{SPACE}", "backspace": "{BACKSPACE}", "delete": "{DELETE}",
            "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
            "home": "{HOME}", "end": "{END}", "page_up": "{PGUP}", "page_down": "{PGDN}",
            # Teclas que antes se descartaban en silencio: al grabarlas no
            # pasaba nada y la macro salía incompleta sin decir por qué.
            "insert": "{INSERT}", "print_screen": "{PRTSC}",
            "menu": "{VK_APPS}", "apps": "{VK_APPS}",
            "caps_lock": "{CAPSLOCK}", "num_lock": "{VK_NUMLOCK}",
            "scroll_lock": "{VK_SCROLL}", "pause": "{BREAK}",
        }
        if nombre in mapping:
            return mapping[nombre]
        if nombre.startswith("f") and nombre[1:].isdigit():
            return "{" + nombre.upper() + "}"
        return None

    # ---- Construcción de la Macro (puede ser lenta si se resuelven selectores) ----
    # Cap a la pausa entre eventos: 30 minutos. Antes eran 30s pero el
    # usuario reportó que necesita pausas más largas en flujos reales
    # (cargas pesadas, esperar a un operador, refrescos lentos del SAP,
    # etc). 30 min es generoso pero bounded: si te dejas la grabación
    # encendida toda la noche, la pausa no crece sin límite.
    MAX_DELAY_S = 1800.0

    @staticmethod
    def construir_macro(
        eventos: list[EventoCrudo],
        resolver_selectores: bool = True,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Macro:
        """Convierte eventos crudos en una `Macro` con delays preservados.

        El campo `delay_before_s` de cada paso refleja el tiempo real
        transcurrido entre el evento anterior y éste (limitado a
        MAX_DELAY_S para evitar pausas absurdamente largas).
        """
        total_clicks = sum(1 for e in eventos if e.tipo == "click")
        n_click = 0
        pasos: list[Step] = []
        prev_ts: float | None = None
        for evt in eventos:
            delay = 0.0
            if prev_ts is not None and evt.timestamp > 0:
                delay = max(0.0, evt.timestamp - prev_ts)
                if delay > Recorder.MAX_DELAY_S:
                    delay = Recorder.MAX_DELAY_S
            if evt.timestamp > 0:
                prev_ts = evt.timestamp

            if evt.tipo == "click":
                n_click += 1
                sel = None
                desc = evt.descripcion
                win_rel = None
                ancla = None
                if resolver_selectores:
                    # Preferimos SIEMPRE lo resuelto en vivo: se calculó
                    # con la pantalla tal y como estaba al clicar.
                    if evt.resuelto is not None:
                        sel, desc, win_rel, ancla = evt.resuelto
                    else:
                        sel, desc, win_rel, ancla = _selector_desde_punto(evt.x, evt.y)
                # Prefijos para la descripción del paso
                mods_label = evt.modifiers.upper() + " " if evt.modifiers else ""
                accion = "Doble click" if evt.double else "Click"
                btn_suffix = "" if evt.button == "left" else f" [{evt.button}]"
                # La miniatura puede venir directa (grabaciones antiguas o
                # tests) o dentro del sobre que rellenó el hilo aparte.
                png = evt.img_png
                if png is None and evt.img_holder:
                    png = evt.img_holder.get("png")
                img_b64 = ""
                if png:
                    try:
                        from .image_match import png_a_b64
                        img_b64 = png_a_b64(png)
                    except Exception:
                        img_b64 = ""
                if sel is not None:
                    extra: dict = {"fallback_xy": [evt.x, evt.y]}
                    if win_rel:
                        extra["win_rel"] = win_rel
                    if ancla:
                        extra["texto_ancla"] = ancla
                    if img_b64:
                        extra["img_b64"] = img_b64
                    if evt.button != "left":
                        extra["button"] = evt.button
                    if evt.double:
                        extra["double"] = True
                    if evt.modifiers:
                        extra["modifiers"] = evt.modifiers
                    pasos.append(Step(
                        tipo=StepType.CLICK_CONTROL,
                        selector=sel,
                        descripcion=f"{mods_label}{accion} en {desc}{btn_suffix}",
                        delay_before_s=delay,
                        extra=extra,
                    ))
                else:
                    extra = {"x": evt.x, "y": evt.y}
                    if win_rel:
                        extra["win_rel"] = win_rel
                    if ancla:
                        extra["texto_ancla"] = ancla
                    if img_b64:
                        extra["img_b64"] = img_b64
                    if evt.button != "left":
                        extra["button"] = evt.button
                    if evt.double:
                        extra["double"] = True
                    if evt.modifiers:
                        extra["modifiers"] = evt.modifiers
                    pasos.append(Step(
                        tipo=StepType.CLICK_AT_XY,
                        extra=extra,
                        descripcion=f"{mods_label}{accion} en ({evt.x},{evt.y}){btn_suffix} — sin selector",
                        delay_before_s=delay,
                    ))
                if on_progress is not None:
                    on_progress(n_click, total_clicks)
            elif evt.tipo == "type_text":
                # raw=True: el texto grabado es LITERAL. Sin este flag, un
                # texto tecleado que contenga {DNI}, {MM} o {SECRET:x} sería
                # sustituido por el motor de placeholders al reproducir
                # (incluyendo teclear secretos reales del almacén).
                pasos.append(Step(
                    tipo=StepType.TYPE_TEXT,
                    valor=evt.valor,
                    descripcion=evt.descripcion,
                    delay_before_s=delay,
                    extra={"raw": True},
                ))
            elif evt.tipo == "send_keys":
                # raw=True también aquí: los tokens {ENTER}/{TAB}/{F1}...
                # colisionan con el regex de placeholders si el Excel tiene
                # una columna llamada "enter", "tab", etc.
                pasos.append(Step(
                    tipo=StepType.SEND_KEYS,
                    valor=evt.valor,
                    descripcion=evt.descripcion,
                    delay_before_s=delay,
                    extra={"raw": True},
                ))
            elif evt.tipo == "scroll":
                extra: dict = {"x": evt.x, "y": evt.y, "dx": evt.dx, "dy": evt.dy}
                if evt.modifiers:
                    extra["modifiers"] = evt.modifiers
                pasos.append(Step(
                    tipo=StepType.SCROLL,
                    extra=extra,
                    descripcion=evt.descripcion,
                    delay_before_s=delay,
                ))
            elif evt.tipo == "drag":
                extra: dict = {
                    "x1": evt.x, "y1": evt.y,
                    "x2": evt.x2, "y2": evt.y2,
                }
                if evt.button != "left":
                    extra["button"] = evt.button
                if evt.modifiers:
                    extra["modifiers"] = evt.modifiers
                pasos.append(Step(
                    tipo=StepType.DRAG,
                    extra=extra,
                    descripcion=evt.descripcion,
                    delay_before_s=delay,
                ))
        return Macro(nombre="grabacion", pasos=pasos)
