"""Tests para escape_send_keys y file_lock."""
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.keyboard_utils import escape_send_keys
from core.file_lock import file_lock


# ===== escape_send_keys =====

def test_escape_texto_normal_sin_cambios():
    assert escape_send_keys("12345678A") == "12345678A"
    assert escape_send_keys("hola mundo") == "hola mundo"


def test_escape_mas():
    assert escape_send_keys("P+ss") == "P{+}ss"


def test_escape_porcentaje():
    assert escape_send_keys("50%") == "50{%}"


def test_escape_parentesis():
    assert escape_send_keys("Apellido (2)") == "Apellido {(}2{)}"


def test_escape_llaves():
    assert escape_send_keys("a{b}c") == "a{{}b{}}c"


def test_escape_acento_circunflejo_y_tilde():
    assert escape_send_keys("a^b~c") == "a{^}b{~}c"


def test_escape_password_compleja():
    # Una contraseña con varios símbolos especiales
    pw = "Cl4ve+Seg%ra(2026)"
    out = escape_send_keys(pw)
    assert "{+}" in out
    assert "{%}" in out
    assert "{(}" in out
    assert "{)}" in out
    # Caracteres normales intactos
    assert out.startswith("Cl4ve")


def test_escape_vacio():
    assert escape_send_keys("") == ""


# ===== file_lock =====

def test_file_lock_crea_y_borra_el_lock(tmp_path):
    target = tmp_path / "datos.xlsx"
    lock = Path(str(target) + ".lock")
    assert not lock.exists()
    with file_lock(target):
        assert lock.exists()  # dentro del with, el lock existe
    assert not lock.exists()  # al salir, se borra


def test_file_lock_serializa_dos_hilos(tmp_path):
    """Dos hilos que adquieren el mismo lock no se solapan."""
    target = tmp_path / "recurso"
    orden = []

    def trabajo(nombre):
        with file_lock(target, timeout=5.0):
            orden.append(f"{nombre}-inicio")
            time.sleep(0.2)
            orden.append(f"{nombre}-fin")

    t1 = threading.Thread(target=trabajo, args=("A",))
    t2 = threading.Thread(target=trabajo, args=("B",))
    t1.start()
    time.sleep(0.05)  # asegurar que A entra primero
    t2.start()
    t1.join()
    t2.join()

    # Las secciones no deben entrelazarse: inicio-fin de uno antes del otro
    assert orden in (
        ["A-inicio", "A-fin", "B-inicio", "B-fin"],
        ["B-inicio", "B-fin", "A-inicio", "A-fin"],
    )


def test_file_lock_rompe_lock_stale(tmp_path):
    """Un lock más viejo que stale_after_s se rompe y se puede adquirir."""
    target = tmp_path / "recurso2"
    lock = Path(str(target) + ".lock")
    # Crear un lock "viejo" a mano
    lock.write_text("99999")
    # Envejecerlo: poner su mtime 200s en el pasado
    import os
    viejo = time.time() - 200
    os.utime(lock, (viejo, viejo))

    adquirido = {"ok": False}
    with file_lock(target, timeout=2.0, stale_after_s=120.0):
        adquirido["ok"] = True
    assert adquirido["ok"] is True


def test_file_lock_timeout_continua_sin_bloquear(tmp_path):
    """Si el lock está tomado y no es stale, tras timeout continúa
    igualmente (no queremos colgar la app eternamente)."""
    target = tmp_path / "recurso3"
    lock = Path(str(target) + ".lock")
    lock.write_text("12345")  # lock reciente, no stale

    inicio = time.time()
    entrado = {"ok": False}
    with file_lock(target, timeout=0.5, stale_after_s=120.0):
        entrado["ok"] = True
    duracion = time.time() - inicio
    assert entrado["ok"] is True
    assert duracion >= 0.5  # esperó el timeout
    assert duracion < 3.0   # pero no eternamente
