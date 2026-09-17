"""Qué pasa cuando se cuela otra ventana delante en plena ejecución.

Se prueba la escalada completa con un reloj falso, sin tocar ninguna
ventana de verdad.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ventana_intrusa import (
    Politica, politica_desde_config, resolver, titulo_coincide,
)


class _Escena:
    """Simula lo que hay delante a lo largo del tiempo."""

    def __init__(self, secuencia, nuestro="gerhonte.exe"):
        self.secuencia = list(secuencia)     # [(proceso, titulo), ...]
        self.nuestro = nuestro
        self.t = 0.0
        self.activaciones = 0
        self.cerradas = []

    def mirar(self):
        return self.secuencia.pop(0) if self.secuencia else (self.nuestro, "")

    def activar(self):
        self.activaciones += 1

    def cerrar(self, titulo):
        self.cerradas.append(titulo)

    def dormir(self, s):
        self.t += s

    def reloj(self):
        return self.t


def _resolver(escena, politica=None):
    return resolver(
        "gerhonte.exe", escena.mirar, escena.activar, escena.cerrar,
        politica or Politica(esperar_s=10.0, intervalo_s=1.0),
        dormir=escena.dormir, reloj=escena.reloj,
    )


# ==================== casos ====================

def test_si_no_hay_intrusa_no_hace_nada():
    e = _Escena([("gerhonte.exe", "GERHONTE")])
    r = _resolver(e)
    assert r.ok and r.intrusa is None
    assert e.activaciones == 0 and r.acciones == []


def test_un_aviso_que_se_va_solo_no_tumba_el_paso():
    """El caso más común: salta un aviso de Windows y desaparece. Antes
    esto tumbaba un paso que habría funcionado sin hacer nada."""
    e = _Escena([
        ("explorer.exe", "Actualizaciones de Windows"),
        ("gerhonte.exe", "GERHONTE"),
    ])
    r = _resolver(e)
    assert r.ok
    assert str(r.intrusa) == "«Actualizaciones de Windows» (explorer.exe)"
    # En la primera vuelta solo espera: no forcejea con el foco
    assert r.acciones == ["esperar"]
    assert e.activaciones == 0


def test_si_no_se_va_sola_se_recupera_nuestra_ventana():
    """Otra ventana se puso encima y ahí se queda: hay que activarla."""
    e = _Escena([
        ("chrome.exe", "Gmail"),
        ("chrome.exe", "Gmail"),
        ("gerhonte.exe", "GERHONTE"),
    ])
    r = _resolver(e)
    assert r.ok
    assert r.acciones == ["esperar", "activar"]
    assert e.activaciones == 1


def test_se_rinde_diciendo_que_estorbaba():
    e = _Escena([("teams.exe", "Reunión de equipo")] * 40)
    r = _resolver(e, Politica(esperar_s=3.0, intervalo_s=1.0))
    assert not r.ok
    assert r.intrusa.titulo == "Reunión de equipo"
    msg = r.explicacion("gerhonte.exe")
    assert "Reunión de equipo" in msg
    assert "cerrar_titulos" in msg          # dice cómo evitarlo la próxima


def test_solo_cierra_las_ventanas_apuntadas():
    """Nunca se cierra nada por iniciativa propia: podría ser un diálogo
    importante."""
    e = _Escena([
        ("nota.exe", "Aviso del antivirus"),
        ("gerhonte.exe", "GERHONTE"),
    ])
    r = _resolver(e, Politica(esperar_s=5.0, intervalo_s=1.0,
                              cerrar_titulos=["antivirus"]))
    assert r.ok
    assert e.cerradas == ["Aviso del antivirus"]
    assert e.activaciones == 0              # no hizo falta forcejear


def test_una_ventana_no_apuntada_no_se_cierra():
    e = _Escena([("banco.exe", "Confirmar transferencia")] * 20)
    r = _resolver(e, Politica(esperar_s=2.0, intervalo_s=1.0,
                              cerrar_titulos=["antivirus"]))
    assert not r.ok
    assert e.cerradas == []                 # ni se toca


def test_el_titulo_coincide_por_trozo_y_sin_mayusculas():
    assert titulo_coincide("Aviso del ANTIVIRUS Corporativo", ["antivirus"])
    assert titulo_coincide("Windows Update", ["update"])
    assert not titulo_coincide("GERHONTE", ["antivirus"])
    assert not titulo_coincide("", ["algo"])
    assert not titulo_coincide("algo", [])
    assert not titulo_coincide("algo", ["   "])    # patrón vacío no cuenta


def test_no_se_queda_colgado_para_siempre():
    """Importante: una tanda no puede quedarse esperando sin fin."""
    e = _Escena([("otro.exe", "Lo que sea")] * 1000)
    r = _resolver(e, Politica(esperar_s=4.0, intervalo_s=1.0))
    assert not r.ok
    assert r.segundos <= 5.0


def test_si_no_se_sabe_que_hay_delante_se_deja_pasar():
    """Cuando la consulta al sistema falla no se sabe nada, y frenar cada
    paso por una duda dejaría el programa inservible. Solo se bloquea
    cuando se ve un programa DISTINTO, que es el caso peligroso."""
    def mirar_roto():
        raise RuntimeError("boom")

    r = resolver("gerhonte.exe", mirar_roto, lambda: None, lambda t: None,
                 Politica(esperar_s=1.0, intervalo_s=0.0),
                 dormir=lambda s: None, reloj=lambda: 0.0)
    assert r.ok                             # devuelve, no lanza


def test_aguanta_que_falle_activar_o_cerrar():
    """Un fallo al mover ventanas no debe reventar la ejecución."""
    e = _Escena([("chrome.exe", "Gmail")] * 3 + [("gerhonte.exe", "G")])

    def activar_roto():
        raise RuntimeError("boom")

    def cerrar_roto(t):
        raise RuntimeError("boom")

    r = resolver("gerhonte.exe", e.mirar, activar_roto, cerrar_roto,
                 Politica(esperar_s=10.0, intervalo_s=1.0,
                          cerrar_titulos=["Gmail"]),
                 dormir=e.dormir, reloj=e.reloj)
    assert r.ok                             # se recuperó pese a los fallos


# ==================== configuración ====================

def test_lee_la_politica_de_config():
    pol = politica_desde_config({"ventanas_intrusas": {
        "esperar_s": 30, "intervalo_s": 2,
        "cerrar_titulos": ["Actualizaciones", "  "],
    }})
    assert pol.esperar_s == 30.0
    assert pol.intervalo_s == 2.0
    assert pol.cerrar_titulos == ["Actualizaciones"]


def test_config_ausente_o_rota_da_valores_por_defecto():
    for cfg in ({}, None, {"ventanas_intrusas": "no es un diccionario"},
                {"ventanas_intrusas": {"esperar_s": "mucho"}}):
        pol = politica_desde_config(cfg)
        assert pol.esperar_s == 15.0 and pol.cerrar_titulos == []


def test_la_lista_de_avisos_a_ignorar_llega_a_la_aplicacion(tmp_path):
    """Antes `popup_titulos_ignorar` solo lo leía la línea de comandos:
    desde la aplicación iba siempre vacía y configurarla no servía."""
    import json
    from core.config_ejecucion import opciones_ejecucion

    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({
        "popup_titulos_ignorar": ["Guardado correctamente"],
        "ventanas_intrusas": {"cerrar_titulos": ["Actualizaciones"]},
    }), encoding="utf-8")
    op = opciones_ejecucion(cfg)
    assert op["ignorar_popups"] == ["Guardado correctamente"]
    assert op["politica_intrusas"].cerrar_titulos == ["Actualizaciones"]


def test_sin_config_no_revienta(tmp_path):
    from core.config_ejecucion import opciones_ejecucion
    op = opciones_ejecucion(tmp_path / "no-existe.json")
    assert op["ignorar_popups"] == []
    assert op["politica_intrusas"].esperar_s == 15.0


def test_todos_los_caminos_de_ejecucion_leen_la_config():
    """Las cuatro formas de ejecutar una macro desde la aplicación."""
    for fichero in ("run_panel.py", "replay_panel.py",
                    "step_editor.py", "step_through_panel.py"):
        src = (ROOT / "ui" / fichero).read_text(encoding="utf-8")
        assert "opciones_ejecucion(" in src, f"{fichero} no lee config.json"
