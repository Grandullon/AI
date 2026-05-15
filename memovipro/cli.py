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


def _ocultar_consola_si_quiet() -> None:
    """Oculta la ventana de consola en Windows si --quiet está en argv.

    Tiene que llamarse lo ANTES posible para evitar el flash de la
    consola al arrancar desde Task Scheduler. Si no es Windows o no
    hay consola, es no-op.
    """
    if "--quiet" not in sys.argv:
        return
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE
    except Exception:
        pass


_ocultar_consola_si_quiet()

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

    parser = argparse.ArgumentParser(prog="memovipro-run", description="Ejecuta una macro o pipeline MemoviPro sin GUI.")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--macro", help="Nombre de la macro (sin extensión) o ruta al YAML — modo iteración por DNI")
    grupo.add_argument("--pipeline", help="Nombre del pipeline (sin extensión) o ruta al YAML — modo cadena")
    grupo.add_argument("--replay", help="Nombre de macro o ruta — modo reproducción simple N veces")
    parser.add_argument("--excel", help="Excel/CSV con la columna DNI (solo con --macro)")
    parser.add_argument("--veces", type=int, default=1, help="Veces a repetir (solo con --replay)")
    parser.add_argument("--velocidad", type=float, default=1.0, help="Velocidad de replay (1.0 original, 0=sin pausas)")
    parser.add_argument("--all", action="store_true", help="Procesar todos los DNIs ignorando checkpoint (solo --macro)")
    parser.add_argument("--dry-run", action="store_true", help="Simulación: resalta sin clicar")
    parser.add_argument("--no-retry", action="store_true", help="No reintentar KO al final (--macro)")
    parser.add_argument("--no-notify", action="store_true", help="No enviar email aunque esté configurado")
    parser.add_argument(
        "--quiet", action="store_true",
        help="Oculta la ventana de consola al iniciar (Windows). Para tareas programadas.",
    )
    parser.add_argument("--data-dir", default=str(ROOT / "data"), help="Carpeta de incidencias/checkpoints")
    parser.add_argument("--macros-dir", default=str(ROOT / "macros"), help="Carpeta de macros")
    parser.add_argument("--pipelines-dir", default=str(ROOT / "pipelines"), help="Carpeta de pipelines")
    parser.add_argument("--logs-dir", default=str(ROOT / "logs"), help="Carpeta de logs")
    args = parser.parse_args(argv)

    if args.macro and not args.excel:
        parser.error("--macro requiere --excel")

    info = ensure_runtime_folders(ROOT)
    setup_logging(args.logs_dir)
    logger.info("=== MemoviPro CLI ===")
    logger.debug("Bootstrap: {}", info)
    logger.info(
        "modo={} dry_run={} veces={}",
        "pipeline" if args.pipeline else ("replay" if args.replay else "macro"),
        args.dry_run, args.veces,
    )

    macros_dir = Path(args.macros_dir)
    data_dir = Path(args.data_dir)
    screenshots_dir = data_dir / "screenshots"
    data_dir.mkdir(parents=True, exist_ok=True)
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    # ---- modo --pipeline ----
    if args.pipeline:
        from core.pipeline import Pipeline
        from core.pipeline_runner import PipelineRunner
        pipelines_dir = Path(args.pipelines_dir)
        pipelines_dir.mkdir(parents=True, exist_ok=True)
        try:
            p = Path(args.pipeline)
            if p.is_file():
                pipeline_path = p
            else:
                pipeline_path = pipelines_dir / f"{args.pipeline}.yaml"
                if not pipeline_path.exists():
                    pipeline_path = pipelines_dir / f"{args.pipeline}.yml"
            pipeline = Pipeline.load(pipeline_path)
        except Exception as exc:
            logger.error("No se pudo cargar el pipeline: {}", exc)
            return 1
        runner = PipelineRunner(
            pipeline=pipeline,
            macros_dir=macros_dir,
            screenshots_dir=screenshots_dir,
            data_dir=data_dir,
        )
        try:
            psum = runner.run()
        except Exception:
            logger.exception("Error fatal durante el pipeline")
            return 1
        logger.info(
            "Pipeline '{}' fin · ok={} ko={} pasos={}",
            psum.nombre, psum.total_ok, psum.total_ko, len(psum.pasos_resultado),
        )
        return 0 if psum.total_ko == 0 and not psum.abortado else 2

    # ---- modo --replay ----
    if args.replay:
        from core.replay_runner import ReplayRunner
        try:
            macro_path = _resolver_macro(args.replay, macros_dir)
            macro = Macro.load(macro_path)
        except Exception as exc:
            logger.error("No se pudo cargar la macro: {}", exc)
            return 1
        runner = ReplayRunner(
            macro=macro,
            veces=args.veces,
            velocidad=args.velocidad,
            screenshots_dir=screenshots_dir,
            data_dir=data_dir,
        )
        try:
            rsum = runner.run()
        except Exception:
            logger.exception("Error fatal durante replay")
            return 1
        logger.info("Replay fin · total={} ok={} ko={}", rsum.total, rsum.ok, rsum.ko)
        return 0 if rsum.ko == 0 else 2

    # ---- modo --macro --excel (DNI) ----
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
