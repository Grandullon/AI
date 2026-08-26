# -*- coding: utf-8 -*-
"""
Datos inventados con la misma forma que los volcados reales.

Sirve para ensenar la herramienta (en una reunion, en un correo, en una
demostracion) sin sacar ni un solo dato real de la red del hospital.
Todos los nombres son ficticios y estan generados por combinacion.
"""
from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

from motor_it import FAMILIAS_DEFECTO, Snapshot, familia_de

SERVICIOS = [
    ("URGENCIAS", 79), ("COCINA", 36), ("MEDICINA INTENSIVA", 31),
    ("RADIODIAGNOSTICO", 24), ("MANTENIMIENTO", 15), ("ANESTESIA Y REANIMACION", 14),
    ("QUIROFANO", 22), ("TRAUMATOLOGIA", 18), ("MEDICINA INTERNA", 26),
    ("PEDIATRIA", 17), ("LIMPIEZA Y LENCERIA", 21), ("LABORATORIO", 13),
    ("ADMISION Y DOCUMENTACION", 12), ("SALUD MENTAL", 11), ("FARMACIA", 9),
    ("REHABILITACION", 8), ("NEUROLOGIA", 7), ("CARDIOLOGIA", 10),
    ("ONCOLOGIA", 9), ("GINECOLOGIA", 12), ("ALMACEN Y LOGISTICA", 8),
    ("CONSULTAS EXTERNAS", 19), ("HOSPITALIZACION MEDICA", 24), ("CELADURIA", 14),
]
DIRECCIONES = ["D. ENFERMERIA", "SSGG", "ACCESIBILIDAD", "S H.G.", "S. HG. Q",
               "S H.N.T.R.", "FORMACION", "S. HMI", "SALUD MENTAL", "PLATAFORMA"]
CENTROS = [("HG", 0.53), ("HNTR", 0.21), ("HMI", 0.13), ("GUADIX", 0.04),
           ("ED. GOB.", 0.04), ("ALCALA", 0.03), ("HDO", 0.02)]
CATEGORIAS = [("ENFERM./ATS", 0.25), ("T.C.AUX.ENF.", 0.23), ("CELADOR", 0.11),
              ("ADJ/ESP.AREA", 0.09), ("PINCHE", 0.06), ("ADMINISTRATIVO", 0.04),
              ("T.ESPECIALIS", 0.04), ("MED.FAM.SCCU", 0.02), ("LAVAND/PLANC", 0.02),
              ("TEC.FARMACIA", 0.01), ("FISIOTERAPEUTA", 0.02), ("MATRONA", 0.01)]
CODIGOS = [("ITE", 0.64), ("ITR", 0.08), ("ITA", 0.08), ("IMS", 0.065),
           ("ITN", 0.04), ("PAT", 0.03), ("PL3", 0.018), ("IMA", 0.013),
           ("PAA", 0.007), ("IMM", 0.005), ("ITI", 0.005), ("EMB", 0.004)]

NOMBRES = ["Ana", "Luis", "Carmen", "Miguel", "Rocio", "Javier", "Marta", "Antonio",
           "Lucia", "Sergio", "Pilar", "Diego", "Elena", "Rafael", "Nuria", "Alberto",
           "Beatriz", "Manuel", "Silvia", "Andres", "Teresa", "Ignacio", "Cristina"]
APELLIDOS = ["Ruiz", "Molina", "Delgado", "Serrano", "Cabrera", "Ortega", "Pastor",
             "Marin", "Herrera", "Vargas", "Castillo", "Reyes", "Iglesias", "Duran",
             "Santana", "Prieto", "Bravo", "Gallardo", "Peralta", "Quesada", "Aranda"]


def _elegir(pesos, rnd):
    total = sum(p for _, p in pesos)
    corte = rnd.uniform(0, total)
    acumulado = 0
    for valor, peso in pesos:
        acumulado += peso
        if corte <= acumulado:
            return valor
    return pesos[-1][0]


