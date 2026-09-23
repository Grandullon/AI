"""Las tres piezas que acercan MemoviPro a UiPath:
1. esperar a que la aplicación esté lista antes de actuar;
2. modo simulado: pulsar sin ratón ni foco;
3. reintentos configurables y visibles.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.espera_listo import esperar_listo
from core.step_model import Macro, Selector, Step, StepType


class _Reloj:
    def __init__(self):
        self.t = 0.0

    def dormir(self, s):
        self.t += s

    def ahora(self):
        return self.t


def _sonda(secuencia):
    """Devuelve los estados en orden; luego "" (lista) para siempre."""
    seq = list(secuencia)
    return lambda: seq.pop(0) if seq else ""


# ==================== 1. esperar a que esté lista ====================

def test_si_esta_lista_no_espera_nada():
    """El caso normal no debe añadir ni un milisegundo a la macro."""
    r = _Reloj()
    res = esperar_listo(_sonda([""]), timeout_s=10, dormir=r.dormir, reloj=r.ahora)
    assert res.listo and r.t == 0.0


def test_espera_mientras_esta_ocupada():
    r = _Reloj()
    res = esperar_listo(
        _sonda(["reloj de arena"] * 5), timeout_s=10, intervalo_s=0.1,
        dormir=r.dormir, reloj=r.ahora)
    assert res.listo
    assert res.motivo == "reloj de arena"
    assert r.t > 0.4               # esperó de verdad


def test_exige_dos_lecturas_seguidas_de_lista():
    """Al cargar un informe el reloj de arena parpadea entre fases: una
    sola lectura de "lista" puede caer justo en el hueco."""
    r = _Reloj()
    # ocupada, lista (hueco), ocupada, lista, lista
    lecturas = []
    base = _sonda(["ocupada", "", "ocupada", "", ""])

    def sonda():
        v = base()
        lecturas.append(v)
        return v

    res = esperar_listo(sonda, timeout_s=10, intervalo_s=0.1,
                        dormir=r.dormir, reloj=r.ahora)
    assert res.listo
    assert lecturas == ["ocupada", "", "ocupada", "", ""]


def test_si_no_se_libera_sigue_igualmente():
    """Nunca hace fallar un paso: agotada la espera, se sigue como antes."""
    r = _Reloj()
    res = esperar_listo(lambda: "no responde", timeout_s=2, intervalo_s=0.5,
                        dormir=r.dormir, reloj=r.ahora)
    assert not res.listo
    assert res.motivo == "no responde"
    assert 2.0 <= r.t <= 2.6


def test_espera_cero_la_desactiva():
    r = _Reloj()
    res = esperar_listo(lambda: "no responde", timeout_s=0,
                        dormir=r.dormir, reloj=r.ahora)
    assert res.listo and r.t == 0.0


def test_fuera_de_windows_no_frena():
    from core.espera_listo import sondear_ventana_frontal
    assert sondear_ventana_frontal() == ""


def test_se_espera_antes_de_clicar_y_teclear(monkeypatch):
    """Los clics por POSICIÓN no esperaban nada: eran un tercio de los
    pasos de las macros reales, y los más propensos a fallar cuando el
    equipo va cargado."""
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = False
    p.macro = Macro(nombre="m", pasos=[])
    orden = []
    monkeypatch.setattr(Player, "_comprobar_foco_esperado", lambda self, paso: orden.append("FOCO"))
    monkeypatch.setattr(Player, "_esperar_listo", lambda self: orden.append("LISTO"))
    monkeypatch.setattr(Player, "_click_at_xy", lambda self, paso: orden.append("CLIC"))
    monkeypatch.setattr(Player, "_type_text", lambda self, paso: orden.append("TECLEO"))

    Player._dispatch(p, Step(tipo=StepType.CLICK_AT_XY, extra={"x": 1, "y": 1}))
    assert orden == ["FOCO", "LISTO", "CLIC"]      # primero la ventana, luego esperar
    orden.clear()
    Player._dispatch(p, Step(tipo=StepType.TYPE_TEXT, valor="hola"))
    assert orden == ["LISTO", "TECLEO"]


def test_la_espera_se_lee_de_config(tmp_path):
    import json
    from core.config_ejecucion import opciones_ejecucion
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"espera_listo_s": 25}), encoding="utf-8")
    assert opciones_ejecucion(cfg)["espera_listo_s"] == 25.0
    cfg.write_text(json.dumps({"espera_listo_s": "mucho"}), encoding="utf-8")
    assert opciones_ejecucion(cfg)["espera_listo_s"] == 10.0


def test_las_cadenas_reciben_las_opciones():
    """Antes las cadenas no recibían NADA de config.json."""
    src = (ROOT / "core" / "pipeline_runner.py").read_text(encoding="utf-8")
    assert "**self.opciones" in src
    ui = (ROOT / "ui" / "pipeline_panel.py").read_text(encoding="utf-8")
    assert "opciones=opciones_ejecucion(" in ui
    cli = (ROOT / "cli.py").read_text(encoding="utf-8")
    assert "opciones=_opciones_ejecucion()" in cli


# ==================== 2. modo simulado ====================

class _Ctrl:
    def __init__(self, admite=("invoke",)):
        self.admite = admite
        self.hecho = []

    def invoke(self):
        if "invoke" not in self.admite:
            raise RuntimeError("sin patrón Invoke")
        self.hecho.append("invoke")

    def toggle(self):
        if "toggle" not in self.admite:
            raise RuntimeError("sin patrón Toggle")
        self.hecho.append("toggle")

    def select(self):
        if "select" not in self.admite:
            raise RuntimeError("sin patrón Select")
        self.hecho.append("select")

    def set_edit_text(self, t):
        self.hecho.append(("texto", t))


def _paso_sim(name="Guardar", tipo="Button", **extra):
    e = {"metodo": "simular"}
    e.update(extra)
    return Step(tipo=StepType.CLICK_CONTROL,
                selector=Selector(control_type=tipo, name=name), extra=e)


def _player(monkeypatch, ctrl):
    from core.player import Player
    p = Player.__new__(Player)
    p.dry_run = False
    monkeypatch.setattr(Player, "_resolve_control", lambda self, paso: ctrl)
    return p


def test_simulado_invoca_un_boton(monkeypatch):
    from core.player import Player
    ctrl = _Ctrl(("invoke",))
    p = _player(monkeypatch, ctrl)
    assert Player._click_simulado(p, _paso_sim()) is True
    assert ctrl.hecho == ["invoke"]


def test_simulado_conmuta_una_casilla_y_selecciona_un_elemento(monkeypatch):
    from core.player import Player
    ctrl = _Ctrl(("toggle",))
    assert Player._click_simulado(_player(monkeypatch, ctrl),
                                  _paso_sim("Guardar con contraseña", "CheckBox"))
    assert ctrl.hecho == ["toggle"]
    ctrl = _Ctrl(("select",))
    assert Player._click_simulado(_player(monkeypatch, ctrl),
                                  _paso_sim("Incidencias", "TreeItem"))
    assert ctrl.hecho == ["select"]


def test_si_el_control_no_lo_admite_se_usa_el_raton(monkeypatch):
    from core.player import Player
    ctrl = _Ctrl(())
    assert Player._click_simulado(_player(monkeypatch, ctrl), _paso_sim()) is False


def test_simulado_no_se_intenta_con_selector_flojo(monkeypatch):
    """Sin un control concreto no hay nada que pulsar «por dentro»."""
    from core.player import Player
    llamadas = []
    monkeypatch.setattr(Player, "_resolve_control",
                        lambda self, paso: llamadas.append(1) or _Ctrl())
    p = Player.__new__(Player)
    p.dry_run = False
    assert Player._click_simulado(p, _paso_sim(name=None)) is False
    assert llamadas == []


def test_simulado_no_imita_doble_clic_ni_modificadores(monkeypatch):
    from core.player import Player
    p = _player(monkeypatch, _Ctrl())
    assert Player._click_simulado(p, _paso_sim(double=True)) is False
    assert Player._click_simulado(p, _paso_sim(button="right")) is False
    assert Player._click_simulado(p, _paso_sim(modifiers="ctrl")) is False


def test_simulado_no_necesita_la_ventana_delante(monkeypatch):
    """Lo importante: si funciona, no se toca el foco para nada."""
    from core.player import Player
    p = _player(monkeypatch, _Ctrl(("invoke",)))
    orden = []
    monkeypatch.setattr(Player, "_comprobar_foco_esperado",
                        lambda self, paso: orden.append("FOCO"))
    monkeypatch.setattr(Player, "_click_control",
                        lambda self, paso: orden.append("RATON"))
    Player._dispatch(p, _paso_sim())
    assert orden == []


def test_si_simulado_falla_cae_al_camino_normal(monkeypatch):
    from core.player import Player
    p = _player(monkeypatch, _Ctrl(()))
    orden = []
    monkeypatch.setattr(Player, "_comprobar_foco_esperado",
                        lambda self, paso: orden.append("FOCO"))
    monkeypatch.setattr(Player, "_esperar_listo", lambda self: orden.append("LISTO"))
    monkeypatch.setattr(Player, "_click_control",
                        lambda self, paso: orden.append("RATON"))
    Player._dispatch(p, _paso_sim())
    assert orden == ["FOCO", "LISTO", "RATON"]


def test_escritura_simulada_necesita_saber_el_campo(monkeypatch):
    from core.player import Player
    ctrl = _Ctrl()
    p = _player(monkeypatch, ctrl)
    con_campo = Step(tipo=StepType.TYPE_TEXT, valor="12345",
                     selector=Selector(control_type="Edit", name="DNI"),
                     extra={"metodo": "simular"})
    assert Player._escribir_simulado(p, con_campo) is True
    assert ctrl.hecho == [("texto", "12345")]
    sin_campo = Step(tipo=StepType.TYPE_TEXT, valor="x", extra={"metodo": "simular"})
    assert Player._escribir_simulado(p, sin_campo) is False


# ==================== 3. reintentos ====================

def _player_reintentos(monkeypatch, fallos):
    import threading
    from core.player import Player
    p = Player.__new__(Player)
    p._abort = threading.Event()
    estado = {"n": 0}

    def dispatch(self, paso):
        estado["n"] += 1
        if estado["n"] <= fallos:
            raise RuntimeError(f"fallo {estado['n']}")

    monkeypatch.setattr(Player, "_dispatch", dispatch)
    esperas = []
    monkeypatch.setattr("core.player.time.sleep", lambda s: esperas.append(s))
    return p, estado, esperas


def test_reintenta_y_acierta(monkeypatch):
    from core.player import Player
    p, estado, esperas = _player_reintentos(monkeypatch, fallos=2)
    Player._ejecutar_paso(p, Step(tipo=StepType.SLEEP, reintentos=2), 0)
    assert estado["n"] == 3
    assert esperas == [0.5, 1.0]         # espera automática creciente


def test_espera_configurada_por_paso(monkeypatch):
    from core.player import Player
    p, estado, esperas = _player_reintentos(monkeypatch, fallos=2)
    paso = Step(tipo=StepType.SLEEP, reintentos=3, extra={"reintento_espera_s": 4})
    Player._ejecutar_paso(p, paso, 0)
    assert esperas == [4.0, 4.0]


def test_sin_reintentos_falla_a_la_primera(monkeypatch):
    from core.player import Player, StepFailed
    p, estado, esperas = _player_reintentos(monkeypatch, fallos=5)
    try:
        Player._ejecutar_paso(p, Step(tipo=StepType.SLEEP, reintentos=0), 0)
        assert False
    except StepFailed:
        pass
    assert estado["n"] == 1 and esperas == []


def test_no_espera_tras_el_ultimo_intento(monkeypatch):
    """Antes se dormía también después del último fallo, para nada."""
    from core.player import Player, StepFailed
    p, estado, esperas = _player_reintentos(monkeypatch, fallos=10)
    try:
        Player._ejecutar_paso(p, Step(tipo=StepType.SLEEP, reintentos=2), 0)
    except StepFailed:
        pass
    assert estado["n"] == 3 and len(esperas) == 2


def test_parar_corta_los_reintentos(monkeypatch):
    from core.player import Player, StepFailed
    p, estado, esperas = _player_reintentos(monkeypatch, fallos=10)
    p._abort.set()
    try:
        Player._ejecutar_paso(p, Step(tipo=StepType.SLEEP, reintentos=5), 0)
    except StepFailed:
        pass
    assert estado["n"] == 1


# ==================== opciones del paso en la tabla y el YAML ====================

def test_las_opciones_por_defecto_no_ensucian_el_yaml():
    """Una macro que no las usa no cambia ni de huella."""
    from core.opciones_paso import aplicar_opciones as aplicar
    p = Step(tipo=StepType.CLICK_CONTROL, extra={"x": 1})
    aplicar(p, "raton", 2, 0.0)
    assert p.to_dict()["extra"] == {"x": 1}
    assert "reintentos" not in p.to_dict()


def test_opciones_se_guardan_y_se_leen():
    from core.opciones_paso import aplicar_opciones as aplicar, marcas_del_paso as marcas
    p = Step(tipo=StepType.CLICK_CONTROL)
    aplicar(p, "simular", 4, 2.5)
    d = p.to_dict()
    assert d["extra"]["metodo"] == "simular"
    assert d["extra"]["reintento_espera_s"] == 2.5
    assert d["reintentos"] == 4
    q = Step.from_dict(d)
    assert marcas(q) == "⚡simulado  ↻4/2.5s"
    aplicar(q, "raton", 2, 0)
    assert marcas(q) == ""
