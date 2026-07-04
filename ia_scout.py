"""IA Scout — pipeline de inteligencia de contenidos para el canal Diario Vida IA.

Monitoriza Reddit + RSS + YouTube, deduplica, analiza con Claude, guarda en
Google Sheets y envía un resumen por Telegram con las propuestas SI.
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Iterable

import gspread
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "").strip()
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 800
CLAUDE_SLEEP_SECONDS = 0.5

USER_AGENT = "Mozilla/5.0 (compatible; n8n-rss-bot/2.0)"
HTTP_TIMEOUT = 15

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
    "with", "by", "is", "are", "was", "were", "be", "been", "have", "has",
    "do", "does", "will", "would", "could", "should", "can", "this", "that",
    "these", "those", "i", "you", "he", "she", "it", "we", "they", "my",
    "your", "its", "our", "their", "what", "which", "who", "how", "when",
    "where", "why", "not", "no", "so", "than", "very", "just", "also", "now",
}


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(msg, flush=True)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def strip_html(txt: str | None) -> str:
    if not txt:
        return ""
    limpio = re.sub(r"<[^>]+>", " ", txt)
    limpio = html.unescape(limpio)
    return re.sub(r"\s+", " ", limpio).strip()


def extraer_keywords(texto: str, max_kw: int = 8) -> str:
    tokens = re.findall(r"[a-záéíóúñü0-9]+", (texto or "").lower())
    vistos: list[str] = []
    for tok in tokens:
        if len(tok) < 4 or tok in STOPWORDS or tok in vistos:
            continue
        vistos.append(tok)
        if len(vistos) >= max_kw:
            break
    return ", ".join(vistos)


def generar_hash(titulo: str, url: str) -> str:
    hash_base = (titulo.lower()[:80] + "_" + url.lower()).strip()
    encoded = base64.b64encode(hash_base.encode("utf-8")).decode("ascii")[:20]
    return encoded.replace("+", "x").replace("/", "x").replace("=", "x")


# ---------------------------------------------------------------------------
# Autenticación Google Sheets (OAuth desktop)
# ---------------------------------------------------------------------------


def get_sheets_client() -> gspread.Client:
    creds: Credentials | None = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
                raise RuntimeError(
                    f"Falta {GOOGLE_CREDENTIALS_FILE}. Descárgalo del OAuth "
                    "cliente en Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as fh:
            fh.write(creds.to_json())

    return gspread.authorize(creds)


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


def _reddit_json(sub: str, headers: dict) -> dict | None:
    urls = [
        f"https://www.reddit.com/r/{sub}/new.json?limit=25",
        f"https://old.reddit.com/r/{sub}/new.json?limit=25",
    ]
    last_err: Exception | None = None
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            if r.status_code == 429:
                last_err = RuntimeError("429 rate limit")
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return None


def fetch_reddit_sources() -> list[dict]:
    items: list[dict] = []
    headers = {"User-Agent": USER_AGENT}
    for sub in REDDIT_SOURCES:
        try:
            data = _reddit_json(sub, headers)
            if not data:
                continue
        except Exception as e:
            log(f"⚠️ Reddit error en r/{sub}: {e}")
            continue

        for child in data.get("data", {}).get("children", []):
            p = child.get("data", {}) or {}
            titulo = (p.get("title") or "").strip()
            permalink = p.get("permalink") or ""
            if not titulo or not permalink:
                continue
            url_full = "https://www.reddit.com" + permalink
            selftext = (p.get("selftext") or "").strip()
            votos = p.get("ups") or 0
            n_com = p.get("num_comments") or 0
            preview = (
                f"[▲ {votos} | 💬 {n_com}] " + (selftext if selftext else titulo)
            )[:1800]
            author = p.get("author") or "anon"
            items.append(
                {
                    "content_hash": generar_hash(titulo, url_full),
                    "fecha_detectado": now_str(),
                    "fuente": f"r/{sub}",
                    "titulo": titulo,
                    "url": url_full,
                    "autor": author,
                    "preview": preview,
                    "keywords": extraer_keywords(titulo + " " + selftext),
                    "notificado": "NO",
                }
            )
    return items


def _parse_rss_or_atom(xml_bytes: bytes) -> list[dict]:
    """Devuelve entradas normalizadas a {titulo, url, resumen} desde RSS 2.0 o Atom."""
    entries: list[dict] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return entries

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    tag = root.tag.lower()

    if tag.endswith("rss") or root.find("channel") is not None:
        channel = root.find("channel") if root.find("channel") is not None else root
        for item in channel.findall("item")[:25]:
            titulo = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            resumen = strip_html(
                item.findtext("description") or item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
            )
            entries.append({"titulo": titulo, "url": url, "resumen": resumen})
    else:
        for entry in root.findall("atom:entry", ns)[:25]:
            titulo = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
            link_el = entry.find("atom:link", ns)
            url = link_el.get("href", "").strip() if link_el is not None else ""
            resumen_raw = (
                entry.findtext("atom:summary", default="", namespaces=ns)
                or entry.findtext("atom:content", default="", namespaces=ns)
                or ""
            )
            entries.append({"titulo": titulo, "url": url, "resumen": strip_html(resumen_raw)})
    return entries


def fetch_rss_blogs() -> list[dict]:
    items: list[dict] = []
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}
    for blog in RSS_BLOGS:
        try:
            r = requests.get(blog["url"], headers=headers, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            entradas = _parse_rss_or_atom(r.content)
        except Exception as e:
            log(f"⚠️ RSS error en {blog['fuente']}: {e}")
            continue
        for e in entradas:
            titulo, url, resumen = e["titulo"], e["url"], e["resumen"]
            if not titulo or not url:
                continue
            items.append(
                {
                    "content_hash": generar_hash(titulo, url),
                    "fecha_detectado": now_str(),
                    "fuente": blog["fuente"],
                    "titulo": titulo,
                    "url": url,
                    "autor": blog["autor"],
                    "preview": resumen[:1800],
                    "keywords": extraer_keywords(titulo + " " + resumen),
                    "notificado": "NO",
                }
            )
    return items


def fetch_youtube_channels() -> list[dict]:
    items: list[dict] = []
    headers = {"User-Agent": USER_AGENT}
    for ch in YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
        try:
            r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:
            log(f"⚠️ YouTube error en {ch['fuente']}: {e}")
            continue

        ns = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/"}
        canal_autor = ""
        author_el = root.find("atom:author/atom:name", ns)
        if author_el is not None and author_el.text:
            canal_autor = author_el.text.strip()

        for entry in root.findall("atom:entry", ns)[:15]:
            titulo_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            desc_el = entry.find("media:group/media:description", ns)
            titulo = (titulo_el.text or "").strip() if titulo_el is not None else ""
            url_vid = link_el.get("href", "").strip() if link_el is not None else ""
            desc = (desc_el.text or "").strip() if desc_el is not None else ""
            if not titulo or not url_vid:
                continue
            items.append(
                {
                    "content_hash": generar_hash(titulo, url_vid),
                    "fecha_detectado": now_str(),
                    "fuente": ch["fuente"],
                    "titulo": titulo,
                    "url": url_vid,
                    "autor": canal_autor or ch["fuente"].replace("YT:", ""),
                    "preview": desc[:1800],
                    "keywords": extraer_keywords(titulo + " " + desc),
                    "notificado": "NO",
                }
            )
    return items


# ---------------------------------------------------------------------------
# Deduplicación
# ---------------------------------------------------------------------------


def leer_hashes_conocidos(gc: gspread.Client, spreadsheet_id: str) -> set[str]:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    valores = hoja.col_values(1)
    return {v.strip() for v in valores[1:] if v.strip()}


def escribir_hash(gc: gspread.Client, spreadsheet_id: str, content_hash: str) -> None:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    hoja.append_row([content_hash, datetime.now(timezone.utc).isoformat()])


def es_duplicado(
    item: dict,
    hashes_conocidos: set[str],
    hashes_batch: set[str],
    titulos_vistos: set[str],
) -> bool:
    h = item["content_hash"]
    titulo_norm = re.sub(r"[^a-z0-9áéíóúñü\s]", "", item["titulo"].lower()).strip()[:80]

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
# Claude
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


def analizar_con_claude(client: Anthropic, item: dict) -> dict:
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
    texto = ""
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            texto += block.text
    return parsear_respuesta_claude(texto)


# ---------------------------------------------------------------------------
# Sheets writer
# ---------------------------------------------------------------------------


def guardar_en_sheets(gc: gspread.Client, spreadsheet_id: str, item: dict, analisis: dict) -> None:
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
# Telegram
# ---------------------------------------------------------------------------


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


def _icono_fuente(fuente: str) -> str:
    icono = FUENTE_ICONS.get(fuente)
    if icono:
        return icono
    return "📺" if fuente.startswith("YT:") else "🌐"


def _escape_html(txt: str) -> str:
    return html.escape(txt or "", quote=False)


def _recortar_angulo(angulo: str, limite: int = 160) -> str:
    if len(angulo) <= limite:
        return angulo
    recortado = angulo[:limite]
    ultimo = max(recortado.rfind(". "), recortado.rfind(", "), recortado.rfind(" — "))
    if ultimo > 80:
        return recortado[: ultimo + 1] + "…"
    return recortado + "…"


def formatear_mensaje_telegram(noticias_si: Iterable[dict]) -> str:
    noticias_si = list(noticias_si)
    ahora = datetime.now().strftime("%d/%m %H:%M")
    total = len(noticias_si)

    largos = sorted(
        [n for n in noticias_si if n.get("formato") == "largo"],
        key=lambda x: -float(x.get("puntuacion", 0)),
    )
    shorts = sorted(
        [n for n in noticias_si if n.get("formato") == "short"],
        key=lambda x: -float(x.get("puntuacion", 0)),
    )
    resto = [n for n in noticias_si if n.get("formato") not in ("largo", "short")]
    final = largos + shorts + resto

    plural = "s" if total != 1 else ""
    lines = [f"📊 <b>SCOUT — {total} propuesta{plural} nueva{plural}</b> ({ahora})\n"]

    en_shorts = False
    for i, p in enumerate(final):
        formato = p.get("formato")
        fl = "🎬 LARGO" if formato == "largo" else "⚡ SHORT" if formato == "short" else "📄"
        punt = float(p.get("puntuacion", 0))
        estrellas = "⭐" * min(round(punt / 2), 5)
        icono = _icono_fuente(p.get("fuente", ""))

        if formato == "short" and not en_shorts and largos:
            lines.append("· · · · · · · · ·")
            en_shorts = True

        fecha_raw = (p.get("fecha_detectado") or "")[:16].replace("T", " ")
        fecha = fecha_raw[5:] if len(fecha_raw) >= 5 else fecha_raw
        angulo = _recortar_angulo(p.get("angulo", ""))

        titulo_html = _escape_html((p.get("titulo") or "")[:60])
        url = p.get("url", "")
        gancho = _escape_html(p.get("gancho") or "Sin gancho")
        angulo_html = _escape_html(angulo)

        lines.append(f"{i+1}. {fl} {estrellas} {icono} <b>{punt:.0f}/10</b> <i>{fecha}</i>")
        lines.append(f'<a href="{url}">{titulo_html}</a>')
        lines.append(f"💡 {gancho}")
        if angulo_html:
            lines.append(f"📐 <i>{angulo_html}</i>")
        lines.append("")

    lines.append("─────────────────")
    lines.append('💬 Di "guion del 1" o "más info del 2" a Marius para continuar.')
    return "\n".join(lines)


def enviar_telegram(token: str, chat_id: str, mensaje: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    trozos = [mensaje]
    if len(mensaje) > 4000:
        trozos = []
        actual = ""
        for linea in mensaje.split("\n"):
            if len(actual) + len(linea) + 1 > 3800:
                trozos.append(actual)
                actual = ""
            actual += linea + "\n"
        if actual:
            trozos.append(actual)

    for trozo in trozos:
        payload = {
            "chat_id": chat_id,
            "text": trozo,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _validar_config() -> None:
    faltan = []
    if not ANTHROPIC_KEY:
        faltan.append("ANTHROPIC_API_KEY")
    if not TG_TOKEN:
        faltan.append("TELEGRAM_BOT_TOKEN")
    if not TG_CHAT_ID:
        faltan.append("TELEGRAM_CHAT_ID")
    if not SHEETS_ID:
        faltan.append("GOOGLE_SHEETS_ID")
    if faltan:
        raise RuntimeError("Faltan variables en .env: " + ", ".join(faltan))


def ejecutar_pipeline() -> dict:
    log("🚀 IA Scout iniciando...")
    _validar_config()

    gc = get_sheets_client()
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
    log(f"✅ Items nuevos: {len(nuevos)} de {len(items_raw)}")

    resumen = {
        "hashes_conocidos": len(hashes_conocidos),
        "items_raw": len(items_raw),
        "nuevos": len(nuevos),
        "analizados": 0,
        "propuestas_si": 0,
        "errores": 0,
    }

    if not nuevos:
        log("ℹ️ Sin novedades este ciclo")
        return resumen

    client = Anthropic(api_key=ANTHROPIC_KEY)
    noticias_si: list[dict] = []

    for item in nuevos:
        try:
            analisis = analizar_con_claude(client, item)
            escribir_hash(gc, SHEETS_ID, item["content_hash"])
            guardar_en_sheets(gc, SHEETS_ID, item, analisis)
            resumen["analizados"] += 1

            if analisis["vale"] == "SI":
                noticias_si.append({**item, **analisis})

            marca = "✅" if analisis["vale"] == "SI" else "❌"
            log(f'{marca} {analisis["puntuacion"]:.0f}/10 — {item["titulo"][:50]}')
        except Exception as e:
            resumen["errores"] += 1
            log(f'⚠️ Error procesando {item["titulo"][:40]}: {e}')
        finally:
            time.sleep(CLAUDE_SLEEP_SECONDS)

    resumen["propuestas_si"] = len(noticias_si)

    if noticias_si:
        mensaje = formatear_mensaje_telegram(noticias_si)
        enviar_telegram(TG_TOKEN, TG_CHAT_ID, mensaje)
        log(f"📱 Telegram enviado: {len(noticias_si)} propuestas")
    else:
        log("ℹ️ Sin propuestas SI este ciclo, no se envía TG")

    return resumen


if __name__ == "__main__":
    try:
        ejecutar_pipeline()
    except Exception as exc:
        log(f"💥 Fallo del pipeline: {exc}")
        sys.exit(1)
