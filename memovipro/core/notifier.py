"""Envío de notificación por email al terminar una ejecución."""
from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from loguru import logger


@dataclass
class SmtpConfig:
    host: str = ""
    port: int = 587
    user: str = ""
    password: str = ""
    use_tls: bool = True
    from_addr: str = ""
    recipients: list[str] = None  # type: ignore[assignment]

    @classmethod
    def from_dict(cls, d: dict) -> "SmtpConfig":
        return cls(
            host=d.get("host", ""),
            port=int(d.get("port", 587)),
            user=d.get("user", ""),
            password=d.get("password", ""),
            use_tls=bool(d.get("use_tls", True)),
            from_addr=d.get("from_addr", "") or d.get("user", ""),
            recipients=list(d.get("recipients", []) or []),
        )

    def is_complete(self) -> bool:
        return bool(self.host and self.from_addr and self.recipients)


def construir_html(
    macro: str,
    total: int,
    ok: int,
    ko: int,
    log_path: str,
    dnis_fallidos: list[tuple[str, str]],
) -> str:
    filas = "".join(
        f"<tr><td style='padding:6px;border:1px solid #ddd'>{dni}</td>"
        f"<td style='padding:6px;border:1px solid #ddd'>{motivo}</td></tr>"
        for dni, motivo in dnis_fallidos
    ) or "<tr><td colspan='2' style='padding:6px;text-align:center'>Sin fallos</td></tr>"
    color = "#27ae60" if ko == 0 else "#c0392b"
    return f"""<!doctype html>
<html><body style="font-family:Arial,sans-serif;color:#2c3e50">
<h2 style="color:{color}">MemoviPro · ejecución de "{macro}"</h2>
<p><b>Total:</b> {total} &nbsp; <b style="color:#27ae60">OK: {ok}</b> &nbsp; <b style="color:#c0392b">KO: {ko}</b></p>
<p><b>Archivo de incidencias:</b><br><code>{log_path}</code></p>
<h3>DNIs con incidencia</h3>
<table style="border-collapse:collapse">
<thead><tr style="background:#2c3e50;color:white">
<th style="padding:6px">DNI</th><th style="padding:6px">Motivo</th></tr></thead>
<tbody>{filas}</tbody></table>
<p style="color:#95a5a6;font-size:12px">Mensaje generado automáticamente por MemoviPro.</p>
</body></html>"""


def enviar_resumen(
    cfg: SmtpConfig,
    asunto: str,
    html: str,
    adjuntar_log: str | Path | None = None,
) -> bool:
    """Envía un email con el resumen. Devuelve True si tuvo éxito."""
    if not cfg.is_complete():
        logger.warning("Notificación deshabilitada: configuración SMTP incompleta")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = cfg.from_addr
    msg["To"] = ", ".join(cfg.recipients)
    msg.attach(MIMEText(html, "html", "utf-8"))

    if adjuntar_log:
        path = Path(adjuntar_log)
        if path.exists():
            from email.mime.application import MIMEApplication
            with path.open("rb") as f:
                part = MIMEApplication(f.read(), Name=path.name)
            part["Content-Disposition"] = f'attachment; filename="{path.name}"'
            msg.attach(part)

    try:
        if cfg.use_tls:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(cfg.host, cfg.port, timeout=20) as s:
                s.starttls(context=ctx)
                if cfg.user:
                    s.login(cfg.user, cfg.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=20) as s:
                if cfg.user:
                    s.login(cfg.user, cfg.password)
                s.send_message(msg)
        logger.info("Notificación enviada a {}", cfg.recipients)
        return True
    except Exception as exc:
        logger.error("Fallo enviando notificación: {}", exc)
        return False
