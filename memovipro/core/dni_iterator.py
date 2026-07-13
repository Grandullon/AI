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
            # Escritura directa (NO _save): _save fusiona con el disco y
            # reincorporaría los OK viejos que justo estamos invalidando.
            self._escribir_directo()
        else:
            if self.fingerprint and not cargado["fingerprint"]:
                cargado["fingerprint"] = self.fingerprint
            self._data = cargado

    def _escribir_directo(self) -> None:
        """Escribe self._data tal cual (atómico, bajo lock), SIN fusionar.
        Para reset()/invalidación, donde queremos machacar el disco."""
        from .file_lock import file_lock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.path):
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            tmp.replace(self.path)

    def _save(self) -> None:
        from .file_lock import file_lock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Lock entre procesos: la GUI y una tarea programada podrían
        # escribir el mismo checkpoint a la vez. Dentro del lock RE-LEEMOS
        # el fichero y FUSIONAMOS con lo que tenemos en memoria antes de
        # escribir: si no, cada proceso machacaría los OK/KO del otro
        # (read-modify-write sin fusión) → DNIs reprocesados.
        with file_lock(self.path):
            self._fusionar_con_disco()
            tmp = self.path.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            tmp.replace(self.path)

    def _fusionar_con_disco(self) -> None:
        """Une los OK/KO en disco con los de memoria (debe llamarse ya bajo
        el file_lock). Preserva el orden y evita duplicados."""
        if not self.path.exists():
            return
        try:
            with self.path.open(encoding="utf-8") as f:
                disco = json.load(f)
        except Exception:
            return
        for clave in ("ok", "ko"):
            en_disco = disco.get(clave, []) or []
            actuales = self._data.get(clave, []) or []
            vistos = set(actuales)
            # Los de disco que no tengamos ya, se anteponen (los generó el
            # otro proceso antes que nuestra escritura).
            nuevos = [d for d in en_disco if d not in vistos]
            self._data[clave] = nuevos + actuales
        # Un DNI marcado OK en cualquiera de los dos ya no es KO.
        oks = set(self._data.get("ok", []))
        self._data["ko"] = [d for d in self._data.get("ko", []) if d not in oks]

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
        # Preservar el fingerprint: sin él, el siguiente _load con
        # fingerprint no detectaría cambios de la macro (el checkpoint
        # quedaría sin la clave y se trataría como "sin fingerprint").
        self._data = {"ok": [], "ko": [], "fingerprint": self.fingerprint or ""}
        # reset() vacía a propósito: escritura directa, sin fusionar con el
        # disco (que aún tiene los viejos OK/KO).
        self._escribir_directo()
