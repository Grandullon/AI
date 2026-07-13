"""Tests de la Tanda 2 de la auditoría (operación diaria).

C1 — schedule_panel: nombre sin prefijo para metadata (Editar/Eliminar)
C2 — excel_logger: Excel bloqueado no aborta el lote (reintenta + CSV)
C3 — rutas de config/data derivadas de la app real (no _MEIPASS)
C4/C5 — main_window: pánico aborta cadenas + closeEvent aborta hilos
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ==================== C2: Excel robusto ====================

def test_c2_append_atomico_escribe_bien(tmp_path):
    from core.excel_logger import ExcelLogger, Incidencia

    log = ExcelLogger(tmp_path / "inc.xlsx")
    r = log.append(Incidencia(
        dni="12345678Z", macro="m", paso_idx=3, paso_tipo="click",
        tipo_error="system", detalle="prueba",
    ))
    assert r > 0
    # No debe quedar ningún .tmp tras el guardado atómico
    assert not (tmp_path / "inc.xlsx.tmp").exists()
    assert log.count_by_dni().get("12345678Z") == 1


def test_c2_excel_bloqueado_no_propaga_y_vuelca_csv(tmp_path, monkeypatch):
    """Si el guardado del Excel falla con PermissionError (fichero abierto),
    append NO debe propagar: devuelve -1 y vuelca la fila a un CSV."""
    from core.excel_logger import ExcelLogger, Incidencia

    log = ExcelLogger(tmp_path / "inc.xlsx")

    # Simular que TODO save al Excel lanza PermissionError (Excel abierto).
    def boom(wb):
        raise PermissionError("[Errno 13] fichero abierto en Excel")

    monkeypatch.setattr(log, "_guardar_atomico", boom)
    # Acortar los sleeps de reintento para que el test sea rápido.
    monkeypatch.setattr("core.excel_logger.time.sleep", lambda *_: None)

    inc = Incidencia(
        dni="99999999R", macro="m", paso_idx=1, paso_tipo="type_text",
        tipo_error="system", detalle="dni que falla",
    )
    r = log.append(inc)  # no debe lanzar
    assert r == -1

    csv_path = (tmp_path / "inc.xlsx").with_suffix(".pendientes.csv")
    assert csv_path.exists()
    contenido = csv_path.read_text(encoding="utf-8-sig")
    assert "99999999R" in contenido
    # Cabecera + 1 fila
    assert contenido.count("99999999R") == 1


def test_c2_varias_incidencias_bloqueadas_se_acumulan_en_csv(tmp_path, monkeypatch):
    from core.excel_logger import ExcelLogger, Incidencia

    log = ExcelLogger(tmp_path / "inc.xlsx")
    monkeypatch.setattr(log, "_guardar_atomico",
                        lambda wb: (_ for _ in ()).throw(PermissionError("x")))
    monkeypatch.setattr("core.excel_logger.time.sleep", lambda *_: None)

    for dni in ("A1", "A2", "A3"):
        assert log.append(Incidencia(
            dni=dni, macro="m", paso_idx=0, paso_tipo="", tipo_error="system",
        )) == -1

    csv_path = (tmp_path / "inc.xlsx").with_suffix(".pendientes.csv")
    lineas = [l for l in csv_path.read_text(encoding="utf-8-sig").splitlines() if l.strip()]
    # cabecera + 3 filas
    assert len(lineas) == 4


def test_c2_guardar_atomico_limpia_tmp_si_replace_falla(tmp_path, monkeypatch):
    """Si el replace final falla (Excel bloqueado en Windows), el .tmp NO
    debe quedar huérfano en data/."""
    from core.excel_logger import ExcelLogger, Incidencia

    log = ExcelLogger(tmp_path / "inc.xlsx")
    tmp_file = (tmp_path / "inc.xlsx").with_suffix(".xlsx.tmp")

    # Simular: save escribe el .tmp correctamente, pero replace falla.
    import pathlib

    def replace_falla(self, target):
        raise PermissionError("destino bloqueado por Excel")

    monkeypatch.setattr(pathlib.Path, "replace", replace_falla)

    class _WB:
        def save(self, path):
            pathlib.Path(path).write_bytes(b"contenido tmp")

    try:
        log._guardar_atomico(_WB())
        assert False, "debía re-lanzar PermissionError"
    except PermissionError:
        pass
    # El .tmp debe haberse limpiado pese al fallo.
    assert not tmp_file.exists(), "el .tmp quedó huérfano"


def test_c2_reintenta_y_acaba_escribiendo(tmp_path, monkeypatch):
    """Si el Excel se libera tras 2 intentos, la fila acaba en el .xlsx
    (no en el CSV)."""
    from core.excel_logger import ExcelLogger, Incidencia

    log = ExcelLogger(tmp_path / "inc.xlsx")
    real = log._guardar_atomico
    estado = {"intentos": 0}

    def flaky(wb):
        estado["intentos"] += 1
        if estado["intentos"] < 3:
            raise PermissionError("aún abierto")
        return real(wb)

    monkeypatch.setattr(log, "_guardar_atomico", flaky)
    monkeypatch.setattr("core.excel_logger.time.sleep", lambda *_: None)

    r = log.append(Incidencia(
        dni="OK123", macro="m", paso_idx=0, paso_tipo="", tipo_error="",
        estado="OK",
    ))
    assert r > 0
    assert not (tmp_path / "inc.xlsx").with_suffix(".pendientes.csv").exists()
    assert log.count_by_dni().get("OK123") == 1


# ==================== C1: prefijo del scheduler ====================

def test_c1_prefix_importable_desde_scheduler():
    from core.scheduler import PREFIX
    assert PREFIX == "MemoviPro_"


def test_c1_sin_prefijo_es_la_funcion_real_que_usa_el_panel():
    """`sin_prefijo` es la fuente única de verdad: la usa tanto
    schedule_panel._nombre_seleccionado como este test. Una regresión en
    el strip se cazaría de verdad."""
    from core.scheduler import sin_prefijo, con_prefijo

    assert sin_prefijo("MemoviPro_rutina") == "rutina"
    assert sin_prefijo("rutina") == "rutina"  # idempotente
    assert con_prefijo("rutina") == "MemoviPro_rutina"
    assert con_prefijo("MemoviPro_rutina") == "MemoviPro_rutina"  # idempotente
    # round-trip
    assert sin_prefijo(con_prefijo("x")) == "x"


def test_c1_panel_usa_sin_prefijo_real():
    """El panel debe delegar en la función compartida, no reimplementar el
    strip inline (evita que se desincronicen)."""
    src = (ROOT / "ui" / "schedule_panel.py").read_text(encoding="utf-8")
    assert "sin_prefijo" in src
    fn = src.split("def _nombre_seleccionado")[1].split("def ")[0]
    assert "sin_prefijo(item.text())" in fn


def test_c1_metadata_roundtrip_con_nombre_desnudo(tmp_path):
    """Guardar metadata con el nombre desnudo y cargarla con ese mismo
    nombre debe funcionar (era el bug: se guardaba desnudo, se cargaba
    con prefijo → None)."""
    from core.scheduler_metadata import TaskMetadata

    meta = TaskMetadata(tmp_path)
    meta.save("rutina", {"modo": "replay", "descripcion": "diaria"})
    cargado = meta.load("rutina")
    assert cargado is not None
    assert cargado["descripcion"] == "diaria"
    # Con el prefijo (bug antiguo) NO se encontraría:
    assert meta.load("MemoviPro_rutina") is None


# ==================== C3: rutas de la app real ====================

def test_c3_run_panel_config_desde_data_dir():
    """run_panel debe derivar config.json de data_dir.parent, no de __file__."""
    src = (ROOT / "ui" / "run_panel.py").read_text(encoding="utf-8")
    assert "self.config_path = self.data_dir.parent / \"config.json\"" in src
    # _cargar_smtp ya no usa un CONFIG_PATH basado en __file__.
    assert "Path(__file__).resolve().parents[1] / \"config.json\"" not in src
    assert "_cargar_smtp(self.config_path)" in src


def test_c3_step_editor_data_dir_desde_macros_dir():
    src = (ROOT / "ui" / "step_editor.py").read_text(encoding="utf-8")
    assert "self.data_dir = self.macros_dir.parent / \"data\"" in src
    # Ya no debe quedar el patrón Path(__file__).parents[1] para data/
    assert "root_app = Path(__file__).resolve().parents[1]" not in src


# ==================== C4/C5: pánico y cierre (conductual sin Qt) ====================
# MainWindow no se puede instanciar sin PyQt6 (no disponible en el entorno
# de test), pero _abortar_todo es lógica pura sobre los 3 paneles: la
# ejercitamos con un objeto ligero que expone los mismos atributos.

class _FakePanel:
    def __init__(self, corriendo=False):
        self._aborted = False
        self._thread = _FakeThread(corriendo)

    def abort(self):
        self._aborted = True


class _FakeThread:
    def __init__(self, corriendo):
        self._corriendo = corriendo
        self.waited = False

    def isRunning(self):
        return self._corriendo

    def wait(self, ms):
        self.waited = True
        self._corriendo = False


def _bind_metodos(run_ok, replay_ok, pipe_ok):
    """Reusa los métodos REALES de MainWindow (los que NO llaman super())
    sobre un objeto ligero, sin instanciar QMainWindow. Requiere PyQt6
    (importa la clase) → skip donde no esté; corre de verdad en Windows.

    Nota: NO bindeamos closeEvent porque su `super().closeEvent()` exige
    que el objeto sea instancia de QMainWindow. Toda la lógica abortable
    vive en `_hilos_en_marcha`/`_detener_hilos`, que sí son testeables."""
    import pytest
    pytest.importorskip("PyQt6.QtWidgets")
    from ui.main_window import MainWindow

    obj = type("_M", (), {})()
    obj.run_panel = _FakePanel(run_ok)
    obj.replay_panel = _FakePanel(replay_ok)
    obj.pipeline_panel = _FakePanel(pipe_ok)
    for m in ("_abortar_todo", "_hilos_en_marcha", "_detener_hilos"):
        setattr(obj, m, getattr(MainWindow, m).__get__(obj))
    return obj


def test_c4_abortar_todo_aborta_los_tres_paneles():
    obj = _bind_metodos(False, False, False)
    obj._abortar_todo()
    assert obj.run_panel._aborted
    assert obj.replay_panel._aborted
    assert obj.pipeline_panel._aborted  # antes NO se abortaba la cadena


def test_c4_panic_delega_en_abortar_todo():
    src = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    panic_fn = src.split("def _panic")[1].split("def ")[0]
    assert "_abortar_todo" in panic_fn


def test_c5_hilos_en_marcha_detecta_solo_los_corriendo():
    obj = _bind_metodos(run_ok=True, replay_ok=False, pipe_ok=True)
    hilos = obj._hilos_en_marcha()
    assert len(hilos) == 2  # run y pipeline corriendo, replay no


def test_c5_detener_hilos_aborta_y_espera():
    """La parte que importa de closeEvent: aborta todo y espera a los
    hilos en marcha (antes cerrar dejaba el worker automatizando)."""
    obj = _bind_metodos(run_ok=True, replay_ok=False, pipe_ok=False)
    hilos = obj._hilos_en_marcha()
    obj._detener_hilos(hilos)
    assert obj.run_panel._aborted
    assert obj.replay_panel._aborted
    assert obj.pipeline_panel._aborted
    assert obj.run_panel._thread.waited      # esperó al hilo que corría


def test_c5_closeevent_estructura():
    """closeEvent debe: mirar hilos, preguntar, respetar el 'No'
    (event.ignore) y delegar en _detener_hilos + super()."""
    src = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    close_fn = src.split("def closeEvent")[1].split("\n    def ")[0]
    assert "_hilos_en_marcha" in close_fn
    assert "event.ignore()" in close_fn
    assert "_detener_hilos" in close_fn
    assert "super().closeEvent" in close_fn
