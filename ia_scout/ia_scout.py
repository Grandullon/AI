"""
IA Scout — Pipeline de inteligencia de contenidos para "Diario Vida IA" (@PacoVidaIA).

Monitoriza RSS, Reddit y YouTube, deduplica, analiza con Claude, guarda en Google
Sheets y envía un resumen por Telegram. Diseñado para ejecución periódica (cron
cada 6h o similar) en un entorno persistente con credenciales OAuth cacheadas.
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
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import feedparser
import gspread
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 800
HTTP_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; n8n-rss-bot/2.0)"

REDDIT_SOURCES = [
    "notebooklm",
    "PromptEngineering",
    "ArtificialInteligence",
    "ChatGPT",
    "ClaudeAI",
    "productivity",
]

RSS_BLOGS = [
    {"url": "https://www.oneusefulthing.org/feed", "fuente": "OneUsefulThing", "autor": "Ethan Mollick"},
    {"url": "https://simonwillison.net/atom/everything/", "fuente": "SimonWillison", "autor": "Simon Willison"},
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
    "our", "their", "what", "which", "who", "how", "when", "where", "why", "not",
    "no", "so", "than", "very", "just", "also", "now",
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
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}Z] {msg}", flush=True)


def strip_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extraer_keywords(titulo: str, preview: str, limite: int = 8) -> str:
    texto = f"{titulo} {preview}".lower()
    tokens = re.findall(r"[a-záéíóúñü0-9]{3,}", texto)
    vistas: list[str] = []
    for t in tokens:
        if t in STOPWORDS or t.isdigit():
            continue
        if t not in vistas:
            vistas.append(t)
        if len(vistas) >= limite:
            break
    return ", ".join(vistas)


def generar_hash(titulo: str, url: str) -> str:
    """Base64 truncado a 20 chars (Opción A del spec, compatible con hashes n8n)."""
    hash_base = (titulo.lower()[:80] + "_" + url.lower()).strip()
    encoded = base64.b64encode(hash_base.encode("utf-8")).decode("ascii")[:20]
    return encoded.replace("+", "x").replace("/", "x").replace("=", "x")


def ahora_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Autenticación Google Sheets
# ---------------------------------------------------------------------------


def get_sheets_client() -> gspread.Client:
    creds: Credentials | None = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return gspread.authorize(creds)


def leer_hashes_conocidos(gc: gspread.Client, spreadsheet_id: str) -> set[str]:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    valores = hoja.col_values(1)
    return {v.strip() for v in valores[1:] if v.strip()}


def escribir_hash(gc: gspread.Client, spreadsheet_id: str, content_hash: str) -> None:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    hoja.append_row([content_hash, datetime.now(timezone.utc).isoformat()])


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
# Fetchers
# ---------------------------------------------------------------------------


def _http_get(url: str, headers: dict | None = None) -> requests.Response | None:
    try:
        r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        if r.status_code >= 400:
            log(f"⚠️ HTTP {r.status_code} en {url}")
            return None
        return r
    except requests.RequestException as e:
        log(f"⚠️ Error red {url}: {e}")
        return None


def fetch_reddit_sources() -> list[dict]:
    items: list[dict] = []
    headers = {"User-Agent": USER_AGENT}
    for sub in REDDIT_SOURCES:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
        resp = _http_get(url, headers=headers)
        if resp is None:
            continue
        try:
            data = resp.json()
        except ValueError:
            log(f"⚠️ Reddit {sub}: JSON inválido")
            continue

        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            titulo = post.get("title", "").strip()
            permalink = post.get("permalink", "")
            if not titulo or not permalink:
                continue
            url_post = "https://www.reddit.com" + permalink
            autor = post.get("author", "unknown")
            selftext = post.get("selftext", "")
            score = post.get("score", 0)
            num_comments = post.get("num_comments", 0)
            preview = f"[↑{score} 💬{num_comments}] {strip_html(selftext)}"[:1800]

            items.append({
                "content_hash": generar_hash(titulo, url_post),
                "fecha_detectado": ahora_str(),
                "fuente": f"r/{sub}",
                "titulo": titulo,
                "url": url_post,
                "autor": autor,
                "preview": preview,
                "keywords": extraer_keywords(titulo, selftext),
                "notificado": "NO",
            })
        time.sleep(0.5)
    return items


def fetch_rss_blogs() -> list[dict]:
    items: list[dict] = []
    for blog in RSS_BLOGS:
        resp = _http_get(blog["url"], headers={"User-Agent": USER_AGENT})
        if resp is None:
            continue
        parsed = feedparser.parse(resp.content)
        for entry in parsed.entries[:15]:
            titulo = (entry.get("title") or "").strip()
            url = (entry.get("link") or "").strip()
            if not titulo or not url:
                continue
            resumen = strip_html(entry.get("summary") or entry.get("description") or "")[:1800]
            fecha_entry = entry.get("published") or entry.get("updated") or ahora_str()
            items.append({
                "content_hash": generar_hash(titulo, url),
                "fecha_detectado": ahora_str(),
                "fuente": blog["fuente"],
                "titulo": titulo,
                "url": url,
                "autor": blog["autor"],
                "preview": resumen,
                "keywords": extraer_keywords(titulo, resumen),
                "notificado": "NO",
                "fecha_publicado": fecha_entry,
            })
    return items


def fetch_youtube_channels() -> list[dict]:
    items: list[dict] = []
    ns = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/"}
    for ch in YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
        resp = _http_get(url, headers={"User-Agent": USER_AGENT})
        if resp is None:
            continue
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            log(f"⚠️ YT {ch['fuente']} XML inválido: {e}")
            continue
        for entry in root.findall("atom:entry", ns)[:15]:
            titulo_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            author_el = entry.find("atom:author/atom:name", ns)
            desc_el = entry.find("media:group/media:description", ns)
            titulo = (titulo_el.text or "").strip() if titulo_el is not None else ""
            link = link_el.get("href") if link_el is not None else ""
            autor = (author_el.text or ch["fuente"]).strip() if author_el is not None else ch["fuente"]
            desc = (desc_el.text or "").strip() if desc_el is not None else ""
            if not titulo or not link:
                continue
            items.append({
                "content_hash": generar_hash(titulo, link),
                "fecha_detectado": ahora_str(),
                "fuente": ch["fuente"],
                "titulo": titulo,
                "url": link,
                "autor": autor,
                "preview": desc[:1800],
                "keywords": extraer_keywords(titulo, desc),
                "notificado": "NO",
            })
    return items


# ---------------------------------------------------------------------------
# Deduplicación
# ---------------------------------------------------------------------------


@dataclass
class DedupState:
    conocidos: set[str]
    batch: set[str] = field(default_factory=set)
    titulos_vistos: set[str] = field(default_factory=set)


def es_duplicado(item: dict, state: DedupState) -> bool:
    h = item["content_hash"]
    titulo_norm = re.sub(r"[^a-z0-9áéíóúñü\s]", "", item["titulo"].lower()).strip()[:80]

    if h in state.conocidos:
        return True
    if h in state.batch:
        return True
    if titulo_norm and titulo_norm in state.titulos_vistos:
        return True

    state.batch.add(h)
    if titulo_norm:
        state.titulos_vistos.add(titulo_norm)
    return False


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


PROMPT_ANALISIS = """Eres el editor de contenido de "Diario Vida IA", canal YouTube español con 15.200 suscriptores creciendo a +100/día.

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


