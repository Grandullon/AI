from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


def _detect_dni_column(df: pd.DataFrame) -> str:
    candidatos = ["DNI", "dni", "Dni", "NIF", "nif", "Documento"]
    for c in candidatos:
        if c in df.columns:
            return c
    return df.columns[0]


def cargar_dnis(path: str | Path, columna: str | None = None) -> list[dict]:
    """Lee Excel/CSV y devuelve lista de diccionarios con al menos la clave 'DNI'.

    Cada fila se incluye entera para que la macro pueda usar otros campos
    como placeholders (`{NOMBRE}`, `{SERVICIO}`, etc.).
    """
    path = Path(path)
    if path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path, dtype=str)
    elif path.suffix.lower() == ".csv":
        df = pd.read_csv(path, dtype=str)
    else:
        raise ValueError(f"Formato no soportado: {path.suffix}")

    col = columna or _detect_dni_column(df)
    if col not in df.columns:
        raise KeyError(f"No se encuentra columna {col!r}. Columnas: {list(df.columns)}")

    df = df.fillna("")
    df = df.rename(columns={col: "DNI"})
    df["DNI"] = df["DNI"].astype(str).str.strip().str.upper()
    df = df[df["DNI"] != ""]
    return df.to_dict(orient="records")


class Checkpoint:
    """Mantiene la lista de DNIs ya completados para una macro y día.

    Permite reanudar una ejecución sin repetir los OK. Si se pasa
    `macro_fingerprint`, se guarda dentro del checkpoint: cuando se carga
    uno antiguo con fingerprint distinto, los OK previos se descartan
    automáticamente (los pasos cambiaron, ya no son comparables).
    """

    def __init__(
        self,
        macro: str,
        path_dir: str | Path,
        fecha: str | None = None,
        macro_fingerprint: str | None = None,
    ):
        self.macro = macro
        self.fecha = fecha or datetime.now().strftime("%Y%m%d")
        self.fingerprint = macro_fingerprint
        self.path = Path(path_dir) / f"checkpoint_{self._sanitize(macro)}_{self.fecha}.json"
        self._data = {"ok": [], "ko": [], "fingerprint": ""}
        self.invalidado = False
        self._load()

    @staticmethod
    def _sanitize(name: str) -> str:
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)

    def _load(self) -> None:
        if not self.path.exists():
            if self.fingerprint:
                self._data["fingerprint"] = self.fingerprint
            return
        try:
            with self.path.open(encoding="utf-8") as f:
                cargado = json.load(f)
        except Exception:
            cargado = {"ok": [], "ko": [], "fingerprint": ""}
        cargado.setdefault("ok", [])
        cargado.setdefault("ko", [])
        cargado.setdefault("fingerprint", "")

        if self.fingerprint and cargado["fingerprint"] and cargado["fingerprint"] != self.fingerprint:
            self.invalidado = True
            self._data = {"ok": [], "ko": [], "fingerprint": self.fingerprint}
            self._save()
        else:
            if self.fingerprint and not cargado["fingerprint"]:
                cargado["fingerprint"] = self.fingerprint
            self._data = cargado

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
        tmp.replace(self.path)

    def marcar_ok(self, dni: str) -> None:
        if dni not in self._data["ok"]:
            self._data["ok"].append(dni)
        if dni in self._data["ko"]:
            self._data["ko"].remove(dni)
        self._save()

    def marcar_ko(self, dni: str) -> None:
        if dni not in self._data["ko"]:
            self._data["ko"].append(dni)
        self._save()

    def hechos(self) -> set[str]:
        return set(self._data["ok"])

    def fallidos(self) -> set[str]:
        return set(self._data["ko"])

    def pendientes(self, todos: list[dict]) -> list[dict]:
        hechos = self.hechos()
        return [r for r in todos if r["DNI"] not in hechos]

    def reset(self) -> None:
        self._data = {"ok": [], "ko": []}
        self._save()
