"""Tests del nombre de macro al cargar/guardar en la pestaña Macros.

Bug reportado: al cargar un YAML y guardar, cambiaba el nombre o ponía el
anterior. Causa: el grabador guarda todo con nombre interno "grabacion";
el editor mostraba ese nombre interno (no el del archivo) y guardaba en
"grabacion.yaml", pisando varias macros entre sí.

Fix: el nombre lo manda el ARCHIVO (Path(path).stem). Aquí se cubre la
función pura de sanitización y, por inspección, la lógica del editor.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.step_model import Macro, Step, StepType, nombre_archivo_macro


def test_nombre_archivo_sanitiza_y_añade_extension():
    assert nombre_archivo_macro("Rutina Diaria") == "Rutina_Diaria.yaml"
    assert nombre_archivo_macro("informe/2026") == "informe_2026.yaml"
    assert nombre_archivo_macro("a b:c*d") == "a_b_c_d.yaml"


def test_nombre_archivo_respeta_extension_existente():
    assert nombre_archivo_macro("informe.yml") == "informe.yml"
    assert nombre_archivo_macro("informe.yaml") == "informe.yaml"


def test_nombre_archivo_vacio():
    assert nombre_archivo_macro("") == "macro_sin_nombre.yaml"
    assert nombre_archivo_macro("   ") == "macro_sin_nombre.yaml"


def test_roundtrip_carga_guarda_mismo_fichero(tmp_path):
    """Simula el flujo real: una macro grabada (nombre interno 'grabacion')
    se guarda como PRUEBAIT.yaml; al 'cargarla', el nombre debe pasar a ser
    el del ARCHIVO, de modo que al re-guardar vuelva al MISMO fichero."""
    # Macro tal como la deja el grabador: nombre interno genérico.
    m = Macro(nombre="grabacion", pasos=[Step(tipo=StepType.SLEEP, valor="1")])
    archivo = tmp_path / "PRUEBAIT.yaml"
    m.save(archivo)

    # "Cargar" en el editor = Macro.load + tomar el nombre del archivo.
    cargada = Macro.load(archivo)
    assert cargada.nombre == "grabacion"          # lo que hay dentro del YAML
    cargada.nombre = archivo.stem                  # lo que hace ahora _load
    assert cargada.nombre == "PRUEBAIT"

    # "Guardar" = derivar el fichero del nombre → debe ser el MISMO.
    destino = tmp_path / nombre_archivo_macro(cargada.nombre)
    assert destino == archivo                       # no crea grabacion.yaml


def test_dos_macros_grabadas_no_colapsan(tmp_path):
    """Dos macros distintas, ambas con nombre interno 'grabacion', guardadas
    con nombres de archivo distintos, NO deben colapsar al re-guardarse."""
    for fname in ("PRUEBAIT.yaml", "huelga.yaml"):
        m = Macro(nombre="grabacion", pasos=[Step(tipo=StepType.SLEEP, valor="0")])
        m.save(tmp_path / fname)

    destinos = set()
    for fname in ("PRUEBAIT.yaml", "huelga.yaml"):
        cargada = Macro.load(tmp_path / fname)
        cargada.nombre = Path(tmp_path / fname).stem   # _load toma el nombre del archivo
        destinos.add(nombre_archivo_macro(cargada.nombre))
    # Dos ficheros distintos, no uno solo ('grabacion.yaml').
    assert destinos == {"PRUEBAIT.yaml", "huelga.yaml"}


def test_editor_load_usa_nombre_del_archivo():
    """Inspección: _load fija macro.nombre = Path(path).stem y _save usa
    nombre_archivo_macro."""
    src = (ROOT / "ui" / "step_editor.py").read_text(encoding="utf-8")
    load_fn = src.split("def _load(self)")[1].split("def _save")[0]
    assert "self.macro.nombre = Path(path).stem" in load_fn
    assert "self._loaded_path = Path(path)" in load_fn
    save_fn = src.split("def _save(self)")[1].split("def _launch_recorder")[0]
    assert "nombre_archivo_macro" in save_fn
