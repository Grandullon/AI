"""Aspecto visual de MemoviPro: paleta, tipografía y hoja de estilos.

Todo el color vive aquí para que la aplicación se vea como una sola cosa
y no como pantallas sueltas. Si algún día hay que cambiar el aspecto, se
cambia en este fichero y no en ocho.
"""
from __future__ import annotations

# Paleta. Azul pizarra sobrio de fondo para las cabeceras y un gris muy
# claro para el lienzo: lo que se lee mucho rato tiene que cansar poco.
AZUL = "#1f6feb"          # acción principal
AZUL_OSCURO = "#1a5fd0"
PIZARRA = "#1e2a38"       # cabeceras, barras
PIZARRA_CLARA = "#2c3e50"
LIENZO = "#f4f6f9"
BORDE = "#d4dae2"
TEXTO = "#1e2a38"
TEXTO_SUAVE = "#5b6b7c"
BLANCO = "#ffffff"

VERDE = "#1e9e6a"         # ejecutar / confirmar
ROJO = "#d64545"          # grabar / parar
AMBAR = "#e08b1e"         # avisos
MORADO = "#7b5ea7"        # herramientas
TEAL = "#0f9b8e"          # depuración

RADIO = "6px"

APP_STYLE = f"""
QMainWindow, QDialog, QWidget {{
    background-color: {LIENZO};
    color: {TEXTO};
    font-family: "Segoe UI", "Inter", Arial, sans-serif;
    font-size: 13px;
}}

/* ---- Pestañas ---- */
QTabWidget::pane {{
    border: 1px solid {BORDE};
    border-radius: {RADIO};
    background: {BLANCO};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXTO_SUAVE};
    padding: 9px 18px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {AZUL};
    border-bottom: 2px solid {AZUL};
}}
QTabBar::tab:!selected:hover {{ color: {TEXTO}; }}

/* ---- Botones ---- */
QPushButton {{
    background-color: {BLANCO};
    color: {TEXTO};
    border: 1px solid {BORDE};
    padding: 7px 14px;
    border-radius: {RADIO};
    font-weight: 600;
}}
QPushButton:hover {{ background-color: #eaeef4; border-color: #b9c2cd; }}
QPushButton:pressed {{ background-color: #dfe5ec; }}
QPushButton:disabled {{
    background-color: #eef1f5; color: #a9b4c0; border-color: #e2e7ee;
}}
QPushButton[tono="primario"] {{
    background-color: {AZUL}; color: {BLANCO}; border-color: {AZUL_OSCURO};
}}
QPushButton[tono="primario"]:hover {{ background-color: {AZUL_OSCURO}; }}
QPushButton[tono="peligro"] {{
    background-color: {ROJO}; color: {BLANCO}; border-color: #bb3a3a;
}}
QPushButton[tono="peligro"]:hover {{ background-color: #bb3a3a; }}
QPushButton[tono="exito"] {{
    background-color: {VERDE}; color: {BLANCO}; border-color: #17845a;
}}
QPushButton[tono="exito"]:hover {{ background-color: #17845a; }}
QPushButton[tono="depurar"] {{
    background-color: {TEAL}; color: {BLANCO}; border-color: #0c8177;
}}
QPushButton[tono="depurar"]:hover {{ background-color: #0c8177; }}
QPushButton[tono="herramienta"] {{
    background-color: {MORADO}; color: {BLANCO}; border-color: #674e8e;
}}
QPushButton[tono="herramienta"]:hover {{ background-color: #674e8e; }}
/* Botón cuadrado de un solo símbolo (refrescar): sin relleno lateral,
   que era lo que cortaba el icono. */
QPushButton[tono="icono"] {{ padding: 4px; font-size: 15px; }}

/* ---- Campos ---- */
QLabel {{ color: {TEXTO}; background: transparent; }}
QLabel[papel="seccion"] {{
    color: {TEXTO_SUAVE}; font-size: 11px; font-weight: 700;
    letter-spacing: 0.6px; text-transform: uppercase;
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTimeEdit,
QTextEdit, QPlainTextEdit {{
    background: {BLANCO};
    color: {TEXTO};
    border: 1px solid {BORDE};
    padding: 6px 8px;
    border-radius: {RADIO};
    selection-background-color: {AZUL};
    selection-color: {BLANCO};
}}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {AZUL};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {BLANCO}; color: {TEXTO};
    border: 1px solid {BORDE};
    selection-background-color: {AZUL}; selection-color: {BLANCO};
}}

/* ---- Tablas y listas ---- */
QTableWidget, QListWidget, QTreeWidget {{
    background-color: {BLANCO};
    color: {TEXTO};
    border: 1px solid {BORDE};
    border-radius: {RADIO};
    gridline-color: #eef1f5;
    alternate-background-color: #fafbfd;
    selection-background-color: #dbe9fd;
    selection-color: {TEXTO};
}}
QTableWidget::item, QListWidget::item {{ padding: 3px; }}
QTableWidget::item:selected, QListWidget::item:selected {{
    background-color: #dbe9fd; color: {TEXTO};
}}
QHeaderView::section {{
    background-color: {PIZARRA};
    color: {BLANCO};
    padding: 7px 8px;
    border: none;
    border-right: 1px solid #33455a;
    font-weight: 600;
}}
QHeaderView {{ background-color: {PIZARRA}; }}

/* ---- Varios ---- */
QProgressBar {{
    border: 1px solid {BORDE}; border-radius: {RADIO};
    text-align: center; background: {BLANCO}; color: {TEXTO};
    height: 20px;
}}
QProgressBar::chunk {{ background-color: {AZUL}; border-radius: 5px; }}
QStatusBar {{
    color: {TEXTO_SUAVE};
    background: {BLANCO};
    border-top: 1px solid {BORDE};
}}
QCheckBox, QRadioButton {{ color: {TEXTO}; background: transparent; padding: 2px; }}
QGroupBox {{
    border: 1px solid {BORDE}; border-radius: {RADIO};
    margin-top: 12px; padding-top: 10px; font-weight: 600;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
QMessageBox {{ background-color: {LIENZO}; }}
QMessageBox QLabel {{ color: {TEXTO}; }}
QScrollBar:vertical {{
    background: transparent; width: 11px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #c3ccd7; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #a9b4c0; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; }}
QScrollBar::handle:horizontal {{
    background: #c3ccd7; border-radius: 5px; min-width: 30px;
}}
QToolTip {{
    background-color: {PIZARRA}; color: {BLANCO};
    border: none; padding: 6px 8px; border-radius: 4px;
}}
"""


def aplicar_tono(boton, tono: str) -> None:
    """Marca un botón con un tono de la paleta ('primario', 'peligro'...).

    Se usa una propiedad de Qt en vez de una hoja de estilos por botón:
    así todos los botones del mismo tipo se ven igual y el color se
    cambia en un solo sitio.
    """
    boton.setProperty("tono", tono)
