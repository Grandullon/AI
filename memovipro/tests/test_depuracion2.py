"""Tests del "modo depuración 2.0": saltar, repetir, pasos desactivados,
grabar con opciones y arranque del paso a paso desde un paso N.
"""
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _player_min():
    from core.player import Player
    p = Player.__new__(Player)
    p._step_mode = True
    p._run_mode = "step"
    p._breakpoints = set()
    p._step_continue = threading.Event()
    p._step_back_flag = False
    p._skip_flag = False
    p._repeat_flag = False
    p._abort = threading.Event()
    p._step_idx = 0
    return p


# ==================== flags de navegación ====================

def test_skip_step_marca_flag_y_despierta():
    from core.player import Player
    p = _player_min()
    Player.skip_step(p)
    assert p._skip_flag is True
    assert p._repeat_flag is False
    assert p._step_back_flag is False
    assert p._step_continue.is_set()


def test_repeat_step_marca_flag_y_despierta():
    from core.player import Player
    p = _player_min()
    Player.repeat_step(p)
    assert p._repeat_flag is True
    assert p._skip_flag is False
    assert p._step_continue.is_set()


def test_advance_step_limpia_skip_y_repeat():
    from core.player import Player
    p = _player_min()
    p._skip_flag = True
    p._repeat_flag = True
    Player.advance_step(p)
    assert p._skip_flag is False
    assert p._repeat_flag is False


def test_step_back_limpia_skip_y_repeat():
    from core.player import Player
    p = _player_min()
    p._skip_flag = True
    p._repeat_flag = True
    Player.step_back(p)
    assert p._skip_flag is False
    assert p._repeat_flag is False
    assert p._step_back_flag is True


def test_mover_puntero():
    from core.player import Player
    p = _player_min()
    Player.mover_puntero(p, 7)
    assert p.step_index() == 7
    Player.mover_puntero(p, -3)   # se normaliza
    assert p.step_index() == 0


# ==================== paso desactivado ====================

def test_step_activo_por_defecto_y_no_se_serializa():
    from core.step_model import Step, StepType
    s = Step(tipo=StepType.SLEEP, valor="1")
    assert s.activo is True
    assert "activo" not in s.to_dict()   # macros existentes no cambian


def test_step_desactivado_se_serializa_y_carga():
    from core.step_model import Step, StepType
    s = Step(tipo=StepType.SLEEP, valor="1", activo=False)
    d = s.to_dict()
    assert d["activo"] is False
    assert Step.from_dict(d).activo is False


def test_yaml_antiguo_sin_activo_carga_como_activo():
    from core.step_model import Step
    s = Step.from_dict({"tipo": "sleep", "valor": "1"})
    assert s.activo is True


def test_render_step_conserva_activo():
    from core.step_model import Step, StepType, render_step
    s = Step(tipo=StepType.SLEEP, valor="1", activo=False)
    assert render_step(s, {}).activo is False


def test_loop_salta_pasos_desactivados(monkeypatch):
    """Un paso desactivado no se ejecuta ni se anuncia."""
    monkeypatch.setattr("core.player._HAS_PYWINAUTO", True)
    from core.player import Player, RunStatus
    from core.step_model import Macro, Step, StepType

    pasos = [
        Step(tipo=StepType.SLEEP, valor="0", descripcion="uno"),
        Step(tipo=StepType.SLEEP, valor="0", descripcion="dos", activo=False),
        Step(tipo=StepType.SLEEP, valor="0", descripcion="tres"),
    ]
    macro = Macro(nombre="m", pasos=pasos, auto_anchor=False)
    vistos = []
    p = Player(
        macro=macro, screenshots_dir=".", logger=None, dry_run=True,
        step_mode=True, run_mode="continue",
        on_status=lambda st: vistos.append(st.paso_idx),
    )
    exito, _ = p.ejecutar_dni({"DNI": "x"})
    assert exito is True
    assert vistos == [0, 2]   # el paso 1 (desactivado) ni aparece


