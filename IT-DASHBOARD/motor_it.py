# -*- coding: utf-8 -*-
"""
Motor de datos del Dashboard de Ausencias / IT.

Lee los volcados diarios de las carpetas de red, normaliza columnas y calcula
los indicadores. No sabe nada de HTML ni de ventanas: solo datos.

Semantica de los volcados IT-HVN-*.xlsx (comprobada sobre fichero real):
  · 'Fecha IT'      -> fecha de inicio de la ausencia   (la que cuenta)
  · 'FECHA INICIO'  -> alta del contrato (vinculacion), NO de la IT
  · 'FECHA FINAL'   -> fin de contrato; vacia en fijos. NO es el alta de IT
  · 'Dias de IT'    -> dias transcurridos a la fecha del volcado
  · 'COD_INC'       -> codigo de incidencia (ITE, ITA, IMS, PAT, PL3...)
  · 'SUSTITUTO_IT'  -> nombre del sustituto; vacio = plaza sin cubrir
"""
from __future__ import annotations

import datetime as _dt
import re
import statistics
import unicodedata
from pathlib import Path

from lector_xlsx import ErrorLectura, leer_hoja_preferida

# ─────────────────────────── normalizacion ───────────────────────────

def normalizar(texto) -> str:
    """'Fecha Início ' -> 'fecha inicio'. Para comparar sin sufrir con tildes."""
    if texto is None:
        return ""
    plano = unicodedata.normalize("NFKD", str(texto))
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", plano.lower()).strip()


def compactar(texto) -> str:
    """Como normalizar pero sin separadores: 'IT-HVN-2026-08-26' -> 'ithvn20260826'."""
    return normalizar(texto).replace(" ", "")


# Alias por campo interno. Se comparan normalizados: da igual acento o mayuscula.
ALIAS = {
    "dni":          ["dni nie", "dni", "nif", "documento"],
    "nombre":       ["apellidos nombre", "apellidos y nombre", "nombre y apellidos", "trabajador"],
    "edad":         ["edad"],
    "categoria":    ["categoria", "categoria profesional"],
    "especialidad": ["especialidad"],
    "servicio":     ["servicio", "unidad", "destino"],
    "centro":       ["centro eq", "centro", "centro trabajo"],
    "direccion":    ["direccion", "direccion responsable", "area"],
    "cod":          ["cod inc", "codigo incidencia", "incidencia", "cod incidencia", "tipo it"],
    # OJO: la fecha de la baja es 'Fecha IT'. 'FECHA INICIO' es del contrato.
    "f_it":         ["fecha it", "fecha baja", "f baja", "inicio it", "fecha inicio it"],
    "f_alta":       ["fecha alta it", "fecha alta", "f alta", "alta it"],
    "dias":         ["dias de it", "dias it", "dias", "duracion"],
    "sustituto":    ["sustituto it", "sustituto", "sustituto_it"],
    "motivo_sust":  ["motivo sustitucion", "motivo de sustitucion"],
    "contrato_ini": ["fecha inicio", "f inicio", "inicio contrato"],
    "contrato_fin": ["fecha final", "fecha fin", "fin contrato"],
    "vinculacion":  ["vinculacion", "vinculo"],
    "sexo":         ["sexo", "genero"],
}

IMPRESCINDIBLES = ("f_it",)

# Agrupacion de codigos en familias. Contrastado con MOTIVO-SUSTITUCION del
# volcado real: IM*->Baja Maternal, PA*->Paternidad, PL3->Permiso Lactancia.
# Se puede reescribir desde config.json sin tocar el programa.
FAMILIAS_DEFECTO = {
    "IT": "Incapacidad temporal",
    "IM": "Maternidad",
    "PA": "Paternidad",
    "PL": "Permisos",
    "EMB": "Riesgo embarazo",
}
FAMILIA_OTROS = "Otras ausencias"


def familia_de(codigo: str, familias: dict) -> str:
    cod = (codigo or "").upper().strip()
    if not cod:
        return FAMILIA_OTROS
    if cod in familias:
        return familias[cod]
    for prefijo in sorted(familias, key=len, reverse=True):
        if cod.startswith(prefijo):
            return familias[prefijo]
    return FAMILIA_OTROS


