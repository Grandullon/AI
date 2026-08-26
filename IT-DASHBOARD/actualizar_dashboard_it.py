# -*- coding: utf-8 -*-
"""
Dashboard diario de Ausencias e Incapacidad Temporal — HUVN · RRHH

Lee los volcados diarios IT-HVN-*.xlsx y ALTAS IT*.xlsx de las carpetas de red,
cruza con Personal Activo si esta disponible, y deja un HTML autosuficiente en
la carpeta compartida. Quien tenga permiso sobre esa carpeta lo abre con doble
clic; quien no lo tenga, no ve nada. No hay servidor, ni base de datos, ni
salida de datos a internet.

Las rutas y umbrales viven en config_it.json, junto al .exe. Cambiarlos no
obliga a recompilar.

Uso:
    python actualizar_dashboard_it.py                 (con ventana)
    python actualizar_dashboard_it.py --headless      (para tarea programada)
    python actualizar_dashboard_it.py --demo          (datos inventados, para enseñarlo)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import webbrowser
from pathlib import Path

from lector_xlsx import ErrorLectura
from motor_it import (FAMILIAS_DEFECTO, cargar_altas, cargar_plantilla, cargar_snapshot,
                      construir_indicadores, dias_atras, fecha_larga, localizar)

APP = "Dashboard de Ausencias e IT · HUVN"
VERSION = "1.0"

CONFIG_DEFECTO = {
    "_como_editar": "Edita este fichero con el Bloc de notas. Guarda y vuelve a ejecutar "
                    "el programa. NO hace falta recompilar nada.",
    "_tokens": {
        "{YYYY}": "anio (2026)", "{MM}": "mes 2 digitos", "{DD}": "dia 2 digitos",
        "{MES_TEXTO}": "nombre del mes en espanol",
    },
    "carpeta_it": r"\\Alhambra\grupo$\HUVN-PERSONAL-ACTIVO\IT DIARIA\IT DIARIA\{YYYY}",
    "patron_it": "IT-HVN-{YYYY}-{MM}-{DD}",
    "carpeta_altas": r"\\Alhambra\grupo$\HUVN-PERSONAL-ACTIVO\IT DIARIA\ALTAS IT\{YYYY}",
    "patron_altas": "ALTAS IT A {YYYY}-{MM}-{DD}",
    "carpeta_personal_activo": r"\\Alhambra\grupo$\HUVN-PERSONAL-ACTIVO\Personal Activo\{YYYY}",
    "patron_personal_activo": "PA-{YYYY}-{MM}-{DD}",
    "salida": r"\\Alhambra\grupo$\HUVN-PERSONAL-ACTIVO\Dashboard-IT.html",
    "generar_version_direccion": True,
    "_generar_version_direccion": "Genera ademas un HTML sin nombres ni DNI, apto para "
                                  "compartir con direccion y comisiones.",
    "dias_serie": 20,
    "dias_vigilancia": 500,
    "_dias_vigilancia": "A partir de cuantos dias entra una ausencia en la tabla de "
                        "seguimiento de larga duracion.",
    "incluir_fines_de_semana": False,
    "abrir_al_terminar": True,
    "familias": FAMILIAS_DEFECTO,
    "_familias": "Prefijo o codigo de COD_INC -> nombre del grupo. Revisalo con la "
                 "unidad: ITE/ITA/ITN/ITI/ITR se agrupan como incapacidad temporal.",
    "columnas": {},
    "_columnas": "Solo si algun volcado cambia de cabecera. Ej: {\"f_it\": \"Fecha IT\"}",
}


def carpeta_base() -> Path:
    """Donde vive el .exe (si esta compilado) o el .py."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def cargar_config(log) -> dict:
    ruta = carpeta_base() / "config_it.json"
    config = dict(CONFIG_DEFECTO)
    if ruta.exists():
        try:
            usuario = json.loads(ruta.read_text(encoding="utf-8"))
            config.update({k: v for k, v in usuario.items() if not k.startswith("_")})
            log(f"Configuracion leida de {ruta.name}")
        except json.JSONDecodeError as exc:
            log(f"[!] {ruta.name} tiene un error de sintaxis (linea {exc.lineno}, "
                f"columna {exc.colno}). Revisa comas, comillas y barras dobles.")
            log("    Se continua con la configuracion interna.")
    else:
        try:
            ruta.write_text(json.dumps(CONFIG_DEFECTO, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            log(f"Creada la configuracion inicial en {ruta}")
        except OSError:
            log("[!] No se pudo escribir config_it.json; se usa la configuracion interna.")
    return config


def recurso(nombre: str) -> Path:
    """Recurso empaquetado: dentro del .exe vive en sys._MEIPASS."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / nombre
    return carpeta_base() / nombre


# ─────────────────────────── recopilacion ───────────────────────────

def recopilar(config: dict, fecha_ref: dt.date, log) -> tuple[list, dict, dict, list[str]]:
    incidencias: list[str] = []
    familias = config.get("familias") or FAMILIAS_DEFECTO
    columnas = config.get("columnas") or {}
    n_dias = int(config.get("dias_serie", 20))
    finde = bool(config.get("incluir_fines_de_semana", False))

    # El volcado de hoy puede no estar aun; se retrocede hasta encontrarlo.
    ultimo = None
    for atras in range(0, 12):
        prueba = fecha_ref - dt.timedelta(days=atras)
        if localizar(config["carpeta_it"], config["patron_it"], prueba):
            ultimo = prueba
            break
    if ultimo is None:
        raise ErrorLectura(
            f"No encuentro ningun volcado IT de los ultimos 12 dias en:\n"
            f"{config['carpeta_it']}\n"
            f"Comprueba que tienes acceso a la carpeta y que el patron "
            f"'{config['patron_it']}' coincide con el nombre real de los ficheros."
        )
    if ultimo != fecha_ref:
        incidencias.append(f"El volcado mas reciente es del {ultimo.strftime('%d/%m/%Y')}.")

    snapshots = []
    for fecha in dias_atras(ultimo, n_dias, finde):
        ruta = localizar(config["carpeta_it"], config["patron_it"], fecha)
        if not ruta:
            continue
        try:
            snap = cargar_snapshot(ruta, fecha, familias, columnas)
        except ErrorLectura as exc:
            incidencias.append(str(exc))
            continue
        if len(snap):
            snapshots.append(snap)
            log(f"  {fecha.strftime('%d/%m')}  {len(snap):>4} ausencias   {ruta.name}")
    if not snapshots:
        raise ErrorLectura("Los volcados localizados no contienen filas legibles.")

    # Altas: cada una se atribuye a su fecha real de alta, no a la del fichero.
    altas_por_fecha: dict[dt.date, list] = {}
    fechas_con_foto = {s.fecha for s in snapshots}
    for fecha in dias_atras(ultimo, n_dias + 4, finde):
        ruta = localizar(config["carpeta_altas"], config["patron_altas"], fecha)
        if not ruta:
            continue
        try:
            for alta in cargar_altas(ruta, fecha, familias, columnas):
                altas_por_fecha.setdefault(alta["f_alta"], []).append(alta)
        except ErrorLectura as exc:
            incidencias.append(str(exc))
    # El fichero de altas de un dia trae las altas de los dias anteriores (el del
    # lunes cubre el fin de semana). Cada alta se lleva al primer volcado que la
    # habria recogido, para no perder las de dias sin foto.
    ordenadas = sorted(fechas_con_foto)
    reubicadas: dict[dt.date, list] = {}
    for fecha_alta, lista in altas_por_fecha.items():
        destino = next((f for f in ordenadas if f >= fecha_alta), None)
        if destino is not None:
            reubicadas.setdefault(destino, []).extend(lista)
    altas_por_fecha = reubicadas
    if altas_por_fecha:
        log(f"  altas leidas para {len(altas_por_fecha)} fecha(s)")

    # Personal activo: para la tasa sobre plantilla. Es opcional.
    plantilla = {"total": 0, "por_servicio": {}, "por_direccion": {}, "por_centro": {}}
    for atras in range(0, 12):
        ruta = localizar(config["carpeta_personal_activo"], config["patron_personal_activo"],
                         ultimo - dt.timedelta(days=atras))
        if ruta:
            try:
                plantilla = cargar_plantilla(ruta, columnas)
                log(f"  plantilla activa: {plantilla['total']} personas ({ruta.name})")
            except ErrorLectura as exc:
                incidencias.append(str(exc))
            break
    else:
        incidencias.append("No se localizo el fichero de Personal Activo: no se calcula "
                           "el porcentaje sobre plantilla.")
    return snapshots, altas_por_fecha, plantilla, incidencias


def actualizar_historial(indicadores: dict, destino: Path, log) -> None:
    """Guarda un punto por dia. Deja rastro aunque despues se borren volcados."""
    ruta = destino.parent / "historial_it.json"
    historial = []
    if ruta.exists():
        try:
            historial = json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            historial = []
    k = indicadores["kpis"]
    punto = {"fecha": indicadores["meta"]["fecha"], "total": k["vigentes"], "it": k["it"],
             "altas": k["altas_hoy"], "bajas": k["bajas_hoy"], "cobertura": k["cobertura"],
             "sin_cubrir": k["sin_cubrir"], "dur_media": k["dur_media"]}
    historial = [p for p in historial if p.get("fecha") != punto["fecha"]]
    historial.append(punto)
    historial.sort(key=lambda p: p.get("fecha", ""))
    try:
        ruta.write_text(json.dumps(historial[-800:], ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except OSError:
        log("[!] No se pudo escribir historial_it.json (permisos de la carpeta).")


def generar_html(indicadores: dict, destino: Path) -> Path:
    plantilla = recurso("plantilla_it.html")
    if not plantilla.exists():
        raise FileNotFoundError(f"No encuentro plantilla_it.html (esperado en {plantilla})")
    html = plantilla.read_text(encoding="utf-8")
    html = html.replace("__DATOS_JSON__", json.dumps(indicadores, ensure_ascii=False))
    html = html.replace("__GENERADO__", dt.datetime.now().strftime("%d/%m/%Y a las %H:%M"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html, encoding="utf-8")
    return destino


def abrir(ruta: Path, log) -> None:
    try:
        if sys.platform == "win32":
            import os
            os.startfile(str(ruta))            # noqa: S606
        else:
            webbrowser.open(ruta.as_uri())
    except Exception as exc:                    # noqa: BLE001
        log(f"[!] No se pudo abrir el navegador: {exc}")


# ─────────────────────────── proceso completo ───────────────────────────

def ejecutar(args, log) -> Path | None:
    config = cargar_config(log)
    if args.dias:
        config["dias_serie"] = args.dias
    fecha_ref = dt.date.fromisoformat(args.fecha) if args.fecha else dt.date.today()

    if args.demo:
        from demo import datos_demo
        log("Modo demostracion: los datos son inventados.")
        snapshots, altas, plantilla, incidencias = datos_demo(fecha_ref)
    else:
        log(f"Explorando volcados hasta el {fecha_ref.strftime('%d/%m/%Y')}...")
        snapshots, altas, plantilla, incidencias = recopilar(config, fecha_ref, log)

    salida = Path(args.salida or config["salida"])
    generados = []

    vigilancia = int(config.get("dias_vigilancia", 500))
    indicadores = construir_indicadores(snapshots, altas, plantilla, incidencias,
                                        anonimo=args.anonimo, vigilancia=vigilancia)
    ruta = generar_html(indicadores, salida)
    generados.append(ruta)
    log(f"Generado: {ruta}")
    actualizar_historial(indicadores, salida, log)

    # Version sin datos personales, para direccion y comisiones.
    if config.get("generar_version_direccion") and not args.anonimo:
        agregado = construir_indicadores(snapshots, altas, plantilla, incidencias,
                                         anonimo=True, vigilancia=vigilancia)
        ruta_dir = salida.with_name(salida.stem + "-direccion" + salida.suffix)
        generar_html(agregado, ruta_dir)
        generados.append(ruta_dir)
        log(f"Generado: {ruta_dir}  (sin nombres ni DNI)")

    k = indicadores["kpis"]
    log("")
    log(f"  Ausencias vigentes .......... {k['vigentes']}")
    log(f"  De ellas, IT ................ {k['it']}")
    log(f"  Altas del dia ............... {k['altas_hoy']}")
    log(f"  Ausencias nuevas ............ {k['bajas_hoy']}")
    log(f"  Sin sustituto ............... {k['sin_cubrir']} ({100 - k['cobertura']:.1f} %)")
    log(f"  Mas de {vigilancia} dias ............ {k['vigilancia']}")

    if config.get("abrir_al_terminar", True) and not args.headless:
        abrir(generados[0], log)
    return generados[0]


def main() -> int:
    p = argparse.ArgumentParser(description=APP)
    p.add_argument("--headless", action="store_true", help="sin ventana, para tareas programadas")
    p.add_argument("--salida", help="ruta del HTML de salida")
    p.add_argument("--dias", type=int, help="numero de volcados de la serie")
    p.add_argument("--fecha", help="fecha de referencia AAAA-MM-DD (por defecto, hoy)")
    p.add_argument("--anonimo", action="store_true", help="genera solo la version sin datos personales")
    p.add_argument("--demo", action="store_true", help="datos inventados, para ensenar la herramienta")
    args = p.parse_args()

    if args.headless:
        def log(msg=""):
            print(msg, flush=True)
        try:
            ejecutar(args, log)
            return 0
        except (ErrorLectura, FileNotFoundError, OSError) as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1

    return ventana(args)


def ventana(args) -> int:
    """Ventana minima: un boton, un registro de lo que va pasando."""
    import tkinter as tk
    from tkinter import scrolledtext

    raiz = tk.Tk()
    raiz.title(f"{APP} v{VERSION}")
    raiz.geometry("760x460")
    raiz.configure(bg="#0057a8")

    tk.Label(raiz, text="Ausencias e Incapacidad Temporal", bg="#0057a8", fg="white",
             font=("Segoe UI", 15, "bold")).pack(pady=(14, 0))
    tk.Label(raiz, text="Hospital Universitario Virgen de las Nieves · Personal",
             bg="#0057a8", fg="#cfe2f6", font=("Segoe UI", 9)).pack()

    marco = tk.Frame(raiz, bg="white")
    marco.pack(fill="both", expand=True, padx=12, pady=12)
    registro = scrolledtext.ScrolledText(marco, font=("Consolas", 9), bg="white",
                                         relief="flat", wrap="word")
    registro.pack(fill="both", expand=True, padx=8, pady=8)

    def log(msg=""):
        registro.insert("end", str(msg) + "\n")
        registro.see("end")
        raiz.update_idletasks()

    barra = tk.Frame(raiz, bg="#0057a8")
    barra.pack(fill="x", padx=12, pady=(0, 12))

    def lanzar():
        boton.config(state="disabled", text="Generando...")
        registro.delete("1.0", "end")
        try:
            ejecutar(args, log)
            log("")
            log("Listo. El informe se ha abierto en el navegador.")
        except (ErrorLectura, FileNotFoundError, OSError) as exc:
            log("")
            log(f"[ERROR] {exc}")
        finally:
            boton.config(state="normal", text="Actualizar informe")

    boton = tk.Button(barra, text="Actualizar informe", command=lanzar,
                      font=("Segoe UI", 10, "bold"), bg="white", fg="#0057a8",
                      relief="flat", padx=18, pady=7, cursor="hand2")
    boton.pack(side="right")

    raiz.after(300, lanzar)     # se genera solo al abrir
    raiz.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