def test_fingerprint_no_cambia_si_todos_activos():
    """Añadir el campo `activo` no debe alterar la huella de macros que no
    lo usan (los checkpoints existentes siguen siendo válidos)."""
    from core.step_model import Macro, Step, StepType
    m = Macro(nombre="m", pasos=[Step(tipo=StepType.SLEEP, valor="1")])
    # Huella calculada sobre un to_dict que NO incluye 'activo'
    assert "activo" not in m.pasos[0].to_dict()
    m2 = Macro.from_dict(m.to_dict())
    assert m.fingerprint() == m2.fingerprint()


# ==================== integración con el loop ====================

def test_loop_skip_no_ejecuta_el_paso(monkeypatch):
    """Con skip_step, el paso se salta sin ejecutarse."""
    import time
    monkeypatch.setattr("core.player._HAS_PYWINAUTO", True)
    from core.player import Player
    from core.step_model import Macro, Step, StepType

    pasos = [Step(tipo=StepType.SLEEP, valor="0") for _ in range(3)]
    macro = Macro(nombre="m", pasos=pasos, auto_anchor=False)
    ejecutados = []
    pausas = []

    p = Player(
        macro=macro, screenshots_dir=".", logger=None, dry_run=True,
        step_mode=True, run_mode="step",
        on_status=lambda st: pausas.append(st.paso_idx) if st.en_pausa else None,
    )
    # Registrar qué pasos llegan a ejecutarse
    orig = Player._ejecutar_paso
    monkeypatch.setattr(
        Player, "_ejecutar_paso",
        lambda self, paso, idx: (ejecutados.append(idx), orig(self, paso, idx))[-1],
    )

    parar = threading.Event()

    def usuario():
        # Salta el paso 0, ejecuta el 1 y el 2
        vistas = 0
        while not parar.is_set():
            if len(pausas) > vistas:
                idx = pausas[vistas]
                vistas += 1
                time.sleep(0.05)
                if idx == 0:
                    p.skip_step()
                else:
                    p.advance_step()
            time.sleep(0.02)

    t = threading.Thread(target=usuario, daemon=True)
    t.start()
    exito, _ = p.ejecutar_dni({"DNI": "x"})
    parar.set()

    assert exito is True
    assert 0 not in ejecutados      # saltado
    assert ejecutados == [1, 2]


def test_loop_repeat_reejecuta_el_mismo_paso(monkeypatch):
    """Con repeat_step, el paso se ejecuta otra vez y se vuelve a pausar
    en el MISMO índice."""
    import time
    monkeypatch.setattr("core.player._HAS_PYWINAUTO", True)
    from core.player import Player
    from core.step_model import Macro, Step, StepType

    pasos = [Step(tipo=StepType.SLEEP, valor="0") for _ in range(2)]
    macro = Macro(nombre="m", pasos=pasos, auto_anchor=False)
    ejecutados = []
    pausas = []

    p = Player(
        macro=macro, screenshots_dir=".", logger=None, dry_run=True,
        step_mode=True, run_mode="step",
        on_status=lambda st: pausas.append(st.paso_idx) if st.en_pausa else None,
    )
    orig = Player._ejecutar_paso
    monkeypatch.setattr(
        Player, "_ejecutar_paso",
        lambda self, paso, idx: (ejecutados.append(idx), orig(self, paso, idx))[-1],
    )

    parar = threading.Event()
    estado = {"repetido": False}

    def usuario():
        vistas = 0
        while not parar.is_set():
            if len(pausas) > vistas:
                idx = pausas[vistas]
                vistas += 1
                time.sleep(0.05)
                if idx == 0 and not estado["repetido"]:
                    estado["repetido"] = True
                    p.repeat_step()      # ejecuta el 0 otra vez
                else:
                    p.advance_step()
            time.sleep(0.02)

    t = threading.Thread(target=usuario, daemon=True)
    t.start()
    exito, _ = p.ejecutar_dni({"DNI": "x"})
    parar.set()

    assert exito is True
    # El paso 0 se ejecutó DOS veces (repetido) y luego el 1
    assert ejecutados == [0, 0, 1]
    # Y se pausó dos veces en el 0
    assert pausas[:3] == [0, 0, 1]


