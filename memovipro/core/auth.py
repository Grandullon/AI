"""Control de acceso a MemoviPro.

Las contraseñas NO se guardan en claro en ningún sitio: de cada una se
guarda solo una huella PBKDF2-SHA256 con 200.000 iteraciones, que no se
puede deshacer. Ni abriendo el ejecutable con un editor ni mirando el
código se puede leer una contraseña.

Alcance de esta protección — conviene tenerlo claro:
es una puerta para que nadie use el programa sin permiso si te levantas
del sitio, no un cifrado de los datos. Quien tenga acceso a los ficheros
del equipo puede llegar a las macros y a los registros por su cuenta. Si
manejas datos de pacientes, la protección de verdad es la del equipo
(sesión de Windows bloqueada y disco cifrado).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

ITERACIONES = 200_000
_PREFIJO_SAL = "memovipro:"

# Usuarios de fábrica. El valor es la huella, nunca la contraseña.
USUARIOS_POR_DEFECTO = {
    "admin": "6YcNe4WnEjWRMrSgZhFyCOEIeBlemLZCA61QvJOxgLg=",
    "franvida": "4rJ2IQsC4yFs9/nN1zUZg5e+cfs2nD4EHUz8mCSPpVU=",
}

# Fichero opcional junto a los datos, por si algún día se cambian las
# contraseñas o se añade gente sin recompilar. Mismo formato.
NOMBRE_FICHERO = "usuarios.json"


def _sal(usuario: str) -> bytes:
    """Sal derivada del usuario: dos personas con la misma contraseña no
    comparten huella, y no hay que guardar la sal aparte."""
    return hashlib.sha256((_PREFIJO_SAL + usuario.lower()).encode()).digest()[:16]


def huella(usuario: str, contrasena: str) -> str:
    """Huella irreversible de una contraseña."""
    bruto = hashlib.pbkdf2_hmac(
        "sha256", (contrasena or "").encode("utf-8"),
        _sal(usuario), ITERACIONES,
    )
    return base64.b64encode(bruto).decode()


def cargar_usuarios(data_dir=None) -> dict[str, str]:
    """Usuarios de fábrica, más los del fichero si existe."""
    usuarios = dict(USUARIOS_POR_DEFECTO)
    if data_dir is None:
        return usuarios
    try:
        ruta = Path(data_dir) / NOMBRE_FICHERO
        if ruta.is_file():
            with ruta.open(encoding="utf-8") as f:
                extra = json.load(f)
            if isinstance(extra, dict):
                usuarios.update({
                    str(u).lower(): str(h) for u, h in extra.items()
                })
    except Exception:
        pass        # un fichero corrupto no debe dejarte fuera
    return usuarios


def verificar(usuario: str, contrasena: str, data_dir=None) -> bool:
    """¿Son correctas estas credenciales?

    La comparación es en tiempo constante (`compare_digest`) para no
    filtrar por lo que tarda en responder.
    """
    if not usuario:
        return False
    usuarios = cargar_usuarios(data_dir)
    esperada = usuarios.get(usuario.strip().lower())
    if not esperada:
        # Calculamos igualmente una huella para que un usuario que no
        # existe tarde lo mismo que uno que sí.
        huella(usuario, contrasena)
        return False
    return hmac.compare_digest(esperada, huella(usuario.strip().lower(), contrasena))


def guardar_usuario(usuario: str, contrasena: str, data_dir) -> None:
    """Crea o cambia la contraseña de un usuario en el fichero local."""
    ruta = Path(data_dir) / NOMBRE_FICHERO
    datos = {}
    try:
        if ruta.is_file():
            with ruta.open(encoding="utf-8") as f:
                cargado = json.load(f)
            if isinstance(cargado, dict):
                datos = cargado
    except Exception:
        datos = {}
    datos[usuario.strip().lower()] = huella(usuario.strip().lower(), contrasena)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2)
    tmp.replace(ruta)