def _persona(i: int, rnd: random.Random, fecha: dt.date) -> dict:
    servicio = _elegir([(s, n) for s, n in SERVICIOS], rnd)
    cod = _elegir(CODIGOS, rnd)
    # Duraciones con cola larga: la mayoria cortas, unas pocas muy largas.
    dias = int(min(900, max(1, rnd.lognormvariate(4.1, 1.05))))
    cubierta = rnd.random() < (0.75 if dias > 90 else 0.34)
    return {
        "id": f"D:demo{i:05d}",
        "dni": f"{10000000 + i * 7 % 89999999}",
        "nombre": f"{rnd.choice(APELLIDOS)} {rnd.choice(APELLIDOS)}, {rnd.choice(NOMBRES)}",
        "edad": int(min(66, max(23, rnd.gauss(49, 10)))),
        "categoria": _elegir(CATEGORIAS, rnd),
        "especialidad": "",
        "servicio": servicio,
        "centro": _elegir(CENTROS, rnd),
        "direccion": rnd.choice(DIRECCIONES),
        "cod": cod,
        "familia": familia_de(cod, FAMILIAS_DEFECTO),
        "f_it": fecha - dt.timedelta(days=dias),
        "f_alta": None,
        "dias": dias,
        "sustituto": "SUSTITUTO ASIGNADO" if cubierta else "",
        "cubierta": cubierta,
        "motivo_sust": "I.T." if cubierta else "",
        "contrato_fin": None,
    }


def datos_demo(fecha_ref: dt.date, n_dias: int = 20, tamano: int = 600):
    """Devuelve (snapshots, altas_por_fecha, plantilla, incidencias)."""
    rnd = random.Random(20260826)
    fechas = []
    cursor = fecha_ref
    while len(fechas) < n_dias:
        if cursor.weekday() < 5:
            fechas.append(cursor)
        cursor -= dt.timedelta(days=1)
    fechas.reverse()

    poblacion = {}
    siguiente = 0
    for _ in range(tamano):
        p = _persona(siguiente, rnd, fechas[0])
        poblacion[p["id"]] = p
        siguiente += 1

    snapshots, altas_por_fecha = [], {}
    for indice, fecha in enumerate(fechas):
        if indice:
            # Cada dia: unas cuantas altas y unas cuantas bajas nuevas.
            n_altas = max(0, int(rnd.gauss(24, 7)))
            candidatos = sorted(poblacion.values(), key=lambda p: -p["dias"])[:400]
            for p in rnd.sample(candidatos, min(n_altas, len(candidatos))):
                alta = dict(p)
                alta["f_alta"] = fecha
                alta["dias"] = (fecha - p["f_it"]).days
                altas_por_fecha.setdefault(fecha, []).append(alta)
                poblacion.pop(p["id"], None)
            for _ in range(max(0, int(rnd.gauss(25, 8)))):
                p = _persona(siguiente, rnd, fecha)
                p["f_it"] = fecha - dt.timedelta(days=rnd.randint(0, 2))
                p["dias"] = (fecha - p["f_it"]).days
                poblacion[p["id"]] = p
                siguiente += 1
        registros = []
        for p in poblacion.values():
            r = dict(p)
            r["dias"] = (fecha - r["f_it"]).days
            registros.append(r)
        snapshots.append(Snapshot(fecha, registros,
                                  Path("DEMOSTRACION-datos-inventados.xlsx")))

    plantilla = {
        "total": 7420,
        "por_servicio": {s: max(12, int(n * rnd.uniform(9, 16))) for s, n in SERVICIOS},
        "por_direccion": {d: rnd.randint(180, 2600) for d in DIRECCIONES},
        "por_centro": {c: int(7420 * p) for c, p in CENTROS},
    }
    return snapshots, altas_por_fecha, plantilla, [
        "DEMOSTRACIÓN: los datos de este informe son inventados. Ninguna persona, "
        "servicio o cifra corresponde a la realidad."
    ]
