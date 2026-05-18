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
    ultima_ejecucion: str = ""
    ultimo_resultado: str = ""

    @property
    def ok_ultima_ejecucion(self) -> bool | None:
        """True si último resultado=0, False si !=0, None si no se conoce."""
        s = (self.ultimo_resultado or "").strip()
        if not s or s.upper() == "N/A":
            return None
        try:
            return int(s, 0) == 0
        except (ValueError, TypeError):
            return None


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


def ejecutar_ahora(nombre: str) -> tuple[bool, str]:
    """Lanza la tarea inmediatamente con `schtasks /Run`.

    Devuelve (éxito, mensaje). El mensaje es útil para mostrar el error
    en la GUI si la tarea no se pudo ejecutar (no existe, sin permisos,
    etc.).
    """
    if not _es_windows():
        return False, "Solo disponible en Windows"
    nombre_completo = f"{PREFIX}{nombre}" if not nombre.startswith(PREFIX) else nombre
    res = _correr(["schtasks", "/Run", "/TN", nombre_completo])
    if res.returncode == 0:
        return True, f"Tarea '{nombre_completo}' lanzada"
    return False, (res.stderr.strip() or res.stdout.strip() or "schtasks falló")


def habilitar_tarea(nombre: str, habilitar: bool = True) -> bool:
    if not _es_windows():
        return False
    nombre_completo = f"{PREFIX}{nombre}" if not nombre.startswith(PREFIX) else nombre
    flag = "/ENABLE" if habilitar else "/DISABLE"
    res = _correr(["schtasks", "/Change", "/TN", nombre_completo, flag])
    return res.returncode == 0


def validar_args(
    args: list[str],
    macros_dir: Path,
    pipelines_dir: Path,
) -> list[str]:
    """Devuelve una lista de errores (vacía si todo bien).

    Comprueba que la macro / pipeline / Excel referidos en `args` existen
    realmente en disco, para evitar crear tareas con referencias rotas.
    """
    errores: list[str] = []
    args = list(args)

    def _existe_macro(nombre: str) -> bool:
        if not nombre:
            return False
        p = Path(nombre)
        if p.is_file():
            return True
        for sufijo in (".yaml", ".yml"):
            if (macros_dir / f"{nombre}{sufijo}").exists():
                return True
        return False

    def _existe_pipeline(nombre: str) -> bool:
        if not nombre:
            return False
        p = Path(nombre)
        if p.is_file():
            return True
        for sufijo in (".yaml", ".yml"):
            if (pipelines_dir / f"{nombre}{sufijo}").exists():
                return True
        return False

    # Buscar cada flag y validar su valor
    for i, a in enumerate(args):
        if a in ("--macro", "--replay") and i + 1 < len(args):
            nombre = args[i + 1]
            if not _existe_macro(nombre):
                errores.append(
                    f"No se encuentra la macro '{nombre}' en {macros_dir}"
                )
        elif a == "--pipeline" and i + 1 < len(args):
            nombre = args[i + 1]
            if not _existe_pipeline(nombre):
                errores.append(
                    f"No se encuentra el pipeline '{nombre}' en {pipelines_dir}"
                )
        elif a == "--excel" and i + 1 < len(args):
            excel = Path(args[i + 1])
            if not excel.exists():
                errores.append(f"No se encuentra el Excel: {excel}")
    return errores


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


def _parse_csv_tasks(text: str, delim: str) -> list[TareaProgramada]:
    """Parsea la salida CSV de schtasks con el delimitador dado.

    Las columnas varían según la versión de Windows y si se usa /V o no:
      - Sin /V: col 0 = TaskName, col 1 = NextRunTime, col 2 = Status
      - Con /V: col 0 = HostName, col 1 = TaskName, col 2 = NextRunTime,
                col 3 = Status, ..., col 8 = TaskToRun
    Para ser inmunes a esa diferencia, escaneamos cada fila buscando
    la columna cuyo valor empieza por `MemoviPro_` (o `\\MemoviPro_`).
    Las siguientes dos columnas se toman como NextRunTime y Status.

    Si el OTRO delimitador aparece dentro del valor, eso indica que
    estamos parseando con el delimitador equivocado y descartamos esa
    fila (típico fallo en Windows español donde schtasks emite `;`).
    """
    import csv
    from io import StringIO

    otro = ";" if delim == "," else ","
    out: list[TareaProgramada] = []
    reader = csv.reader(StringIO(text), delimiter=delim)
    for fila in reader:
        if not fila:
            continue
        idx_nombre = -1
        for i, val in enumerate(fila):
            v_norm = val.strip('"').strip().lstrip("\\")
            if v_norm.startswith(PREFIX) and otro not in val:
                idx_nombre = i
                break
        if idx_nombre < 0:
            continue
        nombre = fila[idx_nombre].strip('"').strip().lstrip("\\")
        def _safe(i):
            return fila[i].strip('"').strip() if 0 <= i < len(fila) else ""
        # Con /V, las columnas relativas al TaskName son:
        #   +1 Next Run Time, +2 Status, +3 Logon Mode,
        #   +4 Last Run Time, +5 Last Result, +6 Author, +7 Task To Run
        proximo = _safe(idx_nombre + 1)
        estado = _safe(idx_nombre + 2)
        ultima_ejecucion = _safe(idx_nombre + 4)
        ultimo_resultado = _safe(idx_nombre + 5)
        # Task To Run: buscamos columna que parezca una ruta/ejecutable.
        accion = ""
        for ofs in (7, 8, 6):
            i_acc = idx_nombre + ofs
            v = _safe(i_acc)
            if v and (".exe" in v.lower() or "\\" in v or "--" in v):
                accion = v
                break
        out.append(TareaProgramada(
            nombre=nombre,
            proximo=proximo,
            estado=estado,
            accion=accion,
            ultima_ejecucion=ultima_ejecucion,
            ultimo_resultado=ultimo_resultado,
        ))
    seen: set[str] = set()
    unicas: list[TareaProgramada] = []
    for t in out:
        if t.nombre in seen:
            continue
        seen.add(t.nombre)
        unicas.append(t)
    return unicas


