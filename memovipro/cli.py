"""MemoviPro CLI — ejecuta una macro sobre un Excel sin abrir la GUI.

Uso típico (desde Task Scheduler o PowerShell):
    memovipro-run.exe --macro descarga_it --excel D:/datos/dnis.xlsx
    memovipro-run.exe --macro descarga_it --excel D:/datos/dnis.xlsx --dry-run
    memovipro-run.exe --macro descarga_it --excel D:/datos/dnis.xlsx --no-retry --no-notify

Códigos de salida:
    0 → todo OK
    2 → terminó pero con DNIs KO
    1 → error fatal (macro no encontrada, Excel ilegible, etc.)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from loguru import logger

from core.bootstrap import ensure_runtime_folders
from core.log_config import setup_logging
from core.notifier import SmtpConfig
from core.runner import MacroRunner
from core.step_model import Macro


def _cargar_config() -> dict:
    p = ROOT / "config.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolver_macro(nombre_o_ruta: str, macros_dir: Path) -> Path:
    p = Path(nombre_o_ruta)
    if p.is_file():
        return p
    for sufijo in (".yaml", ".yml"):
        cand = macros_dir / f"{nombre_o_ruta}{sufijo}"
        if cand.exists():
            return cand
    raise FileNotFoundError(
        f"Macro no encontrada: {nombre_o_ruta!r}. Buscado como ruta y en {macros_dir}"
    )


def _ayuda_interactiva() -> int:
    print("=" * 60)
    print(" MemoviPro CLI · memovipro-run.exe")
    print("=" * 60)
    print()
    print("Este ejecutable necesita argumentos. Llámalo desde una")
    print("consola, desde Task Scheduler, o desde RunMacro.ps1:")
    print()
    print("  memovipro-run.exe --macro NOMBRE --excel D:\\datos\\dnis.xlsx")
    print()
    print("Opciones:")
    print("  --macro NOMBRE      Macro a ejecutar (sin .yaml o ruta completa)")
    print("  --excel RUTA        Excel/CSV con la columna DNI")
    print("  --dry-run           Simulación: resalta los controles, no clica")
    print("  --all               Ignorar checkpoint y procesar todos los DNIs")
    print("  --no-retry          No reintentar KO al final")
    print("  --no-notify         No enviar email aunque esté configurado")
    print()
    print("Códigos de salida: 0=OK · 2=KO parcial · 1=error fatal")
    print()
    try:
        input("Pulsa Enter para salir...")
    except EOFError:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None and len(sys.argv) == 1 and getattr(sys, "frozen", False):
        return _ayuda_interactiva()

    parser = argparse.ArgumentParser(prog="memovipro-run", description="Ejecuta una macro MemoviPro sin GUI.")
    parser.add_argument("--macro", required=True, help="Nombre de la macro (sin extensión) o ruta al YAML")
    parser.add_argument("--excel", required=True, help="Excel/CSV con la columna DNI")
    parser.add_argument("--all", action="store_true", help="Procesar todos (ignorar checkpoint)")
    parser.add_argument("--dry-run", action="store_true", help="Simulación: resalta sin clicar")
    parser.add_argument("--no-retry", action="store_true", help="No reintentar KO al final")
    parser.add_argument("--no-notify", action="store_true", help="No enviar email aunque esté configurado")
    parser.add_argument("--data-dir", default=str(ROOT / "data"), help="Carpeta de incidencias/checkpoints")
    parser.add_argument("--macros-dir", default=str(ROOT / "macros"), help="Carpeta donde buscar la macro por nombre")
    parser.add_argument("--logs-dir", default=str(ROOT / "logs"), help="Carpeta de logs")
    args = parser.parse_args(argv)

    info = ensure_runtime_folders(ROOT)
    setup_logging(args.logs_dir)
    logger.info("=== MemoviPro CLI ===")
    logger.debug("Bootstrap: {}", info)
    logger.info("macro={} excel={} dry_run={} all={}", args.macro, args.excel, args.dry_run, args.all)

    macros_dir = Path(args.macros_dir)
    data_dir = Path(args.data_dir)
    screenshots_dir = data_dir / "screenshots"
    data_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    try:
        macro_path = _resolver_macro(args.macro, macros_dir)
        macro = Macro.load(macro_path)
    except Exception as exc:
        logger.error("No se pudo cargar la macro: {}", exc)
        return 1

    if not Path(args.excel).exists():
        logger.error("Excel no encontrado: {}", args.excel)
        return 1

    cfg = _cargar_config()
    smtp_cfg = None
    if not args.no_notify:
        smtp_dict = cfg.get("smtp", {}) or {}
        if smtp_dict.get("enviar_al_terminar"):
            smtp_cfg = SmtpConfig.from_dict(smtp_dict)
            if not smtp_cfg.is_complete():
                logger.warning("SMTP marcado para enviar pero la configuración está incompleta")
                smtp_cfg = None

    runner = MacroRunner(
        macro=macro,
        excel_dnis=args.excel,
        screenshots_dir=screenshots_dir,
        data_dir=data_dir,
        polling_watchdog_ms=int(cfg.get("polling_watchdog_ms", 300)),
        ignorar_popups=list(cfg.get("popup_titulos_ignorar", []) or []),
        dry_run=args.dry_run,
        reintentar_ko_al_final=not args.no_retry,
        smtp_config=smtp_cfg,
    )
    try:
        summary = runner.run(solo_pendientes=not args.all)
    except Exception:
        logger.exception("Error fatal durante la ejecución")
        return 1

    logger.info("Resultado · total={} ok={} ko={} log={}", summary.total, summary.ok, summary.ko, summary.log_path)
    return 0 if summary.ko == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
