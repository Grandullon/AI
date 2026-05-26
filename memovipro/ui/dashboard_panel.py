"""Pestaña Dashboard: estadísticas históricas de ejecuciones.

Muestra, leyendo los incidencias_*.xlsx de data/:
- Resumen global (total OK/KO, tasa de éxito) de los últimos N días.
- Tabla por macro ordenada por fragilidad (peor tasa de éxito primero).
- Top de errores más frecuentes.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.dashboard import agregar_incidencias


class DashboardPanel(QWidget):
    def __init__(self, data_dir: Path):
        super().__init__()
        self.data_dir = data_dir

        layout = QVBoxLayout(self)

        cab = QHBoxLayout()
        cab.addWidget(QLabel("<b>Dashboard de ejecuciones</b>"))
        cab.addStretch()
        cab.addWidget(QLabel("Últimos:"))
        self.dias_combo = QComboBox()
        self.dias_combo.addItem("7 días", 7)
        self.dias_combo.addItem("30 días", 30)
        self.dias_combo.addItem("90 días", 90)
        self.dias_combo.addItem("365 días", 365)
        self.dias_combo.setCurrentIndex(1)
        self.dias_combo.currentIndexChanged.connect(self.refresh)
        cab.addWidget(self.dias_combo)
        refrescar = QPushButton("↻ Refrescar")
        refrescar.clicked.connect(self.refresh)
        cab.addWidget(refrescar)
        layout.addLayout(cab)

        self.resumen = QLabel("")
        self.resumen.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.resumen)

        # Tabla por macro
        layout.addWidget(QLabel("<b>Por macro</b> (las más frágiles arriba)"))
        self.tabla_macros = QTableWidget(0, 5)
        self.tabla_macros.setHorizontalHeaderLabels(
            ["Macro", "Ejecuciones", "OK", "KO", "Tasa éxito"]
        )
        self.tabla_macros.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla_macros.setAlternatingRowColors(True)
        self.tabla_macros.verticalHeader().setVisible(False)
        layout.addWidget(self.tabla_macros, 1)

        # Top errores
        layout.addWidget(QLabel("<b>Errores más frecuentes</b>"))
        self.tabla_errores = QTableWidget(0, 2)
        self.tabla_errores.setHorizontalHeaderLabels(["Error", "Veces"])
        self.tabla_errores.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tabla_errores.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tabla_errores.setAlternatingRowColors(True)
        self.tabla_errores.verticalHeader().setVisible(False)
        layout.addWidget(self.tabla_errores, 1)

        self.refresh()

    def refresh(self):
        dias = self.dias_combo.currentData() or 30
        stats = agregar_incidencias(self.data_dir, dias=dias)

        if stats.total == 0:
            self.resumen.setText(
                "<i>Aún no hay datos de ejecuciones en este periodo. "
                "Reproduce alguna macro y vuelve aquí.</i>"
            )
            self.tabla_macros.setRowCount(0)
            self.tabla_errores.setRowCount(0)
            return

        tasa = (stats.total_ok / stats.total * 100.0) if stats.total else 0.0
        color = "#27ae60" if tasa >= 90 else ("#e67e22" if tasa >= 70 else "#c0392b")
        self.resumen.setText(
            f"Periodo: <b>{stats.desde} → {stats.hasta}</b> "
            f"({stats.archivos_leidos} días con actividad)<br>"
            f"Total: <b>{stats.total}</b> · "
            f"OK: <b style='color:#27ae60'>{stats.total_ok}</b> · "
            f"KO: <b style='color:#c0392b'>{stats.total_ko}</b> · "
            f"Tasa éxito global: <b style='color:{color}'>{tasa:.1f}%</b>"
        )

        # Tabla macros
        self.tabla_macros.setRowCount(0)
        for ms in stats.por_macro:
            r = self.tabla_macros.rowCount()
            self.tabla_macros.insertRow(r)
            self.tabla_macros.setItem(r, 0, QTableWidgetItem(ms.macro))
            self.tabla_macros.setItem(r, 1, QTableWidgetItem(str(ms.total)))
            self.tabla_macros.setItem(r, 2, QTableWidgetItem(str(ms.ok)))
            self.tabla_macros.setItem(r, 3, QTableWidgetItem(str(ms.ko)))
            tasa_item = QTableWidgetItem(f"{ms.tasa_exito:.0f}%")
            if ms.tasa_exito >= 90:
                tasa_item.setForeground(QColor("#1e8449"))
            elif ms.tasa_exito >= 70:
                tasa_item.setForeground(QColor("#b9770e"))
            else:
                tasa_item.setForeground(QColor("#c0392b"))
            self.tabla_macros.setItem(r, 4, tasa_item)

        # Tabla errores
        self.tabla_errores.setRowCount(0)
        for motivo, veces in stats.top_errores:
            r = self.tabla_errores.rowCount()
            self.tabla_errores.insertRow(r)
            self.tabla_errores.setItem(r, 0, QTableWidgetItem(motivo))
            self.tabla_errores.setItem(r, 1, QTableWidgetItem(str(veces)))
