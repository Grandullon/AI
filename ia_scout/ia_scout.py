"""IA Scout — pipeline de descubrimiento de contenido para Diario Vida IA.

Flujo por ciclo:
  1. OAuth Google Sheets
  2. Fetch Reddit + RSS blogs + YouTube RSS
  3. Deduplicación (hoja Hashes + memoria)
  4. Análisis con Claude (haiku 4.5)
  5. Persistencia en hoja ScoutIA + Hashes
  6. Resumen a Telegram si hay vale=='SI'
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Iterable

# Deps pesadas se importan de forma perezosa dentro de las funciones que las usan
# (feedparser, gspread, anthropic, google.*) para que el módulo sea importable
# en entornos de test sin instalarlas.

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "").strip()
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
GOOGLE_CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 800
CLAUDE_SLEEP_S = 0.5

USER_AGENT = "Mozilla/5.0 (compatible; n8n-rss-bot/2.0)"
HTTP_TIMEOUT = 20

REDDIT_SOURCES = [
    "notebooklm",
    "PromptEngineering",
    "ArtificialInteligence",
    "ChatGPT",
    "ClaudeAI",
    "productivity",
]

RSS_BLOGS = [
    {
        "url": "https://www.oneusefulthing.org/feed",
        "fuente": "OneUsefulThing",
        "autor": "Ethan Mollick",
    },
    {
        "url": "https://simonwillison.net/atom/everything/",
        "fuente": "SimonWillison",
        "autor": "Simon Willison",
    },
]

YOUTUBE_CHANNELS = [
    {"channel_id": "UCj2zirDn1hkPKSARbARfeQw", "fuente": "YT:PaulJames"},
    {"channel_id": "UCYdEAbC7JrC8fBt8OoDwoJQ", "fuente": "YT:JoaquinBarbera"},
    {"channel_id": "UCmeU2DYiVy80wMBGZzEWnbw", "fuente": "YT:PaulLipsky"},
    {"channel_id": "UChez6IIo3Z1g3HUezkr7jIA", "fuente": "YT:AnjanaGowtham"},
    {"channel_id": "UCwT758Tjg0LPHSNmH0QqkhQ", "fuente": "YT:AndyLok"},
    {"channel_id": "UC3KK7ENB_ierAXvrxVNnbZQ", "fuente": "YT:BenAI92"},
    {"channel_id": "UCxcDzs-4quJV4QsairlFYNg", "fuente": "YT:AlejaviRivera"},
    {"channel_id": "UCrB7UFnkosBjAhOg3a9NdWw", "fuente": "YT:GraceLeung"},
]

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "is", "are", "was", "were", "be", "been", "have", "has", "do",
    "does", "will", "would", "could", "should", "can", "this", "that", "these",
    "those", "i", "you", "he", "she", "it", "we", "they", "my", "your", "its",
    "our", "their", "what", "which", "who", "how", "when", "where", "why",
    "not", "no", "so", "than", "very", "just", "also", "now",
}

FUENTE_ICONS = {
    "r/notebooklm": "🔴",
    "r/PromptEngineering": "🔴",
    "r/ArtificialInteligence": "🔴",
    "r/ChatGPT": "🔴",
    "r/ClaudeAI": "🔴",
    "r/productivity": "🔴",
    "OneUsefulThing": "🔬",
    "SimonWillison": "🔬",
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def ahora_local_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def limpiar_texto(texto: str) -> str:
    if not texto:
        return ""
    texto = html.unescape(texto)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def extraer_keywords(texto: str, maximo: int = 8) -> str:
    if not texto:
        return ""
    limpio = re.sub(r"[^a-z0-9áéíóúñü\s]", " ", texto.lower())
    tokens = [t for t in limpio.split() if len(t) > 3 and t not in STOPWORDS]
    vistos: list[str] = []
    for t in tokens:
        if t not in vistos:
            vistos.append(t)
        if len(vistos) >= maximo:
            break
    return ",".join(vistos)


def generar_hash(titulo: str, url: str) -> str:
    """Opción A (base64, 20 chars) — compatible con hashes ya guardados."""
    base = (titulo.lower()[:80] + "_" + url.lower()).strip()
    encoded = base64.b64encode(base.encode("utf-8")).decode("ascii")[:20]
    return encoded.replace("+", "x").replace("/", "x").replace("=", "x")


def normalizar_titulo(titulo: str) -> str:
    t = re.sub(r"[^a-z0-9áéíóúñü\s]", "", titulo.lower())
    return t.strip()[:80]


# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------

def get_sheets_client() -> Any:
    import gspread
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(GOOGLE_CREDS_FILE):
                raise FileNotFoundError(
                    f"Falta {GOOGLE_CREDS_FILE}. Descárgalo desde Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(GOOGLE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return gspread.authorize(creds)


def leer_hashes_conocidos(gc: Any, spreadsheet_id: str) -> set[str]:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    valores = hoja.col_values(1)
    return {v.strip() for v in valores[1:] if v.strip()}


def escribir_hash(gc: Any, spreadsheet_id: str, content_hash: str) -> None:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    hoja.append_row(
        [content_hash, datetime.now(timezone.utc).isoformat()],
        value_input_option="USER_ENTERED",
    )


def guardar_en_sheets(
    gc: Any,
    spreadsheet_id: str,
    item: dict,
    analisis: dict,
) -> None:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("ScoutIA")
    fila = [
        item["content_hash"],
        item["fecha_detectado"],
        item["fuente"],
        item["titulo"],
        item["url"],
        item["autor"],
        (item.get("preview") or "")[:500],
        item.get("keywords", ""),
        "NO",
        analisis["vale"],
        analisis["formato"],
        analisis["puntuacion"],
        analisis.get("gancho", ""),
        analisis.get("angulo", ""),
        "pendiente",
    ]
    hoja.append_row(fila, value_input_option="USER_ENTERED")


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_reddit_sources() -> list[dict]:
    import requests

    resultados: list[dict] = []
    headers = {"User-Agent": USER_AGENT}
    for sub in REDDIT_SOURCES:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
        try:
            r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                log(f"⚠️  Reddit r/{sub} HTTP {r.status_code} — se salta")
                continue
            data = r.json()
            for child in data.get("data", {}).get("children", []):
                d = child.get("data") or {}
                if d.get("stickied") or d.get("over_18"):
                    continue
                titulo = limpiar_texto(d.get("title") or "")
                selftext = limpiar_texto(d.get("selftext") or "")
                permalink = d.get("permalink") or ""
                post_url = "https://reddit.com" + permalink if permalink else d.get("url", "")
                autor = d.get("author") or "anon"
                score = d.get("score", 0)
                comments = d.get("num_comments", 0)
                created_utc = d.get("created_utc")
                if created_utc:
                    fecha = datetime.fromtimestamp(created_utc, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                else:
                    fecha = ahora_local_str()

                preview = f"[{score}↑ · {comments}💬] {selftext or titulo}"[:1800]
                item = {
                    "content_hash": generar_hash(titulo, post_url),
                    "fecha_detectado": fecha,
                    "fuente": f"r/{sub}",
                    "titulo": titulo,
                    "url": post_url,
                    "autor": f"u/{autor}",
                    "preview": preview,
                    "keywords": extraer_keywords(f"{titulo} {selftext}"),
                    "notificado": "NO",
                }
                if item["titulo"] and item["url"]:
                    resultados.append(item)
        except requests.RequestException as e:
            log(f"⚠️  Reddit r/{sub} error red: {e} — se salta")
        except ValueError as e:
            log(f"⚠️  Reddit r/{sub} JSON inválido: {e} — se salta")
        time.sleep(0.4)
    return resultados


def _parsear_fecha_feed(entry) -> str:
    for campo in ("published_parsed", "updated_parsed"):
        v = entry.get(campo) if hasattr(entry, "get") else getattr(entry, campo, None)
        if v:
            try:
                return datetime(*v[:6], tzinfo=timezone.utc).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
    return ahora_local_str()


def fetch_rss_blogs() -> list[dict]:
    import feedparser

    resultados: list[dict] = []
    for blog in RSS_BLOGS:
        try:
            feed = feedparser.parse(blog["url"], request_headers={"User-Agent": USER_AGENT})
            for entry in feed.entries[:20]:
                titulo = limpiar_texto(entry.get("title") or "")
                url = entry.get("link") or ""
                resumen = limpiar_texto(
                    entry.get("summary") or entry.get("description") or ""
                )
                if not titulo or not url:
                    continue
                item = {
                    "content_hash": generar_hash(titulo, url),
                    "fecha_detectado": _parsear_fecha_feed(entry),
                    "fuente": blog["fuente"],
                    "titulo": titulo,
                    "url": url,
                    "autor": blog["autor"],
                    "preview": resumen[:1800],
                    "keywords": extraer_keywords(f"{titulo} {resumen}"),
                    "notificado": "NO",
                }
                resultados.append(item)
        except Exception as e:
            log(f"⚠️  RSS {blog['fuente']} error: {e} — se salta")
    return resultados


def fetch_youtube_channels() -> list[dict]:
    import feedparser

    resultados: list[dict] = []
    for ch in YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
        try:
            feed = feedparser.parse(url, request_headers={"User-Agent": USER_AGENT})
            for entry in feed.entries[:15]:
                titulo = limpiar_texto(entry.get("title") or "")
                video_url = entry.get("link") or ""
                autor = limpiar_texto(entry.get("author") or ch["fuente"])
                resumen = limpiar_texto(
                    entry.get("summary") or entry.get("description") or ""
                )
                if not titulo or not video_url:
                    continue
                item = {
                    "content_hash": generar_hash(titulo, video_url),
                    "fecha_detectado": _parsear_fecha_feed(entry),
                    "fuente": ch["fuente"],
                    "titulo": titulo,
                    "url": video_url,
                    "autor": autor,
                    "preview": resumen[:1800],
                    "keywords": extraer_keywords(f"{titulo} {resumen}"),
                    "notificado": "NO",
                }
                resultados.append(item)
        except Exception as e:
            log(f"⚠️  YouTube {ch['fuente']} error: {e} — se salta")
    return resultados


# ---------------------------------------------------------------------------
# Deduplicación
# ---------------------------------------------------------------------------

def es_duplicado(
    item: dict,
    hashes_conocidos: set[str],
    hashes_batch: set[str],
    titulos_vistos: set[str],
) -> bool:
    h = item["content_hash"]
    titulo_norm = normalizar_titulo(item["titulo"])

    if h in hashes_conocidos:
        return True
    if h in hashes_batch:
        return True
    if titulo_norm and titulo_norm in titulos_vistos:
        return True

    hashes_batch.add(h)
    if titulo_norm:
        titulos_vistos.add(titulo_norm)
    return False


# ---------------------------------------------------------------------------
# Análisis Claude
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """Eres el editor de contenido de "Diario Vida IA", canal YouTube español con 15.200 suscriptores creciendo a +100/día.

