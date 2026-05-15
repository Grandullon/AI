"""Tests del módulo de secretos.

Usamos un keyring fake en memoria para no tocar el almacén real del SO
durante los tests.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _FakeKeyring:
    """Backend en memoria para tests."""
    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service, name):
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        if (service, name) in self.store:
            del self.store[(service, name)]
        else:
            raise KeyError(name)

    def get_keyring(self):
        return self


def test_set_y_get_y_delete(monkeypatch, tmp_path):
    fake = _FakeKeyring()
    import core.secrets as sec
    monkeypatch.setattr(sec, "_HAS_KEYRING", True)
    monkeypatch.setattr(sec, "keyring", fake)

    idx = tmp_path / "secrets_index.json"
    assert sec.list_secrets(idx) == []

    assert sec.set_secret("vpn", "abc123", index_path=idx) is True
    assert sec.get_secret("vpn") == "abc123"
    assert sec.list_secrets(idx) == ["vpn"]

    assert sec.set_secret("smtp", "xyz", index_path=idx) is True
    assert sorted(sec.list_secrets(idx)) == ["smtp", "vpn"]

    assert sec.delete_secret("vpn", index_path=idx) is True
    assert sec.get_secret("vpn") is None
    assert sec.list_secrets(idx) == ["smtp"]


def test_set_secret_sin_keyring_devuelve_false(monkeypatch, tmp_path):
    import core.secrets as sec
    monkeypatch.setattr(sec, "_HAS_KEYRING", False)
    assert sec.set_secret("x", "y", index_path=tmp_path / "i.json") is False
    assert sec.get_secret("x") is None


def test_render_placeholders_resuelve_secret(monkeypatch, tmp_path):
    fake = _FakeKeyring()
    import core.secrets as sec
    monkeypatch.setattr(sec, "_HAS_KEYRING", True)
    monkeypatch.setattr(sec, "keyring", fake)
    sec.set_secret("vpn", "miclave123", index_path=tmp_path / "i.json")

    from core.step_model import render_placeholders
    out = render_placeholders("Login: usuario  Pass: {SECRET:vpn}", {})
    assert out == "Login: usuario  Pass: miclave123"


def test_render_placeholders_secret_no_existe(monkeypatch, tmp_path):
    fake = _FakeKeyring()
    import core.secrets as sec
    monkeypatch.setattr(sec, "_HAS_KEYRING", True)
    monkeypatch.setattr(sec, "keyring", fake)

    from core.step_model import render_placeholders
    out = render_placeholders("{SECRET:no_existe}", {})
    # Debe devolver un marcador visible, no string vacío
    assert "<<SECRET_NOT_FOUND:no_existe>>" == out


def test_render_combina_secret_y_placeholder_normal(monkeypatch, tmp_path):
    fake = _FakeKeyring()
    import core.secrets as sec
    monkeypatch.setattr(sec, "_HAS_KEYRING", True)
    monkeypatch.setattr(sec, "keyring", fake)
    sec.set_secret("api", "TOKEN_ABC", index_path=tmp_path / "i.json")

    from core.step_model import render_placeholders
    out = render_placeholders("{DNI}: {SECRET:api}", {"DNI": "123"})
    assert out == "123: TOKEN_ABC"