# ==================== recarga tras modificar la macro en pausa ====================

def test_mover_puntero_fuerza_recarga_y_despierta():
    from core.player import Player
    p = _player_min()
    Player.mover_puntero(p, 3)
    assert p.step_index() == 3
    assert p._recargar_flag is True
    assert p._step_continue.is_set()   # despierta el wait


def test_insertar_antes_ejecuta_los_nuevos_y_no_el_viejo(monkeypatch):
    """Regresión: el bucle captura el paso ANTES de pausarse. Si la UI
    inserta pasos delante, sin recargar ejecutaría el paso viejo y se
    saltaría los recién insertados."""
    import time
    monkeypatch.setattr("core.player._HAS_PYWINAUTO", True)
    from core.player import Player
    from core.step_model import Macro, Step, StepType

    original = Step(tipo=StepType.SLEEP, valor="0", descripcion="ORIGINAL")
    macro = Macro(nombre="m", pasos=[original], auto_anchor=False)
    ejecutados = []
    pausas = []

    p = Player(
        macro=macro, screenshots_dir=".", logger=None, dry_run=True,
        step_mode=True, run_mode="step",
        on_status=lambda st: pausas.append(st.paso_idx) if st.en_pausa else None,
    )
    monkeypatch.setattr(
        Player, "_ejecutar_paso",
        lambda self, paso, idx: ejecutados.append(paso.descripcion),
    )

    parar = threading.Event()
    estado = {"insertado": False}

    def usuario():
        vistas = 0
        while not parar.is_set():
            if len(pausas) > vistas:
                vistas += 1
                time.sleep(0.05)
                if not estado["insertado"]:
                    estado["insertado"] = True
                    # Insertar 2 pasos ANTES del actual (como hace la UI)
                    nuevos = [
                        Step(tipo=StepType.SLEEP, valor="0", descripcion="NUEVO1"),
                        Step(tipo=StepType.SLEEP, valor="0", descripcion="NUEVO2"),
                    ]
                    macro.pasos[0:0] = nuevos
                    p.mover_puntero(0)     # puntero al primer nuevo + recarga
                else:
                    p.advance_step()
            time.sleep(0.02)

    t = threading.Thread(target=usuario, daemon=True)
    t.start()
    exito, _ = p.ejecutar_dni({"DNI": "x"})
    parar.set()

    assert exito is True
    # Se ejecutan los DOS nuevos y luego el original, en orden.
    assert ejecutados == ["NUEVO1", "NUEVO2", "ORIGINAL"]


def test_reemplazar_no_ejecuta_el_paso_borrado(monkeypatch):
    """Al reemplazar, el paso capturado antes de la pausa ya no existe:
    no debe ejecutarse."""
    import time
    monkeypatch.setattr("core.player._HAS_PYWINAUTO", True)
    from core.player import Player
    from core.step_model import Macro, Step, StepType

    viejo = Step(tipo=StepType.SLEEP, valor="0", descripcion="VIEJO")
    macro = Macro(nombre="m", pasos=[viejo], auto_anchor=False)
    ejecutados = []
    pausas = []

    p = Player(
        macro=macro, screenshots_dir=".", logger=None, dry_run=True,
        step_mode=True, run_mode="step",
        on_status=lambda st: pausas.append(st.paso_idx) if st.en_pausa else None,
    )
    monkeypatch.setattr(
        Player, "_ejecutar_paso",
        lambda self, paso, idx: ejecutados.append(paso.descripcion),
    )

    parar = threading.Event()
    estado = {"hecho": False}

    def usuario():
        vistas = 0
        while not parar.is_set():
            if len(pausas) > vistas:
                vistas += 1
                time.sleep(0.05)
                if not estado["hecho"]:
                    estado["hecho"] = True
                    del macro.pasos[0:1]                     # borra VIEJO
                    macro.pasos[0:0] = [Step(tipo=StepType.SLEEP, valor="0",
                                             descripcion="NUEVO")]
                    p.mover_puntero(0)
                else:
                    p.advance_step()
            time.sleep(0.02)

    t = threading.Thread(target=usuario, daemon=True)
    t.start()
    exito, _ = p.ejecutar_dni({"DNI": "x"})
    parar.set()

    assert exito is True
    assert "VIEJO" not in ejecutados     # el borrado NO se ejecuta
    assert ejecutados == ["NUEVO"]


