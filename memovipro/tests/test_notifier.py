from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.notifier import SmtpConfig, construir_html


def test_smtp_config_is_complete():
    incompleto = SmtpConfig.from_dict({"host": "smtp.x", "from_addr": "a@b.c"})
    assert incompleto.is_complete() is False

    completo = SmtpConfig.from_dict({
        "host": "smtp.x", "from_addr": "a@b.c", "recipients": ["d@e.f"],
    })
    assert completo.is_complete() is True


def test_construir_html_lista_dnis_y_resalta_ok():
    html = construir_html(
        macro="m1",
        total=5,
        ok=3,
        ko=2,
        log_path="/tmp/i.xlsx",
        dnis_fallidos=[("12345678A", "DNI no encontrado"), ("99999999B", "timeout")],
    )
    assert "12345678A" in html
    assert "DNI no encontrado" in html
    assert "OK: 3" in html
    assert "KO: 2" in html
    assert "/tmp/i.xlsx" in html


def test_construir_html_caso_sin_fallos():
    html = construir_html(
        macro="m1", total=3, ok=3, ko=0, log_path="x", dnis_fallidos=[],
    )
    assert "Sin fallos" in html
    assert "#27ae60" in html  # color verde
