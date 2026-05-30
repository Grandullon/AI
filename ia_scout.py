"""IA Scout — pipeline de inteligencia de contenidos para Diario Vida IA.

Monitoriza RSS y Reddit, deduplica, analiza con Claude, guarda en Google Sheets
y envía resumen por Telegram.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from xml.etree import ElementTree as ET

import feedparser
import gspread
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


load_dotenv()


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 800
CLAUDE_SLEEP_SECONDS = 0.5

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

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
# Auth Google Sheets
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
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return gspread.authorize(creds)


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def generar_hash(titulo: str, url: str) -> str:
    hash_base = (titulo.lower()[:80] + "_" + url.lower()).strip()
    encoded = base64.b64encode(hash_base.encode()).decode()[:20]
    return encoded.replace("+", "x").replace("/", "x").replace("=", "x")


def extraer_keywords(texto: str, limite: int = 8) -> str:
    palabras = re.findall(r"[a-záéíóúñü0-9]{4,}", texto.lower())
    vistas: set[str] = set()
    keys: list[str] = []
    for p in palabras:
        if p in STOPWORDS or p in vistas:
            continue
        vistas.add(p)
        keys.append(p)
        if len(keys) >= limite:
            break
    return ", ".join(keys)


def ahora_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def safe_text(html_or_text: str | None, limite: int = 1800) -> str:
    if not html_or_text:
        return ""
    sin_tags = re.sub(r"<[^>]+>", " ", html_or_text)
    sin_tags = re.sub(r"\s+", " ", sin_tags).strip()
    return sin_tags[:limite]


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_reddit_sources() -> list[dict]:
    items: list[dict] = []
    headers = {"User-Agent": USER_AGENT}
    for sub in REDDIT_SOURCES:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"⚠️ Reddit r/{sub}: HTTP {resp.status_code}")
                continue
            data = resp.json()
            for child in data.get("data", {}).get("children", []):
                d = child.get("data", {})
                titulo = (d.get("title") or "").strip()
                permalink = d.get("permalink") or ""
                post_url = f"https://www.reddit.com{permalink}"
                selftext = d.get("selftext") or ""
                votos = d.get("ups", 0)
                comentarios = d.get("num_comments", 0)
                preview_body = f"[{votos}↑ {comentarios}💬] {selftext}".strip()
                preview = safe_text(preview_body, 1800)
                autor = d.get("author") or "—"
                items.append({
                    "content_hash": generar_hash(titulo, post_url),
                    "fecha_detectado": ahora_str(),
                    "fuente": f"r/{sub}",
                    "titulo": titulo,
                    "url": post_url,
                    "autor": autor,
                    "preview": preview,
                    "keywords": extraer_keywords(titulo + " " + selftext),
                    "notificado": "NO",
                })
        except Exception as e:
            print(f"⚠️ Reddit r/{sub} error: {e}")
            continue
    return items


def fetch_rss_blogs() -> list[dict]:
    items: list[dict] = []
    for blog in RSS_BLOGS:
        try:
            feed = feedparser.parse(blog["url"])
            for entry in feed.entries[:20]:
                titulo = (entry.get("title") or "").strip()
                link = entry.get("link") or ""
                resumen = entry.get("summary") or entry.get("description") or ""
                preview = safe_text(resumen, 1800)
                items.append({
                    "content_hash": generar_hash(titulo, link),
                    "fecha_detectado": ahora_str(),
                    "fuente": blog["fuente"],
                    "titulo": titulo,
                    "url": link,
                    "autor": blog["autor"],
                    "preview": preview,
                    "keywords": extraer_keywords(titulo + " " + preview),
                    "notificado": "NO",
                })
        except Exception as e:
            print(f"⚠️ RSS {blog['fuente']} error: {e}")
            continue
    return items


def fetch_youtube_channels() -> list[dict]:
    items: list[dict] = []
    headers = {"User-Agent": USER_AGENT}
    for ch in YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"⚠️ YT {ch['fuente']}: HTTP {resp.status_code}")
                continue
            root = ET.fromstring(resp.content)
            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "media": "http://search.yahoo.com/mrss/",
            }
            for entry in root.findall("atom:entry", ns)[:15]:
                titulo_el = entry.find("atom:title", ns)
                link_el = entry.find("atom:link", ns)
                author_el = entry.find("atom:author/atom:name", ns)
                desc_el = entry.find("media:group/media:description", ns)

                titulo = (titulo_el.text or "").strip() if titulo_el is not None else ""
                link = link_el.get("href") if link_el is not None else ""
                autor = (author_el.text or "").strip() if author_el is not None else ""
                desc = (desc_el.text or "").strip() if desc_el is not None else ""

                items.append({
                    "content_hash": generar_hash(titulo, link),
                    "fecha_detectado": ahora_str(),
                    "fuente": ch["fuente"],
                    "titulo": titulo,
                    "url": link,
                    "autor": autor,
                    "preview": safe_text(desc, 1800),
                    "keywords": extraer_keywords(titulo + " " + desc),
                    "notificado": "NO",
                })
        except Exception as e:
            print(f"⚠️ YT {ch['fuente']} error: {e}")
            continue
    return items


# ---------------------------------------------------------------------------
# Deduplicación
# ---------------------------------------------------------------------------

def leer_hashes_conocidos(gc: gspread.Client, spreadsheet_id: str) -> set[str]:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    valores = hoja.col_values(1)
    return set(v.strip() for v in valores[1:] if v.strip())


def escribir_hash(gc: gspread.Client, spreadsheet_id: str, content_hash: str) -> None:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    hoja.append_row([content_hash, datetime.now(timezone.utc).isoformat()])


def _titulo_normalizado(titulo: str) -> str:
    return re.sub(r"[^a-z0-9áéíóúñü\s]", "", titulo.lower()).strip()[:80]


def es_duplicado(
    item: dict,
    hashes_conocidos: set[str],
    hashes_batch: set[str],
    titulos_vistos: set[str],
) -> bool:
    h = item["content_hash"]
    titulo_norm = _titulo_normalizado(item["titulo"])

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
        return {
            "vale": "SI" if vr in ("SI", "YES", "TRUE") else "NO",
            "formato": fr if fr in ("short", "largo") else "ninguno",
            "puntuacion": min(10, max(0, float(p.get("puntuacion", 0)))),
            "gancho": str(p.get("gancho", "")).strip(),
            "angulo": str(p.get("angulo", "")).strip() or "Sin descripción",
        }
    except Exception as e:
        out = defaults.copy()
        out["angulo"] = f"Error: {str(e)[:100]}"
        return out


_anthropic_client: Anthropic | None = None


def _get_anthropic() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def analizar_con_claude(item: dict) -> dict:
    client = _get_anthropic()
    prompt = PROMPT_TEMPLATE.format(
        fuente=item.get("fuente", ""),
        titulo=item.get("titulo", ""),
        autor=item.get("autor", ""),
        url=item.get("url", ""),
        preview=(item.get("preview") or "")[:1800],
        keywords=item.get("keywords", ""),
    )
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        )
        return parsear_respuesta_claude(texto)
    except Exception as e:
        print(f"⚠️ Claude error: {e}")
        return {
            "vale": "NO",
            "formato": "ninguno",
            "puntuacion": 0,
            "gancho": "",
            "angulo": f"Error API: {str(e)[:100]}",
        }
    finally:
        time.sleep(CLAUDE_SLEEP_SECONDS)


# ---------------------------------------------------------------------------
# Guardado en Sheets
# ---------------------------------------------------------------------------

def guardar_en_sheets(
    gc: gspread.Client,
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
# Telegram
# ---------------------------------------------------------------------------

def _escape_html(texto: str) -> str:
    return (
        texto.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _recortar_angulo(angulo: str, limite: int = 160) -> str:
    if len(angulo) <= limite:
        return angulo
    recortado = angulo[:limite]
    ultimo = max(
        recortado.rfind(". "),
        recortado.rfind(", "),
        recortado.rfind(" — "),
    )
    if ultimo > 80:
        return recortado[: ultimo + 1] + "…"
    return recortado + "…"


def formatear_mensaje_telegram(noticias_si: list[dict]) -> str:
    ahora = datetime.now().strftime("%d/%m %H:%M")
    total = len(noticias_si)

    largos = sorted(
        [n for n in noticias_si if n["formato"] == "largo"],
        key=lambda x: -float(x.get("puntuacion", 0)),
    )
    shorts = sorted(
        [n for n in noticias_si if n["formato"] == "short"],
        key=lambda x: -float(x.get("puntuacion", 0)),
    )
    resto = [n for n in noticias_si if n["formato"] not in ("largo", "short")]
    final = largos + shorts + resto

    plural = "s" if total != 1 else ""
    lines = [f'📊 <b>SCOUT — {total} propuesta{plural} nuevas</b> ({ahora})\n']

    en_shorts = False
    for i, p in enumerate(final):
        if p["formato"] == "largo":
            fl = "🎬 LARGO"
        elif p["formato"] == "short":
            fl = "⚡ SHORT"
        else:
            fl = "📄"

        punt = float(p.get("puntuacion", 0))
        estrellas = "⭐" * min(round(punt / 2), 5)
        icono = FUENTE_ICONS.get(p["fuente"]) or (
            "📺" if p["fuente"].startswith("YT:") else "🌐"
        )

        if p["formato"] == "short" and not en_shorts and largos:
            lines.append("· · · · · · · · ·")
            en_shorts = True

        fecha_raw = (p.get("fecha_detectado") or "")[:16].replace("T", " ")
        fecha = fecha_raw[5:] if len(fecha_raw) >= 5 else fecha_raw

        angulo = _recortar_angulo(p.get("angulo", ""))

        titulo_safe = _escape_html(p["titulo"][:60])
        url_safe = _escape_html(p["url"])
        gancho_safe = _escape_html(p.get("gancho") or "Sin gancho")
        angulo_safe = _escape_html(angulo)

        lines.append(
            f'{i+1}. {fl} {estrellas} {icono} <b>{punt:.0f}/10</b> <i>{fecha}</i>'
        )
        lines.append(f'<a href="{url_safe}">{titulo_safe}</a>')
        lines.append(f"💡 {gancho_safe}")
        if angulo:
            lines.append(f"📐 <i>{angulo_safe}</i>")
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

def ejecutar_pipeline() -> None:
    print("🚀 IA Scout iniciando...")

    gc = get_sheets_client()
    hashes_conocidos = leer_hashes_conocidos(gc, SHEETS_ID)
    print(f"📋 Hashes conocidos: {len(hashes_conocidos)}")

    items_raw: list[dict] = []
    items_raw += fetch_reddit_sources()
    items_raw += fetch_rss_blogs()
    items_raw += fetch_youtube_channels()
    print(f"📥 Items crudos: {len(items_raw)}")

    hashes_batch: set[str] = set()
    titulos_vistos: set[str] = set()
    nuevos: list[dict] = []
    for item in items_raw:
        if not es_duplicado(item, hashes_conocidos, hashes_batch, titulos_vistos):
            nuevos.append(item)
    print(f"✅ Items nuevos: {len(nuevos)} de {len(items_raw)}")

    if not nuevos:
        print("ℹ️ Sin novedades este ciclo")
        return

    noticias_si: list[dict] = []
    for item in nuevos:
        try:
            analisis = analizar_con_claude(item)
            escribir_hash(gc, SHEETS_ID, item["content_hash"])
            guardar_en_sheets(gc, SHEETS_ID, item, analisis)

            if analisis["vale"] == "SI":
                noticias_si.append({**item, **analisis})

            marca = "✅" if analisis["vale"] == "SI" else "❌"
            titulo_log = item["titulo"][:50]
            print(f'{marca} {analisis["puntuacion"]}/10 — [{item["fuente"]}] {titulo_log}')
        except Exception as e:
            print(f'⚠️ Error procesando {item["titulo"][:40]}: {e}')
            continue

    if noticias_si:
        mensaje = formatear_mensaje_telegram(noticias_si)
        enviar_telegram(TG_TOKEN, TG_CHAT_ID, mensaje)
        print(f"📱 Telegram enviado: {len(noticias_si)} propuestas")
    else:
        print("ℹ️ Sin propuestas SI este ciclo, no se envía TG")


if __name__ == "__main__":
    ejecutar_pipeline()