CONTEXTO DEL CANAL:
- PILAR PRINCIPAL (60% del contenido): NotebookLM. Cualquier novedad, truco, caso de uso, integración o experiencia real con NotebookLM tiene prioridad máxima automática.
- PILAR 2: IA práctica para trabajadores del conocimiento (ChatGPT, Claude, Gemini, Perplexity). Casos de uso reales, no demos de laboratorio.
- PILAR 3: Automatización y productividad (n8n, flujos de trabajo, ahorrar tiempo real).
- DESCARTAR SIEMPRE: desarrollo de software, programación pura, hardware, gaming, ciencia sin aplicación práctica, noticias corporativas sin impacto en el usuario.

AUDIENCIA: Profesionales 30-50 años, trabajadores del conocimiento (médicos, RRHH, profesores, administrativos, gestores). Usan IA en su trabajo pero NO son programadores. Quieren resultados en menos de 10 minutos. Desconfían del hype. Valoran la honestidad sobre las limitaciones.

ESTILO DEL CANAL: Anti-gurú. Directo. Sin "revolucionario", sin emojis de cohete. El presentador es Paco, trabaja en un hospital (RRHH), 500+ días de constancia personal. Credibilidad por resultados reales, no por promesas.

---

NOTICIA A EVALUAR:
Fuente: {fuente}
Título: {titulo}
Autor: {autor}
URL: {url}
Contenido: {preview}
Keywords: {keywords}

