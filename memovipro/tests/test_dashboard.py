"""Tests de la agregación del dashboard (core.dashboard)."""
from datetime import datetime, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.dashboard import agregar_incidencias
from core.excel_logger import ExcelLogger, Incidencia


def _crear_excel(data_dir: Path, fecha: datetime, filas: list[Incidencia]):
    """Crea un incidencias_YYYYMMDD.xlsx con las filas dadas."""
    nombre = f"incidencias_{fecha.strftime('%Y%m%d')}.xlsx"
    logger = ExcelLogger(data_dir / nombre)
    for inc in filas:
        logger.append(inc)


def test_dashboard_vacio(tmp_path):
    stats = agregar_incidencias(tmp_path, dias=30)
    assert stats.total == 0
    assert stats.por_macro == []


def test_dashboard_agrega_ok_y_ko(tmp_path):
    hoy = datetime.now()
    _crear_excel(tmp_path, hoy, [
        Incidencia(dni="A", macro="pa", paso_idx=-1, paso_tipo="", tipo_error="", estado="OK"),
        Incidencia(dni="B", macro="pa", paso_idx=-1, paso_tipo="", tipo_error="", estado="OK"),
        Incidencia(dni="C", macro="pa", paso_idx=3, paso_tipo="click", tipo_error="POPUP",
                   titulo_popup="Error X", estado="ERROR"),
    ])
    stats = agregar_incidencias(tmp_path, dias=30)
    assert stats.total == 3
    assert stats.total_ok == 2
    assert stats.total_ko == 1
    assert len(stats.por_macro) == 1
    ms = stats.por_macro[0]
    assert ms.macro == "pa"
    assert ms.ok == 2 and ms.ko == 1
    assert abs(ms.tasa_exito - 66.666) < 0.1


def test_dashboard_top_errores(tmp_path):
    hoy = datetime.now()
    _crear_excel(tmp_path, hoy, [
        Incidencia(dni="A", macro="m", paso_idx=1, paso_tipo="x", tipo_error="POPUP",
                   titulo_popup="DNI no encontrado", estado="ERROR"),
        Incidencia(dni="B", macro="m", paso_idx=1, paso_tipo="x", tipo_error="POPUP",
                   titulo_popup="DNI no encontrado", estado="ERROR"),
        Incidencia(dni="C", macro="m", paso_idx=2, paso_tipo="y", tipo_error="POPUP",
                   titulo_popup="Sin permisos", estado="ERROR"),
    ])
    stats = agregar_incidencias(tmp_path, dias=30)
    # "DNI no encontrado" debe ser el error más frecuente (2 veces)
    assert stats.top_errores[0] == ("DNI no encontrado", 2)
    assert ("Sin permisos", 1) in stats.top_errores


def test_dashboard_macros_ordenadas_por_fragilidad(tmp_path):
    hoy = datetime.now()
    _crear_excel(tmp_path, hoy, [
        # macro 'buena': 3 OK, 0 KO → 100%
        Incidencia(dni="1", macro="buena", paso_idx=-1, paso_tipo="", tipo_error="", estado="OK"),
        Incidencia(dni="2", macro="buena", paso_idx=-1, paso_tipo="", tipo_error="", estado="OK"),
        Incidencia(dni="3", macro="buena", paso_idx=-1, paso_tipo="", tipo_error="", estado="OK"),
        # macro 'fragil': 1 OK, 3 KO → 25%
        Incidencia(dni="4", macro="fragil", paso_idx=-1, paso_tipo="", tipo_error="", estado="OK"),
        Incidencia(dni="5", macro="fragil", paso_idx=1, paso_tipo="x", tipo_error="POPUP", estado="ERROR"),
        Incidencia(dni="6", macro="fragil", paso_idx=1, paso_tipo="x", tipo_error="POPUP", estado="ERROR"),
        Incidencia(dni="7", macro="fragil", paso_idx=1, paso_tipo="x", tipo_error="POPUP", estado="ERROR"),
    ])
    stats = agregar_incidencias(tmp_path, dias=30)
    # La frágil (peor tasa) debe ir primera
    assert stats.por_macro[0].macro == "fragil"
    assert stats.por_macro[-1].macro == "buena"


def test_dashboard_filtra_por_dias(tmp_path):
    hoy = datetime.now()
    viejo = hoy - timedelta(days=60)
    _crear_excel(tmp_path, hoy, [
        Incidencia(dni="A", macro="reciente", paso_idx=-1, paso_tipo="", tipo_error="", estado="OK"),
    ])
    _crear_excel(tmp_path, viejo, [
        Incidencia(dni="Z", macro="antiguo", paso_idx=-1, paso_tipo="", tipo_error="", estado="OK"),
    ])
    # Con 30 días, el de hace 60 días NO debe contar
    stats = agregar_incidencias(tmp_path, dias=30)
    nombres = {m.macro for m in stats.por_macro}
    assert "reciente" in nombres
    assert "antiguo" not in nombres
    # Con 90 días, ambos
    stats90 = agregar_incidencias(tmp_path, dias=90)
    nombres90 = {m.macro for m in stats90.por_macro}
    assert "reciente" in nombres90
    assert "antiguo" in nombres90
