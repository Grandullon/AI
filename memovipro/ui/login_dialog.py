"""Pantalla de acceso.

Aparece antes que la ventana principal. Su papel es evitar que alguien
use el programa si te levantas del sitio; la protección de los datos es
la del equipo (ver core/auth).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from core.auth import verificar

from .theme import AZUL, BLANCO, BORDE, PIZARRA, ROJO, TEXTO, TEXTO_SUAVE

INTENTOS_MAXIMOS = 5

ESTILO = f"""
QDialog {{ background: {PIZARRA}; }}
QFrame#tarjeta {{
    background: {BLANCO};
    border-radius: 10px;
    border: 1px solid {BORDE};
}}
QLabel#marca {{ font-size: 26px; font-weight: 700; color: {PIZARRA}; }}
QLabel#lema {{ font-size: 12px; color: {TEXTO_SUAVE}; }}
QLabel#error {{ font-size: 12px; color: {ROJO}; font-weight: 600; }}
QLabel#pie {{ font-size: 10px; color: {TEXTO_SUAVE}; }}
QLineEdit {{
    background: {BLANCO}; color: {TEXTO};
    border: 1px solid {BORDE}; border-radius: 6px;
    padding: 9px 10px; font-size: 13px;
}}
QLineEdit:focus {{ border-color: {AZUL}; }}
QPushButton#entrar {{
    background: {AZUL}; color: {BLANCO}; border: none;
    border-radius: 6px; padding: 10px; font-size: 14px; font-weight: 700;
}}
QPushButton#entrar:hover {{ background: #1a5fd0; }}
"""


class LoginDialog(QDialog):
    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self.usuario_autenticado = ""
        self._intentos = 0

        self.setWindowTitle("MemoviPro — Acceso")
        self.setFixedSize(380, 400)
        self.setStyleSheet(ESTILO)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        fondo = QVBoxLayout(self)
        fondo.setContentsMargins(22, 22, 22, 22)

        tarjeta = QFrame()
        tarjeta.setObjectName("tarjeta")
        col = QVBoxLayout(tarjeta)
        col.setContentsMargins(26, 26, 26, 22)
        col.setSpacing(10)

        marca = QLabel("MemoviPro")
        marca.setObjectName("marca")
        marca.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(marca)

        lema = QLabel("Automatización de tareas de escritorio")
        lema.setObjectName("lema")
        lema.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(lema)

        col.addSpacing(16)

        self.usuario = QLineEdit()
        self.usuario.setPlaceholderText("Usuario")
        col.addWidget(self.usuario)

        self.contrasena = QLineEdit()
        self.contrasena.setPlaceholderText("Contraseña")
        self.contrasena.setEchoMode(QLineEdit.EchoMode.Password)
        col.addWidget(self.contrasena)

        self.error = QLabel("")
        self.error.setObjectName("error")
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error.setWordWrap(True)
        col.addWidget(self.error)

        self.boton = QPushButton("Entrar")
        self.boton.setObjectName("entrar")
        self.boton.setDefault(True)
        self.boton.clicked.connect(self._entrar)
        col.addWidget(self.boton)

        col.addStretch()

        pie = QLabel(
            "© 2026 Francisco J. Vidal Gázquez\nTodos los derechos reservados"
        )
        pie.setObjectName("pie")
        pie.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(pie)

        fondo.addWidget(tarjeta)

        # Enter en cualquiera de los dos campos entra.
        self.usuario.returnPressed.connect(self._entrar)
        self.contrasena.returnPressed.connect(self._entrar)
        self.usuario.setFocus()

    def _entrar(self) -> None:
        usuario = self.usuario.text().strip()
        clave = self.contrasena.text()
        if verificar(usuario, clave, self.data_dir):
            self.usuario_autenticado = usuario.lower()
            self.accept()
            return
        self._intentos += 1
        self.contrasena.clear()
        self.contrasena.setFocus()
        restantes = INTENTOS_MAXIMOS - self._intentos
        if restantes <= 0:
            # No es una medida de seguridad fuerte (basta con volver a
            # abrir), pero corta el intento a ciegas de quien pasaba por
            # ahí, que es de lo que protege esta pantalla.
            self.error.setText("Demasiados intentos. Se cierra el programa.")
            self.boton.setEnabled(False)
            self.reject()
            return
        # No se dice si ha fallado el usuario o la contraseña: decirlo
        # confirmaría a quién existe.
        self.error.setText(
            f"Usuario o contraseña incorrectos. Quedan {restantes} intento(s)."
        )