# ==================== hallazgos de la revisión ====================

def test_continue_run_limpia_los_flags():
    """Un F4/F5 pulsado a destiempo no debe aplicarse al reanudar."""
    from core.player import Player
    p = _player_min()
    p._skip_flag = True
    p._repeat_flag = True
    p._recargar_flag = True
    Player.continue_run(p)
    assert (p._skip_flag, p._repeat_flag, p._recargar_flag) == (False, False, False)
    assert p._run_mode == "continue"


def test_run_mode_solo_cuenta_breakpoints_alcanzables():
    """Un punto anterior a start_idx o sobre un paso desactivado no
    dispararía: si fuese el único, la sesión debe arrancar en 'step' y no
    auto-reproducir la macro entera."""
    from core.debug_marks import decidir_run_mode, breakpoints_alcanzables
    from core.step_model import Step, StepType

    pasos = [Step(tipo=StepType.SLEEP, valor="0") for _ in range(5)]
    # bp anterior al arranque → inalcanzable
    assert decidir_run_mode({1}, 3, pasos) == "step"
    # bp alcanzable
    assert decidir_run_mode({4}, 3, pasos) == "continue"
    # bp sobre paso desactivado → inalcanzable
    pasos[4].activo = False
    assert decidir_run_mode({4}, 3, pasos) == "step"
    assert breakpoints_alcanzables({1, 4}, 3, pasos) == set()
    # fuera de rango
    assert decidir_run_mode({99}, 0, pasos) == "step"


def test_if_ventana_desactivado_salta_tambien_su_bloque(monkeypatch):
    """Desactivar la condición no debe dejar su bloque ejecutándose
    siempre: se salta la guarda Y los pasos que protege."""
    monkeypatch.setattr("core.player._HAS_PYWINAUTO", True)
    from core.player import Player
    from core.step_model import Macro, Step, StepType

    pasos = [
        Step(tipo=StepType.IF_VENTANA, extra={"ventana": "X", "saltar_si_no": 2},
             activo=False, descripcion="IF"),
        Step(tipo=StepType.SLEEP, valor="0", descripcion="BLOQUE1"),
        Step(tipo=StepType.SLEEP, valor="0", descripcion="BLOQUE2"),
        Step(tipo=StepType.SLEEP, valor="0", descripcion="DESPUES"),
    ]
    macro = Macro(nombre="m", pasos=pasos, auto_anchor=False)
    ejecutados = []
    monkeypatch.setattr(
        Player, "_ejecutar_paso",
        lambda self, paso, idx: ejecutados.append(paso.descripcion),
    )
    p = Player(macro=macro, screenshots_dir=".", logger=None, dry_run=True)
    exito, _ = p.ejecutar_dni({"DNI": "x"})
    assert exito is True
    # El bloque protegido NO se ejecuta; solo lo posterior.
    assert ejecutados == ["DESPUES"]