_anthropic_client: Anthropic | None = None


def _get_anthropic() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY no está definida en el entorno")
        _anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def parsear_respuesta_claude(texto: str) -> dict:
    defaults = {"vale": "NO", "formato": "ninguno", "puntuacion": 0, "gancho": "", "angulo": "Sin análisis"}
    try:
        clean = texto.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{[\s\S]*\}", clean)
        if not match:
            return defaults
        p = json.loads(match.group(0))
        vr = str(p.get("vale", "")).upper().strip()
        fr = str(p.get("formato", "")).lower().strip()
        return {
            "vale": "SI" if vr in ("SI", "YES", "TRUE") else "NO",
            "formato": fr if fr in ("short", "largo") else "ninguno",
            "puntuacion": min(10, max(0, float(p.get("puntuacion", 0)))),
            "gancho": str(p.get("gancho", "")).strip(),
            "angulo": str(p.get("angulo", "")).strip() or "Sin descripción",
        }
    except Exception as e:
        defaults["angulo"] = f"Error: {str(e)[:100]}"
        return defaults


def analizar_con_claude(item: dict) -> dict:
    client = _get_anthropic()
    prompt = PROMPT_ANALISIS.format(
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
    texto = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    return parsear_respuesta_claude(texto)


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


def _recortar_angulo(angulo: str, limite: int = 160) -> str:
    if len(angulo) <= limite:
        return angulo
    recortado = angulo[:limite]
    ultimo = max(recortado.rfind(". "), recortado.rfind(", "), recortado.rfind(" — "))
    return (recortado[: ultimo + 1] + "…") if ultimo > 80 else (recortado + "…")


def formatear_mensaje_telegram(noticias_si: list[dict]) -> str:
    ahora = datetime.now().strftime("%d/%m %H:%M")
    total = len(noticias_si)

    largos = sorted([n for n in noticias_si if n["formato"] == "largo"], key=lambda x: -float(x["puntuacion"]))
    shorts = sorted([n for n in noticias_si if n["formato"] == "short"], key=lambda x: -float(x["puntuacion"]))
    resto = [n for n in noticias_si if n["formato"] not in ("largo", "short")]
    final = largos + shorts + resto

    lines: list[str] = [
        f'📊 <b>SCOUT — {total} propuesta{"s" if total != 1 else ""} nuevas</b> ({ahora})\n'
    ]

    en_shorts = False
    for i, p in enumerate(final):
        fl = "🎬 LARGO" if p["formato"] == "largo" else "⚡ SHORT" if p["formato"] == "short" else "📄"
        punt = float(p.get("puntuacion", 0))
        estrellas = "⭐" * min(round(punt / 2), 5)
        icono = FUENTE_ICONS.get(p["fuente"]) or ("📺" if p["fuente"].startswith("YT:") else "🌐")

        if p["formato"] == "short" and not en_shorts and largos:
            lines.append("· · · · · · · · ·")
            en_shorts = True

        fecha = (p.get("fecha_detectado") or "")[:16].replace("T", " ")[5:]
        angulo = _recortar_angulo(p.get("angulo", ""))
        titulo_esc = html.escape(p["titulo"][:60])
        url_esc = html.escape(p["url"], quote=True)
        gancho_esc = html.escape(p.get("gancho") or "Sin gancho")
        angulo_esc = html.escape(angulo)

        lines.append(f'{i+1}. {fl} {estrellas} {icono} <b>{punt:.0f}/10</b> <i>{fecha}</i>')
        lines.append(f'<a href="{url_esc}">{titulo_esc}</a>')
        lines.append(f"💡 {gancho_esc}")
        if angulo:
            lines.append(f"📐 <i>{angulo_esc}</i>")
        lines.append("")

    lines.append("─────────────────")
    lines.append('💬 Di "guion del 1" o "más info del 2" a Marius para continuar.')
    return "\n".join(lines)


def enviar_telegram(token: str, chat_id: str, mensaje: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "HTML", "disable_web_page_preview": True}
    resp = requests.post(url, json=payload, timeout=15)
    if not resp.ok:
        log(f"⚠️ Telegram respondió {resp.status_code}: {resp.text[:200]}")
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _validar_config() -> list[str]:
    faltantes = []
    if not ANTHROPIC_API_KEY:
        faltantes.append("ANTHROPIC_API_KEY")
    if not TELEGRAM_BOT_TOKEN:
        faltantes.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        faltantes.append("TELEGRAM_CHAT_ID")
    if not SHEETS_ID:
        faltantes.append("GOOGLE_SHEETS_ID")
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE) and not os.path.exists(GOOGLE_TOKEN_FILE):
        faltantes.append(f"{GOOGLE_CREDENTIALS_FILE} o {GOOGLE_TOKEN_FILE}")
    return faltantes


