#!/usr/bin/env python3
"""
IA Scout — Pipeline de inteligencia de contenidos para el canal
YouTube "Diario Vida IA" (Paco, @PacoVidaIA).

Flujo:
  1. Fetch RSS blogs, YouTube RSS y Reddit JSON API.
  2. Normaliza cada item al esquema comun.
  3. Deduplica contra la hoja "Hashes" + memoria del ciclo.
  4. Analiza con Claude (claude-haiku-4-5).
  5. Guarda en hoja "ScoutIA" y anota hash en hoja "Hashes".
  6. Envia resumen a Telegram con las propuestas vale=="SI".
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import feedparser
import gspread
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


# ---------------------------------------------------------------------------
# Configuracion
# ---------------------------------------------------------------------------

load_dotenv()

SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "").strip()
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

USER_AGENT = "Mozilla/5.0 (compatible; n8n-rss-bot/2.0)"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 800
CLAUDE_SLEEP = 0.5  # seg entre llamadas
FETCH_TIMEOUT = 20

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "is", "are", "was", "were", "be", "been", "have",
    "has", "do", "does", "will", "would", "could", "should", "can", "this",
    "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
    "my", "your", "its", "our", "their", "what", "which", "who", "how",
    "when", "where", "why", "not", "no", "so", "than", "very", "just",
    "also", "now",
}

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


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def generar_hash(titulo: str, url: str) -> str:
    """Opcion A: base64 truncado (compatible con hashes n8n ya almacenados)."""
    hash_base = (titulo.lower()[:80] + "_" + url.lower()).strip()
    encoded = base64.b64encode(hash_base.encode()).decode()[:20]
    return encoded.replace("+", "x").replace("/", "x").replace("=", "x")


def extraer_keywords(texto: str, maximo: int = 8) -> str:
    if not texto:
        return ""
    palabras = re.findall(r"[A-Za-zÁÉÍÓÚÑÜáéíóúñü0-9]{3,}", texto.lower())
    vistos: list[str] = []
    seen: set[str] = set()
    for p in palabras:
        if p in STOPWORDS or p in seen:
            continue
        seen.add(p)
        vistos.append(p)
        if len(vistos) >= maximo:
            break
    return ", ".join(vistos)


def _clip(texto: str | None, limite: int) -> str:
    if not texto:
        return ""
    texto = texto.strip()
    return texto if len(texto) <= limite else texto[:limite].rstrip() + "…"


# ---------------------------------------------------------------------------
# Autenticacion Google Sheets
# ---------------------------------------------------------------------------

def get_sheets_client() -> gspread.Client:
    token_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

    creds: Credentials | None = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return gspread.authorize(creds)


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_reddit_sources() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    headers = {"User-Agent": USER_AGENT}

    for sub in REDDIT_SOURCES:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
        try:
            r = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            _log(f"⚠️ Reddit /r/{sub}: {e}")
            continue

        for entry in data.get("data", {}).get("children", []):
            d = entry.get("data", {})
            titulo = (d.get("title") or "").strip()
            url_post = "https://www.reddit.com" + d.get("permalink", "")
            if not titulo or not url_post:
                continue

            selftext = (d.get("selftext") or "").strip()
            votos = d.get("ups", 0)
            comentarios = d.get("num_comments", 0)
            preview = f"[{votos}↑ · {comentarios}💬] {selftext}"[:1800]

            items.append({
                "content_hash": generar_hash(titulo, url_post),
                "fecha_detectado": _now_str(),
                "fuente": f"r/{sub}",
                "titulo": titulo,
                "url": url_post,
                "autor": d.get("author") or "",
                "preview": preview,
                "keywords": extraer_keywords(titulo + " " + selftext),
                "notificado": "NO",
            })
    return items


def fetch_rss_blogs() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for blog in RSS_BLOGS:
        try:
            feed = feedparser.parse(
                blog["url"],
                request_headers={"User-Agent": USER_AGENT},
            )
        except Exception as e:
            _log(f"⚠️ RSS {blog['fuente']}: {e}")
            continue

        for entry in feed.entries[:25]:
            titulo = (entry.get("title") or "").strip()
            url = (entry.get("link") or "").strip()
            if not titulo or not url:
                continue
            resumen = entry.get("summary") or entry.get("description") or ""
            resumen = re.sub(r"<[^>]+>", " ", resumen).strip()
            items.append({
                "content_hash": generar_hash(titulo, url),
                "fecha_detectado": _now_str(),
                "fuente": blog["fuente"],
                "titulo": titulo,
                "url": url,
                "autor": blog.get("autor", ""),
                "preview": resumen[:1800],
                "keywords": extraer_keywords(titulo + " " + resumen),
                "notificado": "NO",
            })
    return items


def fetch_youtube_channels() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "media": "http://search.yahoo.com/mrss/",
    }
    for ch in YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=FETCH_TIMEOUT)
            r.raise_for_status()
            root = ET.fromstring(r.content)
        except Exception as e:
            _log(f"⚠️ YouTube {ch['fuente']}: {e}")
            continue

        canal_autor_el = root.find("atom:author/atom:name", ns)
        canal_autor = canal_autor_el.text.strip() if canal_autor_el is not None and canal_autor_el.text else ch["fuente"]

        for entry in root.findall("atom:entry", ns):
            titulo_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            titulo = (titulo_el.text or "").strip() if titulo_el is not None else ""
            link = link_el.get("href", "").strip() if link_el is not None else ""
            if not titulo or not link:
                continue

            desc_el = entry.find("media:group/media:description", ns)
            descripcion = (desc_el.text or "").strip() if desc_el is not None else ""

            items.append({
                "content_hash": generar_hash(titulo, link),
                "fecha_detectado": _now_str(),
                "fuente": ch["fuente"],
                "titulo": titulo,
                "url": link,
                "autor": canal_autor,
                "preview": descripcion[:1800],
                "keywords": extraer_keywords(titulo + " " + descripcion),
                "notificado": "NO",
            })
    return items


# ---------------------------------------------------------------------------
# Deduplicacion
# ---------------------------------------------------------------------------

def leer_hashes_conocidos(gc: gspread.Client, spreadsheet_id: str) -> set[str]:
    sh = gc.open_by_key(spreadsheet_id)
    try:
        hoja = sh.worksheet("Hashes")
    except gspread.WorksheetNotFound:
        hoja = sh.add_worksheet(title="Hashes", rows=1000, cols=2)
        hoja.append_row(["content_hash", "timestamp"])
        return set()
    valores = hoja.col_values(1)
    return {v.strip() for v in valores[1:] if v.strip()}


def escribir_hash(gc: gspread.Client, spreadsheet_id: str, content_hash: str) -> None:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    hoja.append_row([content_hash, datetime.now(timezone.utc).isoformat()])


def es_duplicado(
    item: dict[str, Any],
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
# Analisis Claude
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


def parsear_respuesta_claude(texto: str) -> dict[str, Any]:
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


def analizar_con_claude(client: Anthropic, item: dict[str, Any]) -> dict[str, Any]:
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
# Guardado en Sheets
# ---------------------------------------------------------------------------

def guardar_en_sheets(
    gc: gspread.Client,
    spreadsheet_id: str,
    item: dict[str, Any],
    analisis: dict[str, Any],
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


def _recortar_angulo(angulo: str) -> str:
    if len(angulo) <= 160:
        return angulo
    recortado = angulo[:160]
    ultimo = max(recortado.rfind(". "), recortado.rfind(", "), recortado.rfind(" — "))
    return (recortado[: ultimo + 1] + "…") if ultimo > 80 else (recortado + "…")


def _escape_html(texto: str) -> str:
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def formatear_mensaje_telegram(noticias_si: list[dict[str, Any]]) -> str:
    ahora = datetime.now().strftime("%d/%m %H:%M")
    total = len(noticias_si)

    largos = sorted(
        [n for n in noticias_si if n["formato"] == "largo"],
        key=lambda x: -float(x["puntuacion"]),
    )
    shorts = sorted(
        [n for n in noticias_si if n["formato"] == "short"],
        key=lambda x: -float(x["puntuacion"]),
    )
    resto = [n for n in noticias_si if n["formato"] not in ("largo", "short")]
    final = largos + shorts + resto

    lines = [
        f"📊 <b>SCOUT — {total} propuesta{'s' if total != 1 else ''} nuevas</b> ({ahora})\n"
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

        titulo_html = _escape_html((p.get("titulo") or "")[:60])
        url_html = _escape_html(p.get("url") or "")
        gancho_html = _escape_html(p.get("gancho") or "Sin gancho")
        angulo_html = _escape_html(angulo)

        lines.append(
            f"{i+1}. {fl} {estrellas} {icono} <b>{punt:.0f}/10</b> <i>{fecha}</i>"
        )
        lines.append(f'<a href="{url_html}">{titulo_html}</a>')
        lines.append(f"💡 {gancho_html}")
        if angulo_html:
            lines.append(f"📐 <i>{angulo_html}</i>")
        lines.append("")

    lines.append("─────────────────")
    lines.append('💬 Di "guion del 1" o "más info del 2" a Marius para continuar.')

    return "\n".join(lines)


def enviar_telegram(token: str, chat_id: str, mensaje: str) -> None:
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

def _validar_config() -> None:
    faltantes = [
        k for k, v in {
            "ANTHROPIC_API_KEY": ANTHROPIC_KEY,
            "TELEGRAM_BOT_TOKEN": TG_TOKEN,
            "TELEGRAM_CHAT_ID": TG_CHAT_ID,
            "GOOGLE_SHEETS_ID": SHEETS_ID,
        }.items()
        if not v
    ]
    if faltantes:
        raise SystemExit(f"❌ Faltan variables de entorno: {', '.join(faltantes)}")


def ejecutar_pipeline() -> None:
    _log("🚀 IA Scout iniciando...")
    _validar_config()

    gc = get_sheets_client()
    hashes_conocidos = leer_hashes_conocidos(gc, SHEETS_ID)
    _log(f"📋 Hashes conocidos: {len(hashes_conocidos)}")

    items_raw: list[dict[str, Any]] = []
    items_raw += fetch_reddit_sources()
    items_raw += fetch_rss_blogs()
    items_raw += fetch_youtube_channels()
    _log(f"📥 Items crudos: {len(items_raw)}")

    hashes_batch: set[str] = set()
    titulos_vistos: set[str] = set()
    nuevos = [
        item for item in items_raw
        if not es_duplicado(item, hashes_conocidos, hashes_batch, titulos_vistos)
    ]
    _log(f"✅ Items nuevos: {len(nuevos)} de {len(items_raw)}")

    if not nuevos:
        _log("ℹ️ Sin novedades este ciclo")
        return

    client = Anthropic(api_key=ANTHROPIC_KEY)
    noticias_si: list[dict[str, Any]] = []

    for item in nuevos:
        try:
            analisis = analizar_con_claude(client, item)
            escribir_hash(gc, SHEETS_ID, item["content_hash"])
            guardar_en_sheets(gc, SHEETS_ID, item, analisis)

            if analisis["vale"] == "SI":
                noticias_si.append({**item, **analisis})

            marca = "✅" if analisis["vale"] == "SI" else "❌"
            _log(
                f"{marca} {analisis['puntuacion']}/10 [{item['fuente']}] "
                f"{_clip(item['titulo'], 50)}"
            )
            time.sleep(CLAUDE_SLEEP)
        except Exception as e:
            _log(f"⚠️ Error procesando {_clip(item['titulo'], 40)}: {e}")
            continue

    if noticias_si:
        mensaje = formatear_mensaje_telegram(noticias_si)
        try:
            enviar_telegram(TG_TOKEN, TG_CHAT_ID, mensaje)
            _log(f"📱 Telegram enviado: {len(noticias_si)} propuestas")
        except Exception as e:
            _log(f"⚠️ Error enviando Telegram: {e}")
    else:
        _log("ℹ️ Sin propuestas SI este ciclo, no se envía TG")


if __name__ == "__main__":
    try:
        ejecutar_pipeline()
    except SystemExit:
        raise
    except Exception:
        _log("💥 Fallo crítico:")
        traceback.print_exc()
        sys.exit(1)
