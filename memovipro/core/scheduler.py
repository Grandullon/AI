"""Integración con Windows Task Scheduler vía `schtasks.exe`.

Crea/lista/elimina tareas que invocan al CLI de MemoviPro (`cli.py` o el
`.exe` empaquetado con PyInstaller).

Limitación: las tareas que automatizan UI necesitan una sesión Windows
iniciada. Por eso al crear la tarea forzamos `/RL LIMITED` y el flag
`/IT` (Interactive Task). Si necesitas que se ejecute aunque el usuario
no esté logado deberás convertirlo en servicio aparte, pero perderás la
posibilidad de simular ratón/teclado en un escritorio.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import time as dtime
from pathlib import Path

from loguru import logger


PREFIX = "MemoviPro_"


@dataclass
class TareaProgramada:
    nombre: str
    proximo: str
    estado: str
    accion: str = ""


@dataclass
class Frecuencia:
    """Frecuencia para schtasks. Solo se usa una variante."""
    diaria: bool = False
    semanal: bool = False
    dias_semana: tuple[str, ...] = ()  # MON,TUE,...
    al_iniciar_sesion: bool = False
    una_vez: bool = False
    hora: dtime = dtime(8, 0)

    def to_schtasks_args(self) -> list[str]:
        hora = self.hora.strftime("%H:%M")
        if self.al_iniciar_sesion:
            return ["/SC", "ONLOGON"]
        if self.diaria:
            return ["/SC", "DAILY", "/ST", hora]
        if self.semanal:
            dias = ",".join(self.dias_semana) if self.dias_semana else "MON"
            return ["/SC", "WEEKLY", "/D", dias, "/ST", hora]
        if self.una_vez:
            return ["/SC", "ONCE", "/ST", hora]
        return ["/SC", "DAILY", "/ST", hora]


def _es_windows() -> bool:
    return sys.platform.startswith("win")


def _correr(cmd: list[str]) -> subprocess.CompletedProcess:
    logger.debug("schtasks: {}", " ".join(shlex.quote(c) for c in cmd))
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")


def _auto_detect_run_exe() -> Path | None:
    """Si estamos corriendo como .exe empaquetado, busca memovipro-run.exe
    junto al ejecutable actual."""
    if not getattr(sys, "frozen", False):
        return None
    gui_exe = Path(sys.executable).resolve()
    candidato = gui_exe.parent / "memovipro-run.exe"
    if candidato.exists():
        return candidato
    return None


def construir_accion(
    args: list[str],
    ejecutable: str | Path | None = None,
) -> tuple[str, str]:
    """Devuelve (programa, argumentos) listos para schtasks /TR.

    `args` es la lista de argumentos CLI ya preparada por el caller.

    Resolución del programa a ejecutar:
      1. Si se pasa `ejecutable`, se usa esa ruta.
      2. Si estamos en modo congelado (.exe via PyInstaller), buscamos
         memovipro-run.exe junto a sys.executable. Si está, lo usamos.
         Si no, lanzamos error — sys.executable + cli.py no funciona
         desde un .exe porque cli.py vive en una carpeta temporal que
         se borra al cerrar.
      3. En desarrollo (python app.py), usamos sys.executable + cli.py.
    """
    if ejecutable:
        exe = Path(ejecutable).resolve()
        if not exe.exists():
            raise FileNotFoundError(f"Ejecutable no encontrado: {exe}")
        return str(exe), subprocess.list2cmdline(args)

    auto = _auto_detect_run_exe()
    if auto is not None:
        return str(auto), subprocess.list2cmdline(args)

    if getattr(sys, "frozen", False):
        raise RuntimeError(
            "Para programar tareas necesitas tener 'memovipro-run.exe' "
            "junto a 'memovipro-gui.exe'. Descarga el artefacto "
            "'memovipro-paquete-completo' (que incluye ambos) o indica "
            "la ruta de memovipro-run.exe en el campo '.exe' del panel."
        )

    # Modo desarrollo: python cli.py
    py = Path(sys.executable).resolve()
    cli = Path(__file__).resolve().parents[1] / "cli.py"
    return str(py), subprocess.list2cmdline([str(cli), *args])


def crear_tarea(
    nombre: str,
    args: list[str],
    frecuencia: Frecuencia,
    ejecutable: str | Path | None = None,
    sobrescribir: bool = True,
) -> bool:
    """Crea una tarea programada que lanza el CLI con los `args` dados.

    Devuelve True si la creación tuvo éxito.
    """
    if not _es_windows():
        logger.error("crear_tarea solo está disponible en Windows")
        return False

    nombre_completo = f"{PREFIX}{nombre}" if not nombre.startswith(PREFIX) else nombre
    programa, args_str = construir_accion(args, ejecutable)
    tr = f'"{programa}" {args_str}'.strip()

    cmd = ["schtasks", "/Create", "/TN", nombre_completo, "/TR", tr, "/RL", "LIMITED", "/IT"]
    cmd.extend(frecuencia.to_schtasks_args())
    if sobrescribir:
        cmd.append("/F")

    res = _correr(cmd)
    if res.returncode == 0:
        logger.info("Tarea creada: {}", nombre_completo)
        return True
    logger.error("Fallo creando tarea {}: rc={} stderr={}", nombre_completo, res.returncode, res.stderr.strip())
    return False


def eliminar_tarea(nombre: str) -> bool:
    if not _es_windows():
        return False
    nombre_completo = f"{PREFIX}{nombre}" if not nombre.startswith(PREFIX) else nombre
    res = _correr(["schtasks", "/Delete", "/TN", nombre_completo, "/F"])
    return res.returncode == 0


def _detectar_delimiter(text: str) -> str:
    """Decide si el CSV usa coma o punto y coma.

    schtasks en Windows español emite CSV con ';' por defecto (porque el
    coma es separador decimal en es-ES). En inglés usa ','. Lo detectamos
    contando ocurrencias en la primera línea no vacía.
    """
    for linea in text.splitlines():
        if not linea.strip():
            continue
        if linea.count(";") > linea.count(","):
            return ";"
        return ","
    return ","


def listar_tareas() -> list[TareaProgramada]:
    """Devuelve solo las tareas creadas por MemoviPro (prefijo MemoviPro_)."""
    if not _es_windows():
        return []
    res = _correr(["schtasks", "/Query", "/FO", "CSV", "/NH", "/V"])
    if res.returncode != 0:
        logger.warning("schtasks query devolvió {}", res.returncode)
        return []

    out: list[TareaProgramada] = []
    import csv
    from io import StringIO

    delim = _detectar_delimiter(res.stdout)
    logger.debug("schtasks CSV delimiter detectado: {}", repr(delim))
    reader = csv.reader(StringIO(res.stdout), delimiter=delim)
    for fila in reader:
        if len(fila) < 2:
            continue
        nombre = fila[0].strip('"').strip()
        if not nombre.lstrip("\\").startswith(PREFIX) and PREFIX not in nombre:
            continue
        proximo = fila[2] if len(fila) > 2 else ""
        estado = fila[3] if len(fila) > 3 else ""
        accion = fila[8] if len(fila) > 8 else ""
        out.append(TareaProgramada(
            nombre=nombre.lstrip("\\"),
            proximo=proximo,
            estado=estado,
            accion=accion,
        ))

    seen: set[str] = set()
    unicas: list[TareaProgramada] = []
    for t in out:
        if t.nombre in seen:
            continue
        seen.add(t.nombre)
        unicas.append(t)
    return unicas
