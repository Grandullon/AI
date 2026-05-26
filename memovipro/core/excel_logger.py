from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


HEADERS = [
    "Fecha/Hora",
    "DNI",
    "Macro",
    "Paso #",
    "Tipo paso",
    "Tipo error",
    "Título popup",
    "Texto popup",
    "Screenshot",
    "Estado",
    "Detalle",
]

HEADER_FILL = PatternFill("solid", fgColor="2C3E50")
HEADER_FONT = Font(bold=True, color="FFFFFF")
OK_FILL = PatternFill("solid", fgColor="D5F5E3")
ERR_FILL = PatternFill("solid", fgColor="FADBD8")


@dataclass
class Incidencia:
    dni: str
    macro: str
    paso_idx: int
    paso_tipo: str
    tipo_error: str
    titulo_popup: str = ""
    texto_popup: str = ""
    screenshot_path: str = ""
    estado: str = "ERROR"
    detalle: str = ""
    timestamp: datetime | None = None

    def row(self) -> list:
        ts = self.timestamp or datetime.now()
        return [
            ts.strftime("%Y-%m-%d %H:%M:%S"),
            self.dni,
            self.macro,
            self.paso_idx,
            self.paso_tipo,
            self.tipo_error,
            self.titulo_popup,
            self.texto_popup,
            self.screenshot_path,
            self.estado,
            self.detalle,
        ]


class ExcelLogger:
    """Acumula incidencias en un Excel diario. Thread-safe."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = Lock()
        self._ensure_workbook()

    def _ensure_workbook(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            wb = Workbook()
            ws = wb.active
            ws.title = "Incidencias"
            ws.append(HEADERS)
            for col_idx, _ in enumerate(HEADERS, start=1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = HEADER_FILL
                cell.font = HEADER_FONT
                cell.alignment = Alignment(horizontal="center", vertical="center")
            self._autosize(ws)
            ws.freeze_panes = "A2"
            wb.save(self.path)

    @staticmethod
    def _autosize(ws) -> None:
        widths = [20, 14, 24, 8, 22, 18, 30, 60, 50, 12, 40]
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w

    def append(self, inc: Incidencia) -> int:
        """Añade una incidencia. Devuelve el número de fila escrita.

        Protegido con un lock intra-proceso (threading) Y entre procesos
        (file_lock) para que una tarea programada y la GUI no corrompan
        el Excel escribiendo a la vez.
        """
        from .file_lock import file_lock
        with self._lock, file_lock(self.path):
            wb = load_workbook(self.path)
            ws = wb["Incidencias"]
            row = inc.row()
            ws.append(row)
            row_idx = ws.max_row
            fill = OK_FILL if inc.estado.upper() == "OK" else ERR_FILL
            for col in range(1, len(HEADERS) + 1):
                ws.cell(row=row_idx, column=col).fill = fill
            if inc.screenshot_path:
                p = Path(inc.screenshot_path)
                if p.exists():
                    cell = ws.cell(row=row_idx, column=HEADERS.index("Screenshot") + 1)
                    cell.hyperlink = str(p.resolve())
                    cell.value = p.name
                    cell.font = Font(color="1A5276", underline="single")
            wb.save(self.path)
            return row_idx

    def append_ok(self, dni: str, macro: str, detalle: str = "") -> int:
        return self.append(
            Incidencia(
                dni=dni,
                macro=macro,
                paso_idx=-1,
                paso_tipo="",
                tipo_error="",
                estado="OK",
                detalle=detalle,
            )
        )

    def count_by_dni(self) -> dict[str, int]:
        with self._lock:
            wb = load_workbook(self.path, read_only=True)
            ws = wb["Incidencias"]
            counts: dict[str, int] = {}
            for row in ws.iter_rows(min_row=2, values_only=True):
                if not row or not row[1]:
                    continue
                counts[row[1]] = counts.get(row[1], 0) + 1
            return counts


def default_log_path(carpeta: str | Path, patron: str = "incidencias_{YYYYMMDD}.xlsx") -> Path:
    name = patron.replace("{YYYYMMDD}", datetime.now().strftime("%Y%m%d"))
    return Path(carpeta) / name
