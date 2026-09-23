"""Corte automático de una tanda descarrilada y borrado de capturas
antiguas (llevan datos de pacientes en pantalla)."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.cortacircuitos import Cortacircuitos


# ==================== corte por fallos seguidos ====================

def test_fallos_sueltos_no_cortan():
    """Un caso que no está no es motivo para parar la tanda."""
    c = Cortacircuitos(3)
    for exito in (True, False, True, False, True, False):
        c.registrar(exito)
        assert not c.debe_parar()


def test_tres_seguidos_cortan():
    c = Cortacircuitos(3)
    c.registrar(False); c.registrar(False)
    assert not c.debe_parar()
    c.registrar(False)
    assert c.debe_parar()
    assert "seguidos han fallado" in c.motivo
    assert "Solo pendientes" in c.motivo      # dice cómo continuar


def test_un_exito_reinicia_la_cuenta():
    c = Cortacircuitos(3)
    c.registrar(False); c.registrar(False)
    c.registrar(True)                          # la macro se recupera sola
    c.registrar(False); c.registrar(False)
    assert not c.debe_parar()


def test_se_puede_desactivar():
    c = Cortacircuitos(0)
    for _ in range(50):
        c.registrar(False)
    assert not c.debe_parar()


def test_una_vez_disparado_no_se_desarma():
    c = Cortacircuitos(2)
    c.registrar(False); c.registrar(False)
    assert c.debe_parar()
    c.registrar(True)
    assert c.debe_parar()


# ==================== integración con el runner ====================

def _runner_falso(resultados, max_ko=3):
    """MacroRunner con lo mínimo para ejercitar _procesar_lote."""
    import threading
    from core.runner import MacroRunner
    from core.step_model import Macro

    r = MacroRunner.__new__(MacroRunner)
    r.macro = Macro(nombre="m", pasos=[])
    r.screenshots_dir = Path(".")
    r.excel_logger = None
    r.dry_run = True
    r.ignorar_popups = []
    r.polling_watchdog_ms = 300
    r.on_status = None
    r.on_dni_done = None
    r._abort = threading.Event()
    r._player = None
    r.max_ko_seguidos = max_ko
    r.cortado_por = ""
    r.politica_intrusas = None
    r.espera_listo_s = None

    class _Chk:
        def marcar_ok(self, d): pass
        def marcar_ko(self, d): pass
    r.checkpoint = _Chk()

    procesados = []

    class _PlayerFalso:
        def __init__(self, **kw): pass
        def ejecutar_dni(self, fila):
            procesados.append(fila["DNI"])
            return resultados.get(fila["DNI"], True), []
    return r, _PlayerFalso, procesados


def test_el_runner_para_la_tanda_y_no_toca_los_siguientes(monkeypatch):
    """Lo importante: los casos que quedan NO se procesan. Antes la macro
    perdida seguía actuando sobre los 197 restantes."""
    import core.runner as rn
    cola = [{"DNI": f"{i}"} for i in range(10)]
    # Los tres primeros fallan
    r, PlayerFalso, procesados = _runner_falso({"0": False, "1": False, "2": False})
    monkeypatch.setattr(rn, "Player", PlayerFalso)

    ok, ko = r._procesar_lote(cola, etiqueta_pasada="p1")
    assert procesados == ["0", "1", "2"]       # se detuvo en el tercero
    assert len(ko) == 3 and ok == []
    assert r.cortado_por
    assert r._abort.is_set()                   # y no se lanza el reintento


def test_el_runner_termina_la_tanda_si_no_hay_racha(monkeypatch):
    import core.runner as rn
    cola = [{"DNI": f"{i}"} for i in range(6)]
    r, PlayerFalso, procesados = _runner_falso({"1": False, "3": False})
    monkeypatch.setattr(rn, "Player", PlayerFalso)

    ok, ko = r._procesar_lote(cola, etiqueta_pasada="p1")
    assert len(procesados) == 6                # los recorre todos
    assert len(ok) == 4 and len(ko) == 2
    assert r.cortado_por == ""


# ==================== retención de capturas ====================

def test_borra_las_capturas_viejas_y_conserva_las_recientes(tmp_path):
    from core.retencion import limpiar_capturas

    vieja = tmp_path / "incidencia_vieja.png"
    reciente = tmp_path / "incidencia_hoy.png"
    otra = tmp_path / "no_es_imagen.txt"
    for f in (vieja, reciente, otra):
        f.write_bytes(b"x")
    antiguo = time.time() - 40 * 86400
    import os
    os.utime(vieja, (antiguo, antiguo))
    os.utime(otra, (antiguo, antiguo))

    assert limpiar_capturas(tmp_path, dias=30) == 1
    assert not vieja.exists()
    assert reciente.exists()
    assert otra.exists()          # solo toca imágenes


def test_retencion_desactivada_no_borra_nada(tmp_path):
    from core.retencion import limpiar_capturas
    import os
    f = tmp_path / "a.png"
    f.write_bytes(b"x")
    antiguo = time.time() - 400 * 86400
    os.utime(f, (antiguo, antiguo))
    assert limpiar_capturas(tmp_path, dias=0) == 0
    assert f.exists()


def test_retencion_no_revienta_con_carpeta_inexistente():
    from core.retencion import limpiar_capturas
    assert limpiar_capturas("/no/existe/esta/carpeta") == 0
    assert limpiar_capturas(None) == 0