---

TIPOS DE CONTENIDO QUE SÍ INTERESAN:

1. NOTEBOOKLM — cualquier cosa: update, truco, caso de uso, integración, comparativa, experiencia real. PUNTUACIÓN MÍNIMA 6 automático si tiene ángulo demostrable.

2. HILO REDDIT con experiencias reales — usuarios contando qué les funcionó o falló. Ángulo: "esto le pasa a tu audiencia también".

3. HERRAMIENTA NUEVA para no-devs — si se puede probar en menos de 5 minutos, vale.

4. ACTUALIDAD IA con impacto práctico — funciones nuevas en ChatGPT, Claude, Gemini que cambien el flujo de trabajo diario.

5. COMPARATIVA práctica — "X vs Y para hacer Z", "probé 3 formas de hacer esto".

6. ERROR O LIMITACIÓN REAL — fallo, workaround o decepción documentada. Ángulo honesto.

---

ESCALA DE PUNTUACIÓN:

1: Spam, irrelevante total
2: Fuera de nicho (hardware, gaming, ciencia pura, eventos)
3: IA genérica sin ángulo para trabajadores no-dev
4: Ángulo débil o contenido escaso
5: Decente pero no urgente
6: Bueno — relevante + ángulo claro + grabar esta semana
7: Muy bueno — búsquedas activas + demostrable + útil ahora
8: Excelente — alto potencial + aplicable hoy + diferenciador
9-10: Exclusiva o tendencia emergente con ventana corta