def ejecutar_pipeline() -> int:
    log("🚀 IA Scout iniciando…")

    faltantes = _validar_config()
    if faltantes:
        log(f"❌ Falta configuración: {', '.join(faltantes)}")
        return 2

    gc = get_sheets_client()
    hashes_conocidos = leer_hashes_conocidos(gc, SHEETS_ID)
    log(f"📋 Hashes conocidos: {len(hashes_conocidos)}")

    items_raw: list[dict] = []
    items_raw += fetch_reddit_sources()
    items_raw += fetch_rss_blogs()
    items_raw += fetch_youtube_channels()
    log(f"📥 Items crudos: {len(items_raw)}")

    state = DedupState(conocidos=hashes_conocidos)
    nuevos = [it for it in items_raw if not es_duplicado(it, state)]
    log(f"✅ Items nuevos: {len(nuevos)} de {len(items_raw)}")

    if not nuevos:
        log("ℹ️ Sin novedades este ciclo")
        return 0

    noticias_si: list[dict] = []
    for item in nuevos:
        try:
            analisis = analizar_con_claude(item)
            escribir_hash(gc, SHEETS_ID, item["content_hash"])
            guardar_en_sheets(gc, SHEETS_ID, item, analisis)
            if analisis["vale"] == "SI":
                noticias_si.append({**item, **analisis})
            marca = "✅" if analisis["vale"] == "SI" else "❌"
            log(f'{marca} {analisis["puntuacion"]}/10 — {item["titulo"][:50]}')
            time.sleep(0.5)
        except Exception as e:  # noqa: BLE001 — quiero seguir con el resto
            log(f'⚠️ Error procesando "{item["titulo"][:40]}": {e}')
            continue

    if noticias_si:
        mensaje = formatear_mensaje_telegram(noticias_si)
        enviar_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, mensaje)
        log(f"📱 Telegram enviado: {len(noticias_si)} propuestas")
    else:
        log("ℹ️ Sin propuestas SI este ciclo, no se envía TG")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(ejecutar_pipeline())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
