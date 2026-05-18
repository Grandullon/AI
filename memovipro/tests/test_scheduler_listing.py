"""Tests del listing robusto de tareas en Windows.

Cubre que listar_tareas funcione en cualquier locale:
  - CSV con coma (Windows EN)
  - CSV con punto y coma (Windows ES, FR, DE...)
  - Fallback a /FO LIST cuando CSV no devuelve nada útil
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import scheduler as sched
from core.scheduler import _parse_csv_tasks, _parse_list_tasks


def test_parse_csv_coma():
    csv_en = (
        '"\\MemoviPro_4","08/05/2026 12:57:00","Listo","Interactiva","","0","USR","ejec.exe","","" \n'
    )
    out = _parse_csv_tasks(csv_en, ",")
    assert len(out) == 1
    assert out[0].nombre == "MemoviPro_4"
    assert out[0].proximo == "08/05/2026 12:57:00"


def test_parse_csv_punto_y_coma():
    csv_es = (
        '"\\MemoviPro_4";"08/05/2026 12:57:00";"Listo";"Interactiva";"";"0";"USR";"ejec.exe";"";"" \n'
        '"\\MemoviPro_descarga";"09/05/2026 07:45:00";"Listo";"Interactiva";"";"0";"USR";"x.exe";"";"" \n'
    )
    out = _parse_csv_tasks(csv_es, ";")
    nombres = {t.nombre for t in out}
    assert nombres == {"MemoviPro_4", "MemoviPro_descarga"}


def test_parse_csv_filtra_no_memovipro():
    csv_mix = (
        '"\\MemoviPro_4";"";"Listo";"";"";"";"";"";"";"" \n'
        '"\\OtraTarea";"";"Listo";"";"";"";"";"";"";"" \n'
        '"\\MemoviPro_otra";"";"Listo";"";"";"";"";"";"";"" \n'
    )
    out = _parse_csv_tasks(csv_mix, ";")
    nombres = {t.nombre for t in out}
    assert nombres == {"MemoviPro_4", "MemoviPro_otra"}


def test_parse_list_en():
    list_en = """
HostName: WIN-X
TaskName: \\MemoviPro_diaria
Next Run Time: 09/05/2026 07:45:00
Status: Ready
Logon Mode: Interactive only
Task To Run: C:\\memovipro-run.exe --replay descarga

HostName: WIN-X
TaskName: \\OtraTarea
Next Run Time: ...
Status: Ready
"""
    out = _parse_list_tasks(list_en)
    assert len(out) == 1
    assert out[0].nombre == "MemoviPro_diaria"


def test_parse_list_es():
    list_es = """
HostName: PC-USR
Nombre de tarea: \\MemoviPro_test
Próxima ejecución: 10/05/2026 08:00:00
Estado: Listo
Tarea para ejecutar: C:\\memovipro-run.exe --replay foo
"""
    out = _parse_list_tasks(list_es)
    assert len(out) == 1
    assert out[0].nombre == "MemoviPro_test"
    assert "10/05/2026" in out[0].proximo


def test_listar_tareas_usa_lista_mas_larga(monkeypatch):
    """Si CSV con `,` da 0 y con `;` da 2, debe devolver la de `;`."""
    csv_with_semi = (
        '"\\MemoviPro_a";"";"Listo";"";"";"";"";"";"";"" \n'
        '"\\MemoviPro_b";"";"Listo";"";"";"";"";"";"";"" \n'
    )

    class _Res:
        returncode = 0
        stdout = csv_with_semi
        stderr = ""

    monkeypatch.setattr(sched, "_es_windows", lambda: True)
    calls = {"n": 0}
    def fake_correr(cmd):
        calls["n"] += 1
        return _Res()
    monkeypatch.setattr(sched, "_correr", fake_correr)

    out = sched.listar_tareas()
    assert {t.nombre for t in out} == {"MemoviPro_a", "MemoviPro_b"}
    assert calls["n"] == 1   # con CSV ya tuvo suficiente


def test_listar_tareas_fallback_list(monkeypatch):
    """Si CSV no devuelve tareas, debe probar formato LIST."""
    class _ResCSV:
        returncode = 0
        stdout = "datos basura sin tareas memovipro"
        stderr = ""

    class _ResList:
        returncode = 0
        stdout = (
            "TaskName: \\MemoviPro_x\n"
            "Status: Ready\n"
            "Task To Run: x.exe\n"
        )
        stderr = ""

    monkeypatch.setattr(sched, "_es_windows", lambda: True)
    respuestas = iter([_ResCSV(), _ResList()])
    monkeypatch.setattr(sched, "_correr", lambda cmd: next(respuestas))

    out = sched.listar_tareas()
    assert len(out) == 1
    assert out[0].nombre == "MemoviPro_x"