def test_atras_salta_pasos_desactivados(monkeypatch):
    """◀ Atrás debe retroceder al paso ACTIVO anterior, no quedarse
    clavado por culpa de uno desactivado en medio."""
    import time
    monkeypatch.setattr("core.player._HAS_PYWINAUTO", True)
    from core.player import Player
    from core.step_model import Macro, Step, StepType

    pasos = [
        Step(tipo=StepType.SLEEP, valor="0", descripcion="A"),
        Step(tipo=StepType.SLEEP, valor="0", descripcion="B", activo=False),
        Step(tipo=StepType.SLEEP, valor="0", descripcion="C"),
    ]
    macro = Macro(nombre="m", pasos=pasos, auto_anchor=False)
    pausas = []
    monkeypatch.setattr(Player, "_ejecutar_paso", lambda self, paso, idx: None)
    p = Player(
        macro=macro, screenshots_dir=".", logger=None, dry_run=True,
        step_mode=True, run_mode="step",
        on_status=lambda st: pausas.append(st.paso_idx) if st.en_pausa else None,
    )

    parar = threading.Event()
    estado = {"atras": False}

    def usuario():
        vistas = 0
        while not parar.is_set():
            if len(pausas) > vistas:
                idx = pausas[vistas]
                vistas += 1
                time.sleep(0.05)
                if idx == 2 and not estado["atras"]:
                    estado["atras"] = True
                    p.step_back()     # desde C: debe ir a A, no quedarse en C
                else:
                    p.advance_step()
            time.sleep(0.02)

    t = threading.Thread(target=usuario, daemon=True)
    t.start()
    exito, _ = p.ejecutar_dni({"DNI": "x"})
    parar.set()
    assert exito is True
    # Pausó en 0, 2, y tras el Atrás volvió al 0 (saltando el desactivado)
    assert pausas[:3] == [0, 2, 0]


# ==================== propagación y cableado ====================

def test_replay_runner_propaga_skip_y_repeat():
    from core.replay_runner import ReplayRunner
    r = ReplayRunner.__new__(ReplayRunner)
    llam = {"skip": 0, "rep": 0}

    class _FakePlayer:
        def skip_step(self): llam["skip"] += 1
        def repeat_step(self): llam["rep"] += 1

    r._player = _FakePlayer()
    r.skip_step()
    r.repeat_step()
    assert llam == {"skip": 1, "rep": 1}


def test_panel_tiene_botones_y_atajos():
    src = (ROOT / "ui" / "step_through_panel.py").read_text(encoding="utf-8")
    # Botones nuevos
    for marca in ("⏭ F4", "🔁 F12", "✏️ Editar"):
        assert marca in src
    # Atajos globales nuevos
    assert '_pynput_keyboard.Key.f4: "skip"' in src
    assert '_pynput_keyboard.Key.f12: "repeat"' in src
    # Y el despachador los conoce
    assert '"skip": self._on_skip' in src
    assert '"repeat": self._on_repeat' in src


def test_panel_grabar_ofrece_tres_opciones():
    src = (ROOT / "ui" / "step_through_panel.py").read_text(encoding="utf-8")
    fn = src.split("def _integrar_grabacion")[1].split("\n    def ")[0]
    assert "Insertar DESPUÉS" in fn
    assert "Insertar ANTES" in fn
    assert "REEMPLAZAR" in fn
    # Al insertar antes hay que mover el puntero para no re-ejecutar
    assert "mover_puntero" in fn


def test_editor_hasta_aqui_deja_en_pausa():
    """'▶ Hasta aquí' debe entrar en la sesión de depuración con un
    breakpoint en ese paso (antes terminaba la ejecución)."""
    src = (ROOT / "ui" / "step_editor.py").read_text(encoding="utf-8")
    fn = src.split("def _run_hasta_aqui")[1].split("\n    def ")[0]
    assert "_arrancar_step_through" in fn
    assert "breakpoints_extra" in fn


def test_editor_paso_a_paso_desde_fila():
    src = (ROOT / "ui" / "step_editor.py").read_text(encoding="utf-8")
    fn = src.split("def _launch_step_through")[1].split("\n    def ")[0]
    assert "start_idx" in fn


def test_editor_toggle_activo():
    src = (ROOT / "ui" / "step_editor.py").read_text(encoding="utf-8")
    assert "def _toggle_activo" in src
    fn = src.split("def _toggle_activo")[1].split("\n    def ")[0]
    assert "paso.activo = not paso.activo" in fn
    # Y la tabla marca los desactivados
    assert "setStrikeOut(True)" in src
