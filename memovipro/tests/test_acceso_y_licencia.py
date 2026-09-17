"""Acceso a la aplicación, licencia y textos de la interfaz."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.auth import (
    USUARIOS_POR_DEFECTO, cargar_usuarios, guardar_usuario, huella, verificar,
)


# ==================== credenciales ====================

def test_los_usuarios_de_fabrica_entran():
    assert verificar("admin", "Distrito11-*")
    assert verificar("franvida", "franvida")


def test_contrasena_incorrecta_no_entra():
    assert not verificar("admin", "distrito11-*")     # distingue mayúsculas
    assert not verificar("admin", "Distrito11")
    assert not verificar("admin", "")
    assert not verificar("franvida", "Franvida")


def test_usuario_inexistente_no_entra():
    assert not verificar("pepe", "loquesea")
    assert not verificar("", "Distrito11-*")


def test_el_usuario_no_distingue_mayusculas_ni_espacios():
    """Escribir «Admin» o « admin » a las 7 de la mañana no debe dejarte
    fuera; la contraseña sí distingue, como debe ser."""
    for escrito in ("ADMIN", "Admin", "  admin  "):
        assert verificar(escrito, "Distrito11-*")


def test_las_contrasenas_no_estan_en_claro_en_el_codigo():
    """Lo importante: ni abriendo el ejecutable con un editor se leen."""
    fuente = (ROOT / "core" / "auth.py").read_text(encoding="utf-8")
    assert "Distrito11-*" not in fuente
    assert "franvida\"" not in fuente.replace('"franvida":', "")
    # Lo que se guarda son huellas en base64, no texto
    for h in USUARIOS_POR_DEFECTO.values():
        assert len(h) > 40 and h.endswith("=")


def test_la_huella_no_se_puede_deshacer():
    """Dos usuarios con la misma contraseña no comparten huella (la sal
    depende del usuario), así que no se puede deducir una de otra."""
    assert huella("admin", "misma") != huella("franvida", "misma")
    assert huella("admin", "misma") == huella("admin", "misma")


def test_se_pueden_cambiar_contrasenas_sin_recompilar(tmp_path):
    guardar_usuario("nuevo", "Clave Larga 123", tmp_path)
    assert verificar("nuevo", "Clave Larga 123", tmp_path)
    assert not verificar("nuevo", "otra", tmp_path)
    # Y los de fábrica siguen valiendo
    assert verificar("admin", "Distrito11-*", tmp_path)


def test_cambiar_la_contrasena_de_un_usuario_de_fabrica(tmp_path):
    guardar_usuario("admin", "OtraDistinta9!", tmp_path)
    assert verificar("admin", "OtraDistinta9!", tmp_path)
    assert not verificar("admin", "Distrito11-*", tmp_path)


def test_un_fichero_corrupto_no_te_deja_fuera(tmp_path):
    (tmp_path / "usuarios.json").write_text("{esto no es json", encoding="utf-8")
    assert verificar("admin", "Distrito11-*", tmp_path)
    assert cargar_usuarios(tmp_path) == USUARIOS_POR_DEFECTO


def test_el_fichero_guardado_tampoco_lleva_la_contrasena(tmp_path):
    guardar_usuario("nuevo", "SecretoDelHospital", tmp_path)
    contenido = (tmp_path / "usuarios.json").read_text(encoding="utf-8")
    assert "SecretoDelHospital" not in contenido


# ==================== licencia ====================

def test_existe_la_licencia_y_nombra_al_autor():
    licencia = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Francisco J. Vidal Gázquez" in licencia
    assert "Todos los derechos reservados" in licencia
    # Que diga expresamente qué no se puede hacer
    for prohibido in ("distribución", "modificación", "ingeniería inversa"):
        assert prohibido in licencia.lower()


def test_la_licencia_se_empaqueta_en_el_exe():
    for spec in ("memovipro-gui.spec", "memovipro-run.spec"):
        assert "'LICENSE'" in (ROOT / spec).read_text(encoding="utf-8")


def test_la_autoria_aparece_en_la_aplicacion():
    about = (ROOT / "ui" / "about_panel.py").read_text(encoding="utf-8")
    assert "Francisco J. Vidal Gázquez" in about
    assert "derechos reservados" in about.lower()
    login = (ROOT / "ui" / "login_dialog.py").read_text(encoding="utf-8")
    assert "Francisco J. Vidal Gázquez" in login


# ==================== textos de la interfaz ====================

def test_no_queda_jerga_en_los_textos_visibles():
    """Nombres como «step-through» o «dashboard» no dicen nada a quien
    usa el programa."""
    import re
    jerga = ("step-through", "dashboard", "breakpoint", "fallback", "dry-run")
    encontrados = []
    for fichero in (ROOT / "ui").glob("*.py"):
        for linea in fichero.read_text(encoding="utf-8").splitlines():
            visible = re.findall(r'(?:QPushButton|QLabel|addTab|setWindowTitle|setToolTip)\(\s*[fr]?"([^"]{3,})"', linea)
            for texto in visible:
                for palabra in jerga:
                    if palabra in texto.lower():
                        encontrados.append(f"{fichero.name}: {texto}")
    assert not encontrados, "Jerga en textos visibles: " + "; ".join(encontrados)


def test_los_iconos_llevan_doble_espacio():
    """Convenio de la interfaz: «🔴  Grabar», no «🔴 Grabar». Con un solo
    espacio el icono queda pegado al texto y se lee peor."""
    import re
    malos = []
    for fichero in (ROOT / "ui").glob("*.py"):
        for texto in re.findall(r'QPushButton\("([^"]+)"\)',
                                fichero.read_text(encoding="utf-8")):
            if not texto or texto[0].isascii():
                continue
            if len(texto) > 2 and texto[1] == " " and texto[2] != " ":
                malos.append(f"{fichero.name}: {texto}")
    assert not malos, "Iconos con un solo espacio: " + "; ".join(malos)
