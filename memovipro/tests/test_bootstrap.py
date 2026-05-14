from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.bootstrap import ensure_runtime_folders


def test_crea_carpetas_si_no_existen(tmp_path):
    info = ensure_runtime_folders(tmp_path)
    for sub in ("data", "data/screenshots", "logs", "macros"):
        assert (tmp_path / sub).exists()
        assert (tmp_path / sub).is_dir()
    assert info["root"] == str(tmp_path)


def test_es_idempotente(tmp_path):
    ensure_runtime_folders(tmp_path)
    info2 = ensure_runtime_folders(tmp_path)
    assert info2["carpetas_creadas"] == []


def test_copia_macros_desde_bundle(tmp_path, monkeypatch):
    # Simular bundle de PyInstaller
    bundle = tmp_path / "_MEI"
    bundle_macros = bundle / "macros"
    bundle_macros.mkdir(parents=True)
    (bundle_macros / "ejemplo.yaml").write_text("nombre: ejemplo\npasos: []\n", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

    raiz = tmp_path / "instalado"
    info = ensure_runtime_folders(raiz)

    assert (raiz / "macros" / "ejemplo.yaml").exists()
    assert info["macros_copiadas"] >= 1


def test_no_pisa_macros_si_ya_hay(tmp_path, monkeypatch):
    bundle = tmp_path / "_MEI"
    (bundle / "macros").mkdir(parents=True)
    (bundle / "macros" / "ejemplo.yaml").write_text("v: bundle\n", encoding="utf-8")

    raiz = tmp_path / "instalado"
    (raiz / "macros").mkdir(parents=True)
    (raiz / "macros" / "ya_existente.yaml").write_text("v: usuario\n", encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

    info = ensure_runtime_folders(raiz)

    assert (raiz / "macros" / "ya_existente.yaml").exists()
    assert not (raiz / "macros" / "ejemplo.yaml").exists()
    assert info["macros_copiadas"] == 0


def test_copia_config_si_falta(tmp_path, monkeypatch):
    bundle = tmp_path / "_MEI"
    bundle.mkdir()
    (bundle / "config.json").write_text('{"key": 1}', encoding="utf-8")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

    raiz = tmp_path / "instalado"
    info = ensure_runtime_folders(raiz)

    assert (raiz / "config.json").exists()
    assert info["config_copiado"] is True
