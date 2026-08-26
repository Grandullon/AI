# -*- coding: utf-8 -*-
"""
Lector de .xlsx sin dependencias externas.

Un .xlsx es un ZIP con XML dentro. Aqui se abre con zipfile + xml.etree, que
vienen de serie en Python. Motivo: el .exe resultante no necesita pandas ni
openpyxl, pesa poco y no depende de que nadie instale nada en su equipo.

Devuelve cada hoja como lista de diccionarios {cabecera: valor}.
"""
from __future__ import annotations

import datetime as _dt
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKGREL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# Formatos numericos que Excel considera fecha de fabrica.
FORMATOS_FECHA = set(range(14, 23)) | set(range(45, 48)) | {27, 30, 36, 50, 57}
_RE_FMT_FECHA = re.compile(r"(?<!\\)[dmyhs]", re.IGNORECASE)
_EPOCH = _dt.datetime(1899, 12, 30)  # Excel cuenta desde aqui (bug del 1900 incluido)


class ErrorLectura(Exception):
    pass


def _col_a_indice(ref: str) -> int:
    """'AB12' -> 27 (indice 0). Solo mira las letras."""
    n = 0
    for ch in ref:
        if ch.isalpha():
            n = n * 26 + (ord(ch.upper()) - 64)
        else:
            break
    return n - 1


def _serial_a_fecha(valor: float):
    try:
        f = _EPOCH + _dt.timedelta(days=float(valor))
    except (ValueError, OverflowError):
        return None
    return f.date() if f.time() == _dt.time(0, 0) else f


class LibroExcel:
    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        try:
            self._zip = zipfile.ZipFile(self.ruta)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ErrorLectura(f"No se puede abrir {self.ruta.name}: {exc}") from exc
        self._cadenas = self._leer_cadenas()
        self._estilos_fecha = self._leer_estilos()

    def cerrar(self):
        try:
            self._zip.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    # ---------- partes internas del xlsx ----------
    def _xml(self, nombre: str):
        try:
            with self._zip.open(nombre) as fh:
                return ET.parse(fh).getroot()
        except KeyError:
            return None
        except ET.ParseError as exc:
            raise ErrorLectura(f"{self.ruta.name} -> {nombre} corrupto: {exc}") from exc

    def _leer_cadenas(self) -> list[str]:
        raiz = self._xml("xl/sharedStrings.xml")
        if raiz is None:
            return []
        cadenas = []
        for si in raiz.findall(f"{NS_MAIN}si"):
            # El texto puede venir partido en varios <t> por formato enriquecido.
            cadenas.append("".join(t.text or "" for t in si.iter(f"{NS_MAIN}t")))
        return cadenas

    def _leer_estilos(self) -> set[int]:
        """Indices de estilo (s=) cuyo formato numerico es una fecha."""
        raiz = self._xml("xl/styles.xml")
        if raiz is None:
            return set()
        personalizados = {}
        for nf in raiz.iter(f"{NS_MAIN}numFmt"):
            try:
                idf = int(nf.get("numFmtId", -1))
            except ValueError:
                continue
            codigo = (nf.get("formatCode") or "").split(";")[0]
            # Quita literales entre comillas antes de buscar d/m/y.
            limpio = re.sub(r'"[^"]*"', "", codigo)
            if _RE_FMT_FECHA.search(limpio):
                personalizados[idf] = True
        fechas = set()
        cell_xfs = raiz.find(f"{NS_MAIN}cellXfs")
        if cell_xfs is None:
            return fechas
        for i, xf in enumerate(cell_xfs.findall(f"{NS_MAIN}xf")):
            try:
                idf = int(xf.get("numFmtId", 0))
            except ValueError:
                continue
            if idf in FORMATOS_FECHA or personalizados.get(idf):
                fechas.add(i)
        return fechas

    def _rutas_hojas(self) -> list[tuple[str, str]]:
        libro = self._xml("xl/workbook.xml")
        rels = self._xml("xl/_rels/workbook.xml.rels")
        if libro is None:
            raise ErrorLectura(f"{self.ruta.name} no parece un Excel valido")
        destino = {}
        if rels is not None:
            for rel in rels.findall(f"{NS_PKGREL}Relationship"):
                objetivo = rel.get("Target", "")
                if objetivo.startswith("/"):
                    objetivo = objetivo[1:]
                elif not objetivo.startswith("xl/"):
                    objetivo = "xl/" + objetivo
                destino[rel.get("Id")] = objetivo.replace("/./", "/")
        hojas = []
        for hoja in libro.iter(f"{NS_MAIN}sheet"):
            rid = hoja.get(f"{NS_REL}id")
            ruta = destino.get(rid)
            if ruta:
                hojas.append((hoja.get("name", "Hoja"), ruta))
        if not hojas:
            hojas = [("Hoja1", "xl/worksheets/sheet1.xml")]
        return hojas

    # ---------- lectura de celdas ----------
    def _valor(self, celda) -> object:
        tipo = celda.get("t")
        if tipo == "inlineStr":
            nodo = celda.find(f"{NS_MAIN}is")
            return "".join(t.text or "" for t in nodo.iter(f"{NS_MAIN}t")) if nodo is not None else ""
        v = celda.find(f"{NS_MAIN}v")
        if v is None or v.text is None:
            return None
        bruto = v.text
        if tipo == "s":
            try:
                return self._cadenas[int(bruto)]
            except (ValueError, IndexError):
                return ""
        if tipo == "b":
            return bruto == "1"
        if tipo in ("str", "e"):
            return bruto
        try:
            numero = float(bruto)
        except ValueError:
            return bruto
        try:
            estilo = int(celda.get("s", -1))
        except ValueError:
            estilo = -1
        if estilo in self._estilos_fecha and numero > 0:
            fecha = _serial_a_fecha(numero)
            if fecha is not None:
                return fecha
        return int(numero) if numero.is_integer() else numero

    def filas(self, hoja_idx: int = 0, limite: int | None = None):
        """Genera cada fila como lista de valores, respetando huecos."""
        hojas = self._rutas_hojas()
        if hoja_idx >= len(hojas):
            return
        raiz = self._xml(hojas[hoja_idx][1])
        if raiz is None:
            return
        for n, fila in enumerate(raiz.iter(f"{NS_MAIN}row")):
            if limite is not None and n >= limite:
                return
            valores: list[object] = []
            for celda in fila.findall(f"{NS_MAIN}c"):
                ref = celda.get("r") or ""
                idx = _col_a_indice(ref) if ref else len(valores)
                if idx < 0:
                    idx = len(valores)
                while len(valores) <= idx:
                    valores.append(None)
                valores[idx] = self._valor(celda)
            yield valores


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, (_dt.date, _dt.datetime)):
        return valor.isoformat()
    return str(valor).strip()