def _parse_list_tasks(text: str) -> list[TareaProgramada]:
    """Parsea la salida `schtasks /FO LIST /V` como fallback.

    Cada tarea es un bloque de líneas `Clave: Valor` separadas por
    una línea en blanco. Funciona en cualquier locale: aunque las
    claves estén traducidas ("Nombre de tarea" en vez de "TaskName"),
    nos basta con encontrar UNA línea cuyo valor empiece por la
    barra invertida `\\MemoviPro_…`.
    """
    out: list[TareaProgramada] = []
    bloque: dict[str, str] = {}

    def emitir():
        # Buscamos cualquier línea cuyo valor pinta a nombre de tarea
        # (`\MemoviPro_xxx`) y la usamos como nombre.
        nombre = ""
        proximo = ""
        estado = ""
        accion = ""
        for clave, valor in bloque.items():
            v = valor.strip()
            v_norm = v.lstrip("\\")
            cl = clave.strip().lower()
            if not nombre and v_norm.startswith(PREFIX):
                nombre = v_norm
            elif "next" in cl or "próxima" in cl or "proxima" in cl:
                proximo = v
            elif cl in ("status", "estado"):
                estado = v
            elif "task to run" in cl or "tarea" in cl and "ejecutar" in cl:
                accion = v
        if nombre:
            out.append(TareaProgramada(
                nombre=nombre,
                proximo=proximo,
                estado=estado,
                accion=accion,
            ))

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            if bloque:
                emitir()
                bloque = {}
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            bloque[k.strip()] = v.strip()
    if bloque:
        emitir()

    seen: set[str] = set()
    unicas: list[TareaProgramada] = []
    for t in out:
        if t.nombre in seen:
            continue
        seen.add(t.nombre)
        unicas.append(t)
    return unicas


def listar_tareas() -> list[TareaProgramada]:
    """Devuelve solo las tareas con prefijo MemoviPro_.

    Estrategia robusta multi-locale:
      1. Pide schtasks /FO CSV /NH /V.
      2. Prueba CSV con `,` Y con `;`. Se queda con la lista más larga.
         (Windows en inglés usa `,`, español/francés/alemán usan `;`).
      3. Si AMBAS dan 0, intenta /FO LIST /V que es resistente a la
         localización porque va por bloques `Clave: Valor`.
    """
    if not _es_windows():
        return []

    res = _correr(["schtasks", "/Query", "/FO", "CSV", "/NH", "/V"])
    if res.returncode == 0 and res.stdout:
        with_comma = _parse_csv_tasks(res.stdout, ",")
        with_semi = _parse_csv_tasks(res.stdout, ";")
        logger.debug(
            "listar_tareas CSV: coma={} semi={}",
            len(with_comma), len(with_semi),
        )
        elegido = with_comma if len(with_comma) >= len(with_semi) else with_semi
        if elegido:
            return elegido

    # Fallback: formato LIST (bloques Clave: Valor)
    res2 = _correr(["schtasks", "/Query", "/FO", "LIST", "/V"])
    if res2.returncode == 0 and res2.stdout:
        lista = _parse_list_tasks(res2.stdout)
        logger.debug("listar_tareas LIST: {}", len(lista))
        return lista

    logger.warning(
        "listar_tareas no encontró tareas (rc_csv={} rc_list={})",
        res.returncode, res2.returncode if 'res2' in locals() else "n/a",
    )
    return []