BONO NOTEBOOKLM: suma +1 punto a cualquier contenido sobre NotebookLM con puntuación base ≥5.

EJEMPLOS CALIBRADOS:
- "NotebookLM añade diapositivas editables" → 9
- "Cómo uso NotebookLM para estudiar protocolos médicos" → 8
- "Claude vs ChatGPT para redactar informes" → 7
- "Hilo Reddit: NotebookLM me ha cambiado el trabajo" → 7
- "Build an AI agent with Python" → 2
- "OpenAI recauda 110B" → 3

---

FORMATOS:
- SHORT: Un truco, comparativa visual, dato sorprendente, experiencia real resumida (≤60s)
- LARGO: Tutorial paso a paso, workflow completo, análisis con demo (8-15min)

---

Responde ÚNICAMENTE con este JSON sin texto antes ni después:
{{
  "vale": "SI" o "NO",
  "formato": "short" o "largo" o "ninguno",
  "puntuacion": número entero del 1 al 10,
  "gancho": "título en español de España, max 65 chars, sin emojis de cohete",
  "angulo": "2-3 frases sobre qué contenido sería, a quién beneficia y por qué encaja"
}}

REGLA FINAL: si dudas y puntuación ≥5, pon SI."""


def parsear_respuesta_claude(texto: str) -> dict:
    defaults = {
        "vale": "NO",
        "formato": "ninguno",
        "puntuacion": 0,
        "gancho": "",
        "angulo": "Sin análisis",
    }
    try:
        clean = texto.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{[\s\S]*\}", clean)
        if not match:
            return defaults
        p = json.loads(match.group(0))
        vr = str(p.get("vale", "")).upper().strip()
        fr = str(p.get("formato", "")).lower().strip()
        try:
            punt = float(p.get("puntuacion", 0))
        except (TypeError, ValueError):
            punt = 0.0
        return {
            "vale": "SI" if vr in ("SI", "YES", "TRUE") else "NO",
            "formato": fr if fr in ("short", "largo") else "ninguno",
            "puntuacion": min(10, max(0, punt)),
            "gancho": str(p.get("gancho", "")).strip(),
            "angulo": str(p.get("angulo", "")).strip() or "Sin descripción",
        }
    except Exception as e:
        defaults["angulo"] = f"Error: {str(e)[:100]}"
        return defaults


def analizar_con_claude(client: Any, item: dict) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        fuente=item.get("fuente", ""),
        titulo=item.get("titulo", ""),
        autor=item.get("autor", ""),
        url=item.get("url", ""),
        preview=(item.get("preview") or "")[:1800],
        keywords=item.get("keywords", ""),
    )
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    texto = "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    )
    return parsear_respuesta_claude(texto)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def _recortar_angulo(angulo: str, maximo: int = 160) -> str:
    if len(angulo) <= maximo:
        return angulo
    recortado = angulo[:maximo]
    ultimo = max(recortado.rfind(". "), recortado.rfind(", "), recortado.rfind(" — "))
    if ultimo > 80:
        return recortado[: ultimo + 1] + "…"
    return recortado + "…"


def formatear_mensaje_telegram(noticias_si: Iterable[dict]) -> str:
    noticias = list(noticias_si)
    ahora = datetime.now().strftime("%d/%m %H:%M")
    total = len(noticias)

    largos = sorted(
        [n for n in noticias if n["formato"] == "largo"],
        key=lambda x: -float(x.get("puntuacion", 0)),
    )
    shorts = sorted(
        [n for n in noticias if n["formato"] == "short"],
        key=lambda x: -float(x.get("puntuacion", 0)),
    )
    resto = [n for n in noticias if n["formato"] not in ("largo", "short")]
    final = largos + shorts + resto

    sufijo = "s" if total != 1 else ""
    lines = [f"📊 <b>SCOUT — {total} propuesta{sufijo} nuevas</b> ({ahora})\n"]

    en_shorts = False
    for i, p in enumerate(final):
        fl = (
            "🎬 LARGO"
            if p["formato"] == "largo"
            else "⚡ SHORT"
            if p["formato"] == "short"
            else "📄"
        )
        try:
            punt = float(p.get("puntuacion", 0))
        except (TypeError, ValueError):
            punt = 0.0
        estrellas = "⭐" * min(round(punt / 2), 5)
        icono = FUENTE_ICONS.get(p["fuente"]) or (
            "📺" if p["fuente"].startswith("YT:") else "🌐"
        )

        if p["formato"] == "short" and not en_shorts and largos:
            lines.append("· · · · · · · · ·")
            en_shorts = True

        fecha = (p.get("fecha_detectado") or "")[:16].replace("T", " ")[5:]
        angulo = _recortar_angulo(p.get("angulo", ""))

        titulo_html = html.escape(p["titulo"][:60])
        url_html = html.escape(p["url"], quote=True)
        gancho_html = html.escape(p.get("gancho") or "Sin gancho")

        lines.append(
            f"{i+1}. {fl} {estrellas} {icono} <b>{punt:.0f}/10</b> <i>{fecha}</i>"
        )
        lines.append(f'<a href="{url_html}">{titulo_html}</a>')
        lines.append(f"💡 {gancho_html}")
        if angulo:
            lines.append(f"📐 <i>{html.escape(angulo)}</i>")
        lines.append("")

    lines.append("─────────────────")
    lines.append('💬 Di "guion del 1" o "más info del 2" a Marius para continuar.')
    return "\n".join(lines)


def enviar_telegram(token: str, chat_id: str, mensaje: str) -> None:
    import requests

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": mensaje,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def _check_env() -> None:
    faltan = []
    if not SHEETS_ID:
        faltan.append("GOOGLE_SHEETS_ID")
    if not ANTHROPIC_KEY:
        faltan.append("ANTHROPIC_API_KEY")
    if not TG_TOKEN:
        faltan.append("TELEGRAM_BOT_TOKEN")
    if not TG_CHAT_ID:
        faltan.append("TELEGRAM_CHAT_ID")
    if faltan:
        raise SystemExit(f"❌ Faltan variables de entorno: {', '.join(faltan)}")


def ejecutar_pipeline() -> None:
    from anthropic import Anthropic

    log("🚀 IA Scout iniciando...")
    _check_env()

    gc = get_sheets_client()
    claude = Anthropic(api_key=ANTHROPIC_KEY)

    hashes_conocidos = leer_hashes_conocidos(gc, SHEETS_ID)
    log(f"📋 Hashes conocidos: {len(hashes_conocidos)}")

    items_raw: list[dict] = []
    items_raw += fetch_reddit_sources()
    items_raw += fetch_rss_blogs()
    items_raw += fetch_youtube_channels()
    log(f"📥 Items crudos: {len(items_raw)}")

    hashes_batch: set[str] = set()
    titulos_vistos: set[str] = set()
    nuevos = [
        item
        for item in items_raw
        if not es_duplicado(item, hashes_conocidos, hashes_batch, titulos_vistos)
    ]
    log(f"✅ Items nuevos tras dedup: {len(nuevos)} de {len(items_raw)}")

    if not nuevos:
        log("ℹ️  Sin novedades este ciclo")
        return

    noticias_si: list[dict] = []
    for item in nuevos:
        try:
            analisis = analizar_con_claude(claude, item)
            escribir_hash(gc, SHEETS_ID, item["content_hash"])
            guardar_en_sheets(gc, SHEETS_ID, item, analisis)

            if analisis["vale"] == "SI":
                noticias_si.append({**item, **analisis})

            marcador = "✅" if analisis["vale"] == "SI" else "❌"
            log(
                f"{marcador} {analisis['puntuacion']}/10 [{item['fuente']}] "
                f"{item['titulo'][:60]}"
            )
        except Exception as e:
            log(f"⚠️  Error procesando '{item['titulo'][:40]}': {e}")
            continue
        finally:
            time.sleep(CLAUDE_SLEEP_S)

    if noticias_si:
        try:
            mensaje = formatear_mensaje_telegram(noticias_si)
            enviar_telegram(TG_TOKEN, TG_CHAT_ID, mensaje)
            log(f"📱 Telegram enviado: {len(noticias_si)} propuestas")
        except Exception as e:
            log(f"❌ Error enviando Telegram: {e}")
    else:
        log("ℹ️  Sin propuestas SI este ciclo, no se envía TG")


if __name__ == "__main__":
    try:
        ejecutar_pipeline()
    except SystemExit:
        raise
    except Exception as e:
        log(f"💥 Pipeline abortado: {e}")
        traceback.print_exc()
        sys.exit(1)