def detectar_cabecera(filas: list[list], max_filas: int = 12) -> int:
    """
    Estos volcados a veces llevan un titulo o filas en blanco arriba.
    La cabecera es la primera fila con varias celdas de texto no repetidas.
    """
    mejor_idx, mejor_puntos = 0, -1
    for i, fila in enumerate(filas[:max_filas]):
        textos = [_texto(c) for c in fila]
        no_vacias = [t for t in textos if t]
        if len(no_vacias) < 3:
            continue
        # Penaliza filas que ya son datos (muchos numeros/fechas).
        literales = sum(1 for c in fila if isinstance(c, str) and c.strip())
        puntos = len(set(no_vacias)) + literales
        if puntos > mejor_puntos:
            mejor_idx, mejor_puntos = i, puntos
    return mejor_idx


def leer_tabla(ruta: Path, hoja_idx: int = 0) -> list[dict]:
    """Lee la hoja y devuelve filas como dicts con la cabecera detectada."""
    with LibroExcel(ruta) as libro:
        filas = list(libro.filas(hoja_idx))
    if not filas:
        return []
    idx = detectar_cabecera(filas)
    cabecera_bruta = [_texto(c) for c in filas[idx]]
    cabecera, vistos = [], {}
    for i, nombre in enumerate(cabecera_bruta):
        nombre = nombre or f"col_{i + 1}"
        if nombre in vistos:  # cabeceras duplicadas: col, col_2, col_3...
            vistos[nombre] += 1
            nombre = f"{nombre}_{vistos[nombre]}"
        else:
            vistos[nombre] = 1
        cabecera.append(nombre)
    registros = []
    for fila in filas[idx + 1:]:
        if not any(_texto(c) for c in fila):
            continue
        registro = {}
        for i, clave in enumerate(cabecera):
            registro[clave] = fila[i] if i < len(fila) else None
        registros.append(registro)
    return registros


def hojas(ruta: Path) -> list[str]:
    """Nombres de las hojas, en orden."""
    with LibroExcel(ruta) as libro:
        return [n for n, _ in libro._rutas_hojas()]


def leer_hoja_preferida(ruta: Path, preferidas: list[str]) -> list[dict]:
    """
    Lee la hoja cuyo nombre case con alguna de las preferidas; si ninguna
    casa, la primera. Los volcados traen hojas de trabajo detras ('bae')
    que no deben confundirse con la buena.
    """
    nombres = hojas(ruta)
    objetivo = 0
    for pref in preferidas:
        pref_n = re.sub(r"[^a-z0-9]+", "", pref.lower())
        for i, nombre in enumerate(nombres):
            if re.sub(r"[^a-z0-9]+", "", (nombre or "").lower()) == pref_n:
                objetivo = i
                break
        else:
            continue
        break
    return leer_tabla(ruta, objetivo)
