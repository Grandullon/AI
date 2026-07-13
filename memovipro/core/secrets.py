"""Gestión de credenciales cifradas usando el almacén nativo del SO.

Wrapper sobre `keyring`, que en Windows usa Credential Manager (DPAPI),
en macOS usa Keychain y en Linux gnome-keyring/KWallet. El YAML de la
macro NUNCA contiene contraseñas, solo placeholders `{SECRET:nombre}`
que se resuelven en runtime.

Para listar/borrar secretos mantenemos un índice manual en
`data/secrets_index.json` porque `keyring` no expone listado en todas
las plataformas.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from threading import Lock

try:
    import keyring
    _HAS_KEYRING = True
except Exception:
    _HAS_KEYRING = False
    keyring = None  # placeholder para tests (monkeypatch) y para que el
    #                 nombre exista aunque el paquete no esté instalado

SERVICE_NAME = "MemoviPro"

# El índice está junto al .exe / al app.py para que sea fácil de encontrar.
def _default_index_path() -> Path:
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
        root = Path(__file__).resolve().parents[1]
    return root / "data" / "secrets_index.json"


_index_lock = Lock()


def _read_index(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("nombres", []))
    except Exception:
        return []


def _write_index(path: Path, nombres: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({"nombres": sorted(set(nombres))}, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def is_available() -> bool:
    """¿Está disponible un backend de keyring funcional?"""
    if not _HAS_KEYRING:
        return False
    try:
        backend = keyring.get_keyring()
        # Algunos backends "fail" devuelven una clase placeholder
        return "fail" not in backend.__class__.__name__.lower()
    except Exception:
        return False


def get_secret(nombre: str) -> str | None:
    """Devuelve el valor del secreto o None si no existe."""
    if not _HAS_KEYRING:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, nombre)
    except Exception:
        return None


def set_secret(nombre: str, valor: str, index_path: Path | None = None) -> bool:
    """Guarda (o sobrescribe) un secreto y lo añade al índice."""
    if not _HAS_KEYRING:
        return False
    try:
        keyring.set_password(SERVICE_NAME, nombre, valor)
    except Exception:
        return False
    path = index_path or _default_index_path()
    with _index_lock:
        nombres = _read_index(path)
        if nombre not in nombres:
            nombres.append(nombre)
            _write_index(path, nombres)
    return True


def delete_secret(nombre: str, index_path: Path | None = None) -> bool:
    """Elimina un secreto del almacén y del índice."""
    ok = False
    if _HAS_KEYRING:
        try:
            keyring.delete_password(SERVICE_NAME, nombre)
            ok = True
        except Exception:
            pass
    path = index_path or _default_index_path()
    with _index_lock:
        nombres = _read_index(path)
        if nombre in nombres:
            nombres.remove(nombre)
            _write_index(path, nombres)
    return ok


def list_secrets(index_path: Path | None = None) -> list[str]:
    """Devuelve la lista de nombres de secretos conocidos (índice manual)."""
    path = index_path or _default_index_path()
    with _index_lock:
        return _read_index(path)
