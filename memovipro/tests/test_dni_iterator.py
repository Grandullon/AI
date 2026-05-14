from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.dni_iterator import Checkpoint, cargar_dnis


def test_cargar_dnis_xlsx(tmp_path):
    df = pd.DataFrame({"DNI": ["12345678A", "87654321B", ""], "Nombre": ["a", "b", "c"]})
    path = tmp_path / "dnis.xlsx"
    df.to_excel(path, index=False)
    out = cargar_dnis(path)
    assert len(out) == 2
    assert out[0]["DNI"] == "12345678A"
    assert out[0]["Nombre"] == "a"


def test_cargar_dnis_csv_normaliza(tmp_path):
    path = tmp_path / "dnis.csv"
    path.write_text("DNI\n  12345678a  \n99999999z\n", encoding="utf-8")
    out = cargar_dnis(path)
    assert [r["DNI"] for r in out] == ["12345678A", "99999999Z"]


def test_checkpoint_persiste(tmp_path):
    cp = Checkpoint(macro="mTest", path_dir=tmp_path, fecha="20260514")
    cp.marcar_ok("A")
    cp.marcar_ko("B")
    cp.marcar_ok("C")

    cp2 = Checkpoint(macro="mTest", path_dir=tmp_path, fecha="20260514")
    assert cp2.hechos() == {"A", "C"}
    assert cp2.fallidos() == {"B"}

    pendientes = cp2.pendientes([{"DNI": "A"}, {"DNI": "B"}, {"DNI": "D"}])
    assert [r["DNI"] for r in pendientes] == ["B", "D"]


def test_checkpoint_ok_limpia_ko(tmp_path):
    cp = Checkpoint(macro="m", path_dir=tmp_path, fecha="20260514")
    cp.marcar_ko("X")
    cp.marcar_ok("X")
    assert cp.fallidos() == set()
    assert cp.hechos() == {"X"}
