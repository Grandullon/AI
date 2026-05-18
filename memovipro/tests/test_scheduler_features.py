"""Tests para las nuevas funcionalidades del scheduler:
- ejecutar_ahora()
- habilitar_tarea()
- validar_args()
- TareaProgramada.ok_ultima_ejecucion
- TaskMetadata
- Parser CSV extendido con ultima_ejecucion / ultimo_resultado
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import scheduler as sched
from core.scheduler import (
    TareaProgramada,
    _parse_csv_tasks,
    ejecutar_ahora,
    habilitar_tarea,
    validar_args,
)
from core.scheduler_metadata import TaskMetadata


# ===== TareaProgramada.ok_ultima_ejecucion =====

def test_ok_ultima_ejecucion_string_vacio():
    t = TareaProgramada(nombre="x", proximo="", estado="", ultimo_resultado="")
    assert t.ok_ultima_ejecucion is None


def test_ok_ultima_ejecucion_cero_decimal():
    t = TareaProgramada(nombre="x", proximo="", estado="", ultimo_resultado="0")
    assert t.ok_ultima_ejecucion is True


def test_ok_ultima_ejecucion_cero_hex():
    t = TareaProgramada(nombre="x", proximo="", estado="", ultimo_resultado="0x0")
    assert t.ok_ultima_ejecucion is True


def test_ok_ultima_ejecucion_error():
    t = TareaProgramada(nombre="x", proximo="", estado="", ultimo_resultado="2")
    assert t.ok_ultima_ejecucion is False


def test_ok_ultima_ejecucion_no_parseable():
    t = TareaProgramada(nombre="x", proximo="", estado="", ultimo_resultado="N/A")
    assert t.ok_ultima_ejecucion is None


# ===== _parse_csv_tasks ahora incluye última/resultado =====

def test_parse_csv_extrae_ultima_ejecucion_y_resultado():
    csv_en = (
        '"HOST","\\MemoviPro_x","08/05/2026 12:57:00","Listo","Interactiva",'
        '"08/05/2026 07:45:00","0","USR","C:\\run.exe --replay x","","" \n'
    )
    out = _parse_csv_tasks(csv_en, ",")
    assert len(out) == 1
    t = out[0]
    assert t.nombre == "MemoviPro_x"
    assert t.proximo == "08/05/2026 12:57:00"
    assert t.estado == "Listo"
    assert t.ultima_ejecucion == "08/05/2026 07:45:00"
    assert t.ultimo_resultado == "0"
    assert t.ok_ultima_ejecucion is True


# ===== ejecutar_ahora / habilitar_tarea =====

def test_ejecutar_ahora_fuera_de_windows(monkeypatch):
    monkeypatch.setattr(sched, "_es_windows", lambda: False)
    ok, msg = ejecutar_ahora("X")
    assert ok is False
    assert "Windows" in msg


def test_ejecutar_ahora_usa_schtasks_run(monkeypatch):
    calls = {"cmd": None}

    class _Res:
        returncode = 0
        stdout = "Realizado correctamente"
        stderr = ""

    def fake_correr(cmd):
        calls["cmd"] = cmd
        return _Res()

    monkeypatch.setattr(sched, "_es_windows", lambda: True)
    monkeypatch.setattr(sched, "_correr", fake_correr)

    ok, msg = ejecutar_ahora("descarga_diaria")
    assert ok is True
    assert "MemoviPro_descarga_diaria" in msg
    assert calls["cmd"][:2] == ["schtasks", "/Run"]
    assert "MemoviPro_descarga_diaria" in calls["cmd"]


def test_habilitar_tarea_usa_change_enable(monkeypatch):
    calls = {"cmd": None}

    class _Res:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_correr(cmd):
        calls["cmd"] = cmd
        return _Res()

    monkeypatch.setattr(sched, "_es_windows", lambda: True)
    monkeypatch.setattr(sched, "_correr", fake_correr)

    assert habilitar_tarea("foo", True) is True
    assert "/ENABLE" in calls["cmd"]


def test_habilitar_tarea_usa_disable(monkeypatch):
    calls = {"cmd": None}

    class _Res:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(sched, "_es_windows", lambda: True)
    monkeypatch.setattr(sched, "_correr", lambda cmd: (calls.__setitem__("cmd", cmd), _Res())[1])

    assert habilitar_tarea("foo", False) is True
    assert "/DISABLE" in calls["cmd"]


# ===== validar_args =====

def test_validar_args_macro_inexistente(tmp_path):
    macros = tmp_path / "macros"
    macros.mkdir()
    pipelines = tmp_path / "pipelines"
    pipelines.mkdir()
    err = validar_args(["--replay", "no_existe", "--veces", "1"], macros, pipelines)
    assert any("no_existe" in e for e in err)


def test_validar_args_macro_existente(tmp_path):
    macros = tmp_path / "macros"
    macros.mkdir()
    (macros / "foo.yaml").write_text("nombre: foo\npasos: []\n", encoding="utf-8")
    pipelines = tmp_path / "pipelines"
    pipelines.mkdir()
    err = validar_args(["--replay", "foo"], macros, pipelines)
    assert err == []


def test_validar_args_pipeline_existente(tmp_path):
    macros = tmp_path / "macros"
    macros.mkdir()
    pipelines = tmp_path / "pipelines"
    pipelines.mkdir()
    (pipelines / "diaria.yaml").write_text("nombre: diaria\npasos: []\n", encoding="utf-8")
    err = validar_args(["--pipeline", "diaria"], macros, pipelines)
    assert err == []


def test_validar_args_excel_inexistente(tmp_path):
    macros = tmp_path / "macros"
    macros.mkdir()
    (macros / "foo.yaml").write_text("x", encoding="utf-8")
    pipelines = tmp_path / "pipelines"
    pipelines.mkdir()
    err = validar_args(
        ["--macro", "foo", "--excel", str(tmp_path / "no_existe.xlsx")],
        macros, pipelines,
    )
    assert any("no_existe.xlsx" in e for e in err)


def test_validar_args_acepta_ruta_absoluta(tmp_path):
    macros = tmp_path / "macros"
    macros.mkdir()
    f = tmp_path / "abs.yaml"
    f.write_text("x", encoding="utf-8")
    pipelines = tmp_path / "pipelines"
    pipelines.mkdir()
    err = validar_args(["--replay", str(f)], macros, pipelines)
    assert err == []


# ===== TaskMetadata =====

def test_task_metadata_save_y_load(tmp_path):
    meta = TaskMetadata(tmp_path)
    data = {"modo": "replay", "macro": "foo", "veces": 5, "velocidad": 1.5}
    meta.save("descarga_diaria", data)

    cargado = meta.load("descarga_diaria")
    assert cargado == data


def test_task_metadata_load_inexistente_devuelve_none(tmp_path):
    meta = TaskMetadata(tmp_path)
    assert meta.load("no_existe") is None


def test_task_metadata_delete(tmp_path):
    meta = TaskMetadata(tmp_path)
    meta.save("x", {"a": 1})
    assert meta.load("x") == {"a": 1}
    meta.delete("x")
    assert meta.load("x") is None


def test_task_metadata_sanitiza_nombres(tmp_path):
    """Caracteres raros en el nombre no rompen el filesystem."""
    meta = TaskMetadata(tmp_path)
    meta.save("descarga / IT \\ 2026", {"x": 1})
    # Debe poder cargarlo con el mismo nombre
    assert meta.load("descarga / IT \\ 2026") == {"x": 1}


def test_task_metadata_all_names(tmp_path):
    meta = TaskMetadata(tmp_path)
    meta.save("a", {})
    meta.save("b", {})
    meta.save("c", {})
    assert set(meta.all_names()) == {"a", "b", "c"}