def mapear_columnas(cabeceras, overrides: dict | None = None) -> dict:
    """Devuelve {campo_interno: nombre_real_de_la_columna}."""
    overrides = overrides or {}
    indice = {}
    for c in cabeceras:
        clave = normalizar(c)
        if clave and clave not in indice:
            indice[clave] = c
    mapa = {}
    for campo, alias in ALIAS.items():
        forzado = overrides.get(campo)
        if forzado and forzado in cabeceras:
            mapa[campo] = forzado
            continue
        for a in alias:                      # coincidencia exacta
            if a in indice:
                mapa[campo] = indice[a]
                break
        if campo in mapa:
            continue
        for a in alias:                      # la cabecera empieza por el alias
            for norm, real in indice.items():
                if norm.startswith(a):
                    mapa[campo] = real
                    break
            if campo in mapa:
                break
    return mapa


def _a_fecha(valor):
    """Acepta date, datetime, serial de Excel o texto en varios formatos."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, _dt.datetime):
        return valor.date()
    if isinstance(valor, _dt.date):
        return valor
    if isinstance(valor, (int, float)):
        try:
            return (_dt.datetime(1899, 12, 30) + _dt.timedelta(days=float(valor))).date()
        except (ValueError, OverflowError):
            return None
    texto = str(valor).strip().split("T")[0].split(" ")[0]
    for patron in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%y", "%d.%m.%Y"):
        try:
            return _dt.datetime.strptime(texto, patron).date()
        except ValueError:
            continue
    return None


def _limpiar(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return re.sub(r"\s+", " ", str(valor)).strip()


def _entero(valor):
    if valor is None or valor == "":
        return None
    try:
        return int(float(str(valor).replace(",", ".")))
    except (TypeError, ValueError):
        return None


# ─────────────────────────── localizar ficheros ───────────────────────────

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
         "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def resolver_tokens(texto: str, fecha: _dt.date) -> str:
    return (texto.replace("{YYYY}", str(fecha.year))
                 .replace("{MM}", f"{fecha.month:02d}")
                 .replace("{DD}", f"{fecha.day:02d}")
                 .replace("{WW}", f"{fecha.isocalendar()[1]:02d}")
                 .replace("{MES_TEXTO}", MESES[fecha.month - 1]))


def localizar(carpeta_patron: str, patron_archivo: str, fecha: _dt.date,
              extension: str = "xlsx") -> Path | None:
    """
    Busca el fichero de un dia. Mira la carpeta del anio y sus subcarpetas, asi
    da igual como se llame la del mes (MARZO, 03-Marzo, marzo...). Compara en
    forma compacta: 'IT-HVN-2026-08-26' y 'ITHVN20260826' se reconocen igual.
    """
    base = Path(resolver_tokens(carpeta_patron, fecha))
    esperado = compactar(resolver_tokens(patron_archivo, fecha))
    if not esperado:
        return None
    try:
        if not base.is_dir():
            return None
        candidatos = list(base.glob(f"*.{extension}")) + list(base.glob(f"*/*.{extension}"))
    except (OSError, PermissionError):
        return None
    for ruta in candidatos:
        if compactar(ruta.stem) == esperado:
            return ruta
    for ruta in candidatos:           # tolera sufijos: '... (rev).xlsx'
        if compactar(ruta.stem).startswith(esperado):
            return ruta
    return None


def dias_atras(desde: _dt.date, cuantos: int, incluir_finde: bool = False) -> list[_dt.date]:
    """Fechas hacia atras, saltando fines de semana salvo que se pidan."""
    fechas, cursor, guarda = [], desde, 0
    while len(fechas) < cuantos and guarda < cuantos * 4 + 60:
        if incluir_finde or cursor.weekday() < 5:
            fechas.append(cursor)
        cursor -= _dt.timedelta(days=1)
        guarda += 1
    return list(reversed(fechas))


# ─────────────────────────── carga ───────────────────────────

class Snapshot:
    """Foto de un dia: las ausencias vigentes segun el volcado de esa fecha."""

    __slots__ = ("fecha", "registros", "ruta", "por_id")

    def __init__(self, fecha, registros, ruta):
        self.fecha, self.registros = fecha, registros
        self.ruta = Path(ruta) if ruta else None
        self.por_id = {r["id"]: r for r in registros}

    def __len__(self):
        return len(self.registros)


def _clave(reg: dict, n: int) -> str:
    """Identidad estable entre dias. Con DNI basta; si falta, nombre + inicio."""
    dni = normalizar(reg.get("dni"))
    if dni:
        return f"D:{dni}"
    nombre = normalizar(reg.get("nombre"))
    if nombre:
        inicio = reg.get("f_it")
        return f"N:{nombre}|{inicio.isoformat() if inicio else ''}"
    return f"F:{n}"


def _construir(fila: dict, mapa: dict, fecha: _dt.date, familias: dict, n: int) -> dict | None:
    inicio = _a_fecha(fila.get(mapa.get("f_it")))
    if inicio is None:
        return None
    alta = _a_fecha(fila.get(mapa.get("f_alta")))
    sustituto = _limpiar(fila.get(mapa.get("sustituto")))
    dias = _entero(fila.get(mapa.get("dias")))
    if dias is None:
        dias = (fecha - inicio).days
    cod = _limpiar(fila.get(mapa.get("cod"))).upper() or "SIN COD"
    reg = {
        "dni": _limpiar(fila.get(mapa.get("dni"))),
        "nombre": _limpiar(fila.get(mapa.get("nombre"))) or "SIN NOMBRE",
        "edad": _entero(fila.get(mapa.get("edad"))),
        "categoria": _limpiar(fila.get(mapa.get("categoria"))) or "SIN CATEGORIA",
        "especialidad": _limpiar(fila.get(mapa.get("especialidad"))),
        "servicio": _limpiar(fila.get(mapa.get("servicio"))) or "SIN SERVICIO",
        "centro": _limpiar(fila.get(mapa.get("centro"))) or "SIN CENTRO",
        "direccion": _limpiar(fila.get(mapa.get("direccion"))) or "SIN DIRECCION",
        "cod": cod,
        "familia": familia_de(cod, familias),
        "f_it": inicio,
        "f_alta": alta,
        "dias": dias,
        "sustituto": sustituto,
        "cubierta": bool(sustituto),
        "motivo_sust": _limpiar(fila.get(mapa.get("motivo_sust"))),
        "contrato_fin": _a_fecha(fila.get(mapa.get("contrato_fin"))),
    }
    reg["id"] = _clave(reg, n)
    return reg


def cargar_snapshot(ruta: Path, fecha: _dt.date, familias: dict,
                    overrides: dict | None = None) -> Snapshot:
    filas = leer_hoja_preferida(ruta, ["IT DIARIA", "IT", "DATOS"])
    if not filas:
        return Snapshot(fecha, [], ruta)
    mapa = mapear_columnas(list(filas[0].keys()), overrides)
    faltan = [c for c in IMPRESCINDIBLES if c not in mapa]
    if faltan:
        raise ErrorLectura(
            f"{ruta.name}: no localizo la columna de inicio de la baja ('Fecha IT'). "
            f"Cabeceras leidas: {', '.join(list(filas[0].keys())[:12])}"
        )
    registros = []
    for n, fila in enumerate(filas):
        reg = _construir(fila, mapa, fecha, familias, n)
        if reg is None:
            continue
        if reg["f_alta"] and reg["f_alta"] <= fecha:
            continue                      # ya reincorporado a esa fecha
        registros.append(reg)
    return Snapshot(fecha, registros, ruta)


def cargar_altas(ruta: Path, fecha_fichero: _dt.date, familias: dict,
                 overrides: dict | None = None) -> list[dict]:
    """
    Fichero 'ALTAS IT A ...': reincorporaciones. Cubre una ventana de varios
    dias (el del lunes trae el fin de semana), asi que cada alta se atribuye a
    su 'Fecha Alta IT', no a la fecha del fichero.
    """
    filas = leer_hoja_preferida(ruta, ["ALTAS", "ALTAS IT"])
    if not filas:
        return []
    mapa = mapear_columnas(list(filas[0].keys()), overrides)
    altas = []
    for n, fila in enumerate(filas):
        reg = _construir(fila, mapa, fecha_fichero, familias, n)
        if reg is None:
            continue
        reg["f_alta"] = reg["f_alta"] or fecha_fichero
        if reg.get("f_it"):
            reg["dias"] = _entero(fila.get(mapa.get("dias")))
            if reg["dias"] is None:
                reg["dias"] = (reg["f_alta"] - reg["f_it"]).days
        altas.append(reg)
    return altas


def cargar_plantilla(ruta: Path, overrides: dict | None = None) -> dict:
    """Del PA-YYYY-MM-DD.xlsx solo interesa cuanta gente activa hay y donde."""
    filas = leer_hoja_preferida(ruta, ["PERSONAL ACTIVO", "PA", "DATOS"])
    if not filas:
        return {"total": 0, "por_servicio": {}, "por_direccion": {}, "por_centro": {}}
    mapa = mapear_columnas(list(filas[0].keys()), overrides)
    srv, dire, centro = {}, {}, {}
    for fila in filas:
        s = _limpiar(fila.get(mapa.get("servicio"))) or "SIN SERVICIO"
        d = _limpiar(fila.get(mapa.get("direccion"))) or "SIN DIRECCION"
        c = _limpiar(fila.get(mapa.get("centro"))) or "SIN CENTRO"
        srv[s] = srv.get(s, 0) + 1
        dire[d] = dire.get(d, 0) + 1
        centro[c] = centro.get(c, 0) + 1
    return {"total": len(filas), "por_servicio": srv, "por_direccion": dire, "por_centro": centro}


# ─────────────────────────── indicadores ───────────────────────────

TRAMOS = [("1-7", 0, 7), ("8-15", 8, 15), ("16-30", 16, 30), ("31-90", 31, 90),
          ("91-180", 91, 180), ("181-365", 181, 365), ("+365", 366, 10 ** 7)]
TRAMOS_EDAD = [("-30", 0, 29), ("30-39", 30, 39), ("40-49", 40, 49),
               ("50-59", 50, 59), ("60+", 60, 200)]

# Hitos de control de la IT: son los que de verdad miran en gestion.
HITO_PRORROGA = 365    # 12 meses: control INSS, prorroga o propuesta de IP
HITO_MAXIMO = 545      # 18 meses: plazo maximo agotado


def _contar(registros, campo, top=None):
    conteo = {}
    for r in registros:
        clave = r.get(campo) or "SIN DATO"
        conteo[clave] = conteo.get(clave, 0) + 1
    orden = sorted(conteo.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return orden[:top] if top else orden


def _tramo(valor, tramos):
    if valor is None:
        return "SIN DATO"
    for etiqueta, minimo, maximo in tramos:
        if minimo <= valor <= maximo:
            return etiqueta
    return "SIN DATO"


def _persona(reg, anonimo: bool) -> dict:
    """Fila lista para el HTML. En modo anonimo no viajan ni nombre ni DNI."""
    fila = {
        "srv": reg.get("servicio", ""), "cat": reg.get("categoria", ""),
        "cen": reg.get("centro", ""), "dir": reg.get("direccion", ""),
        "cod": reg.get("cod", ""), "fam": reg.get("familia", ""),
        "dias": reg.get("dias"), "edad": reg.get("edad"),
        "ini": reg["f_it"].isoformat() if reg.get("f_it") else "",
        "alta": reg["f_alta"].isoformat() if reg.get("f_alta") else "",
        "sus": reg.get("sustituto", "") if not anonimo else ("Si" if reg.get("cubierta") else ""),
        "cub": bool(reg.get("cubierta")),
    }
    fila["nom"] = "—" if anonimo else reg.get("nombre", "")
    fila["dni"] = "" if anonimo else reg.get("dni", "")
    return fila


def construir_indicadores(snapshots: list[Snapshot], altas_por_fecha: dict,
                          plantilla: dict, incidencias: list[str],
                          anonimo: bool = False) -> dict:
    """snapshots ordenados de mas antiguo a mas reciente."""
    if not snapshots:
        return {"error": "No se ha podido leer ningún volcado diario.",
                "incidencias": incidencias}

    hoy, ayer = snapshots[-1], (snapshots[-2] if len(snapshots) > 1 else None)
    vigentes = hoy.registros

    # ── serie diaria ──
    serie = []
    for i, snap in enumerate(snapshots):
        altas_dia = bajas_dia = None
        if i > 0:
            previo = snapshots[i - 1]
            bajas_dia = sum(1 for k in snap.por_id if k not in previo.por_id)
            altas_dia = sum(1 for k in previo.por_id if k not in snap.por_id)
        reales = altas_por_fecha.get(snap.fecha)   # el fichero ALTAS IT manda
        if reales is not None:
            altas_dia = len(reales)
        serie.append({
            "f": snap.fecha.isoformat(),
            "et": snap.fecha.strftime("%d/%m"),
            "total": len(snap),
            "it": sum(1 for r in snap.registros if r["familia"] == "Incapacidad temporal"),
            "altas": altas_dia,
            "bajas": bajas_dia,
        })

    totales = [p["total"] for p in serie]
    media_periodo = round(statistics.fmean(totales), 1) if totales else 0
    delta_dia = len(hoy) - len(ayer) if ayer else 0

    # ── movimientos del dia ──
    bajas_hoy = [r for k, r in hoy.por_id.items() if ayer and k not in ayer.por_id]
    altas_hoy = [r for k, r in ayer.por_id.items() if k not in hoy.por_id] if ayer else []
    origen_altas = "comparacion de volcados"
    reales_hoy = altas_por_fecha.get(hoy.fecha)
    if reales_hoy is not None:
        altas_hoy, origen_altas = reales_hoy, "fichero ALTAS IT"

    # ── duraciones y cobertura ──
    con_dias = [r for r in vigentes if r.get("dias") is not None]
    duraciones = [r["dias"] for r in con_dias]
    largas_90 = [r for r in con_dias if r["dias"] > 90]
    prorroga = sorted((r for r in con_dias if HITO_PRORROGA <= r["dias"] < HITO_MAXIMO),
                      key=lambda r: -r["dias"])
    maximo = sorted((r for r in con_dias if r["dias"] >= HITO_MAXIMO), key=lambda r: -r["dias"])
    cubiertas = [r for r in vigentes if r["cubierta"]]
    sin_cubrir = [r for r in vigentes if not r["cubierta"]]

    # ── ranking por servicio y por direccion ──
    def ranking(campo, dotaciones, tope=40):
        conteo = dict(_contar(vigentes, campo))
        historico: dict[str, list[int]] = {}
        for snap in snapshots:
            c = dict(_contar(snap.registros, campo))
            for clave in conteo:
                historico.setdefault(clave, []).append(c.get(clave, 0))
        filas = []
        for clave, total in sorted(conteo.items(), key=lambda kv: -kv[1])[:tope]:
            hist = historico.get(clave, [total])
            media = statistics.fmean(hist) if hist else total
            desv = statistics.pstdev(hist) if len(hist) > 1 else 0.0
            dotacion = dotaciones.get(clave, 0)
            grupo = [r for r in vigentes if r.get(campo) == clave]
            filas.append({
                "nombre": clave,
                "total": total,
                "plantilla": dotacion,
                "tasa": round(total / dotacion * 100, 1) if dotacion else None,
                "media": round(media, 1),
                "delta": round(total - media, 1),
                "pico": bool(desv > 0 and total > media + 2 * desv and total >= 3),
                "sin_cubrir": sum(1 for r in grupo if not r["cubierta"]),
                "largas": sum(1 for r in grupo if (r.get("dias") or 0) > 90),
                "serie": hist[-20:],
            })
        return filas

    rank_srv = ranking("servicio", plantilla.get("por_servicio", {}))
    rank_dir = ranking("direccion", plantilla.get("por_direccion", {}), tope=20)
    rank_cen = ranking("centro", plantilla.get("por_centro", {}), tope=15)

    mes = hoy.fecha.month
    jornadas_mes = sum(p["total"] for p, s in zip(serie, snapshots) if s.fecha.month == mes)
    total_plantilla = plantilla.get("total", 0)
    edades = [r["edad"] for r in vigentes if r.get("edad")]

    # ── alertas ──
    alertas = []
    if maximo:
        alertas.append({"nivel": "critico",
                        "titulo": f"{len(maximo)} ausencias superan los 18 meses",
                        "detalle": "Plazo máximo agotado: procede resolver la situación "
                                   "(alta, prórroga extraordinaria o propuesta de IP)."})
    if prorroga:
        alertas.append({"nivel": "aviso",
                        "titulo": f"{len(prorroga)} ausencias entre 12 y 18 meses",
                        "detalle": "Tramo de control del INSS: prórroga expresa o propuesta de IP."})
    picos = [r for r in rank_srv if r["pico"]]
    if picos:
        alertas.append({"nivel": "aviso",
                        "titulo": f"Repunte anómalo en {len(picos)} servicio(s)",
                        "detalle": "Por encima de su media del periodo: "
                                   + ", ".join(r["nombre"] for r in picos[:4]) + "."})
    if ayer and len(ayer) and abs(delta_dia) / len(ayer) > 0.05:
        alertas.append({"nivel": "aviso" if delta_dia > 0 else "ok",
                        "titulo": f"La cifra {'sube' if delta_dia > 0 else 'baja'} un "
                                  f"{abs(delta_dia) / len(ayer) * 100:.1f}% respecto al volcado anterior",
                        "detalle": f"De {len(ayer)} a {len(hoy)} ausencias vigentes."})
    if vigentes and len(sin_cubrir) / len(vigentes) > 0.5:
        alertas.append({"nivel": "aviso",
                        "titulo": f"{len(sin_cubrir)} ausencias sin sustituto asignado",
                        "detalle": f"Un {len(sin_cubrir) / len(vigentes) * 100:.0f}% del total. "
                                   "Revisar la cobertura en los servicios de la tabla."})
    for aviso in incidencias:
        alertas.append({"nivel": "info", "titulo": "Aviso de lectura", "detalle": aviso})
    if not alertas:
        alertas.append({"nivel": "ok", "titulo": "Sin incidencias destacables",
                        "detalle": "Ningún umbral de control superado hoy."})

    conteo_tramos = {}
    for r in vigentes:
        clave = _tramo(r.get("dias"), TRAMOS)
        conteo_tramos[clave] = conteo_tramos.get(clave, 0) + 1
    conteo_edad = {}
    for r in vigentes:
        clave = _tramo(r.get("edad"), TRAMOS_EDAD)
        conteo_edad[clave] = conteo_edad.get(clave, 0) + 1

    return {
        "meta": {
            "fecha": hoy.fecha.isoformat(),
            "fecha_larga": fecha_larga(hoy.fecha),
            "fecha_anterior": ayer.fecha.isoformat() if ayer else None,
            "dias_serie": len(serie),
            "fichero": hoy.ruta.name if hoy.ruta else "",
            "origen_altas": origen_altas,
            "anonimo": anonimo,
            "plantilla_total": total_plantilla,
        },
        "kpis": {
            "vigentes": len(hoy),
            "it": sum(1 for r in vigentes if r["familia"] == "Incapacidad temporal"),
            "delta_dia": delta_dia,
            "altas_hoy": len(altas_hoy),
            "bajas_hoy": len(bajas_hoy),
            "saldo": len(bajas_hoy) - len(altas_hoy),
            "media_periodo": media_periodo,
            "tasa_absentismo": round(len(hoy) / total_plantilla * 100, 2) if total_plantilla else None,
            "cubiertas": len(cubiertas),
            "sin_cubrir": len(sin_cubrir),
            "cobertura": round(len(cubiertas) / len(vigentes) * 100, 1) if vigentes else 0,
            "largas_90": len(largas_90),
            "prorroga": len(prorroga),
            "maximo": len(maximo),
            "jornadas_mes": jornadas_mes,
            "dur_media": round(statistics.fmean(duraciones), 1) if duraciones else 0,
            "dur_mediana": round(statistics.median(duraciones), 1) if duraciones else 0,
            "edad_media": round(statistics.fmean(edades), 1) if edades else None,
        },
        "serie": serie,
        "ranking": {"servicio": rank_srv, "direccion": rank_dir, "centro": rank_cen},
        "distribuciones": {
            "familia": _contar(vigentes, "familia"),
            "cod": _contar(vigentes, "cod", 12),
            "categoria": _contar(vigentes, "categoria", 12),
            "tramos": [[t[0], conteo_tramos.get(t[0], 0)] for t in TRAMOS],
            "edad": [[t[0], conteo_edad.get(t[0], 0)] for t in TRAMOS_EDAD],
        },
        "alertas": alertas,
        "movimientos": {
            "altas": [_persona(r, anonimo) for r in sorted(altas_hoy, key=lambda r: -(r.get("dias") or 0))],
            "bajas": [_persona(r, anonimo) for r in sorted(bajas_hoy, key=lambda r: r.get("servicio") or "")],
        },
        "criticas": [_persona(r, anonimo) for r in (maximo + prorroga)[:80]],
        "vigentes": [_persona(r, anonimo) for r in sorted(vigentes, key=lambda r: -(r.get("dias") or 0))],
    }


def fecha_larga(f: _dt.date) -> str:
    return f"{DIAS_SEMANA[f.weekday()]} {f.day} de {MESES[f.month - 1]} de {f.year}"
