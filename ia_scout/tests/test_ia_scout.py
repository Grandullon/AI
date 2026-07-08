"""Tests unitarios de funciones puras — sin llamadas de red."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ia_scout as s  # noqa: E402


def test_generar_hash_estable_y_20_chars():
    h1 = s.generar_hash("Hola Mundo", "https://ex.com/a")
    h2 = s.generar_hash("Hola Mundo", "https://ex.com/a")
    assert h1 == h2
    assert len(h1) == 20
    assert "+" not in h1 and "/" not in h1 and "=" not in h1


def test_generar_hash_case_insensitive_titulo_y_url():
    a = s.generar_hash("Un Título", "https://ex.com/A")
    b = s.generar_hash("un título", "https://ex.com/a")
    assert a == b


def test_extraer_keywords_stopwords_y_dedup():
    kw = s.extraer_keywords(
        "The notebook workflow with notebook and Claude is powerful workflow"
    )
    tokens = [t for t in kw.split(",") if t]
    assert "the" not in tokens
    assert "and" not in tokens
    assert tokens.count("notebook") == 1
    assert tokens.count("workflow") == 1
    assert 0 < len(tokens) <= 8


def test_es_duplicado_por_hash_conocido():
    item = {"content_hash": "abc", "titulo": "Un titulo"}
    conocidos, batch, vistos = {"abc"}, set(), set()
    assert s.es_duplicado(item, conocidos, batch, vistos) is True


def test_es_duplicado_por_hash_batch():
    item = {"content_hash": "def", "titulo": "Otro titulo"}
    conocidos, batch, vistos = set(), set(), set()
    assert s.es_duplicado(item, conocidos, batch, vistos) is False
    assert s.es_duplicado(item, conocidos, batch, vistos) is True


def test_es_duplicado_por_titulo_normalizado():
    # Misma normalización (mayúsculas/puntuación varían, acentos se preservan)
    a = {"content_hash": "h1", "titulo": "NotebookLM: nueva función!"}
    b = {"content_hash": "h2", "titulo": "notebooklm nueva función"}
    conocidos, batch, vistos = set(), set(), set()
    assert s.es_duplicado(a, conocidos, batch, vistos) is False
    assert s.es_duplicado(b, conocidos, batch, vistos) is True


def test_parsear_respuesta_claude_json_valido():
    raw = """```json
    {"vale":"SI","formato":"largo","puntuacion":8,"gancho":"Prueba","angulo":"algo"}
    ```"""
    r = s.parsear_respuesta_claude(raw)
    assert r["vale"] == "SI"
    assert r["formato"] == "largo"
    assert r["puntuacion"] == 8
    assert r["gancho"] == "Prueba"


def test_parsear_respuesta_claude_formato_invalido_se_normaliza():
    raw = '{"vale":"YES","formato":"video","puntuacion":15}'
    r = s.parsear_respuesta_claude(raw)
    assert r["vale"] == "SI"
    assert r["formato"] == "ninguno"
    assert r["puntuacion"] == 10  # clamp


def test_parsear_respuesta_claude_texto_basura():
    r = s.parsear_respuesta_claude("no hay json aquí")
    assert r["vale"] == "NO"
    assert r["formato"] == "ninguno"
    assert r["puntuacion"] == 0


def test_formatear_mensaje_telegram_orden_y_html():
    noticias = [
        {
            "formato": "short",
            "puntuacion": 5,
            "fuente": "r/ChatGPT",
            "url": "https://ex.com/s",
            "titulo": "Short bajo",
            "gancho": "gancho-s",
            "angulo": "algo corto",
            "fecha_detectado": "2026-07-08 10:00",
        },
        {
            "formato": "largo",
            "puntuacion": 9,
            "fuente": "YT:PaulJames",
            "url": "https://ex.com/l1",
            "titulo": "Largo top",
            "gancho": "gancho-l1",
            "angulo": "análisis extenso",
            "fecha_detectado": "2026-07-08 09:30",
        },
        {
            "formato": "largo",
            "puntuacion": 7,
            "fuente": "OneUsefulThing",
            "url": "https://ex.com/l2",
            "titulo": "Largo medio",
            "gancho": "gancho-l2",
            "angulo": "otro análisis",
            "fecha_detectado": "2026-07-08 09:00",
        },
    ]
    msg = s.formatear_mensaje_telegram(noticias)
    # Debe empezar con el título correcto (3 propuestas)
    assert "3 propuestas nuevas" in msg
    # Largos primero → gancho-l1 antes que gancho-l2 antes que gancho-s
    p1 = msg.index("gancho-l1")
    p2 = msg.index("gancho-l2")
    p3 = msg.index("gancho-s")
    assert p1 < p2 < p3
    # Separador entre largos y shorts
    assert "· · · · · · · · ·" in msg
    # HTML válido básico
    assert '<a href="https://ex.com/l1">' in msg


def test_formatear_mensaje_telegram_escapa_html_del_titulo():
    noticias = [
        {
            "formato": "short",
            "puntuacion": 5,
            "fuente": "r/ChatGPT",
            "url": "https://ex.com/x",
            "titulo": "Peligro <script>alert(1)</script>",
            "gancho": "g",
            "angulo": "a",
            "fecha_detectado": "2026-07-08 10:00",
        }
    ]
    msg = s.formatear_mensaje_telegram(noticias)
    assert "<script>" not in msg
    assert "&lt;script&gt;" in msg


def test_normalizar_titulo_limpia_puntuacion():
    assert s.normalizar_titulo("¡Hola, Mundo! ¿Qué tal?") == "hola mundo qué tal"


def test_limpiar_texto_quita_html_y_entities():
    out = s.limpiar_texto("<p>Hola&nbsp;mundo</p>\n\n  extra   espacios")
    assert out == "Hola mundo extra espacios"


if __name__ == "__main__":
    import traceback

    fallidos = []
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        try:
            t()
            print(f"✅ {t.__name__}")
        except Exception:
            fallidos.append(t.__name__)
            print(f"❌ {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - len(fallidos)}/{len(tests)} tests pasaron")
    sys.exit(1 if fallidos else 0)
