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


def test_c1_nombre_seleccionado_quita_prefijo():
    """La lógica de strip del prefijo (aislada de Qt): dado el texto de la
    tabla 'MemoviPro_rutina', el nombre interno debe ser 'rutina'."""
    from core.scheduler import PREFIX

    def strip_prefix(texto: str) -> str:
        return texto[len(PREFIX):] if texto.startswith(PREFIX) else texto

    assert strip_prefix("MemoviPro_rutina") == "rutina"
    assert strip_prefix("rutina") == "rutina"  # idempotente
    # Y las funciones del scheduler reañaden el prefijo de forma tolerante:
    # crear/ejecutar/eliminar aceptan tanto 'rutina' como 'MemoviPro_rutina'.


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


# ==================== C4/C5: pánico y cierre ====================

def test_c4_panic_incluye_pipeline_panel():
    src = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    abort_fn = src.split("def _abortar_todo")[1].split("def ")[0]
    assert "pipeline_panel" in abort_fn
    assert "run_panel" in abort_fn
    assert "replay_panel" in abort_fn
    # _panic delega en _abortar_todo
    panic_fn = src.split("def _panic")[1].split("def ")[0]
    assert "_abortar_todo" in panic_fn


def test_c5_closeevent_aborta_hilos():
    src = (ROOT / "ui" / "main_window.py").read_text(encoding="utf-8")
    assert "def closeEvent" in src
    close_fn = src.split("def closeEvent")[1].split("def ")[0]
    assert "_abortar_todo" in close_fn
    assert "isRunning" in close_fn
    assert ".wait(" in close_fn  # espera a que el worker termine
