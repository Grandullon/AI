"""IA Scout — content intelligence pipeline for the Diario Vida IA YouTube channel.

Reads RSS + Reddit sources, deduplicates against Google Sheets, scores each item
with Claude, appends the result to the sheet, and sends a Telegram digest of
the winners.

Env vars (loaded from .env in the working directory):
    ANTHROPIC_API_KEY
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    GOOGLE_SHEETS_ID
    GOOGLE_CREDENTIALS_FILE   (default: credentials.json)
    GOOGLE_TOKEN_FILE         (default: token.json)
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import traceback
from datetime import datetime, timezone
from typing import Any

import feedparser
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import gspread

load_dotenv()

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TG_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SHEETS_ID = os.environ["GOOGLE_SHEETS_ID"]
CREDS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.environ.get("GOOGLE_TOKEN_FILE", "token.json")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CLAUDE_MODEL = "claude-haiku-4-5-20251001"
USER_AGENT = "Mozilla/5.0 (compatible; ia-scout/1.0)"

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


def get_sheets_client() -> gspread.Client:
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return gspread.authorize(creds)


def generar_hash(titulo: str, url: str) -> str:
    base = (titulo.lower()[:80] + "_" + url.lower()).strip()
    encoded = base64.b64encode(base.encode()).decode()[:20]
    return encoded.replace("+", "x").replace("/", "x").replace("=", "x")


def extraer_keywords(texto: str, limite: int = 8) -> str:
    palabras = re.findall(r"[a-záéíóúñü0-9]+", texto.lower())
    vistos: list[str] = []
    for p in palabras:
        if len(p) < 3 or p in STOPWORDS or p in vistos:
            continue
        vistos.append(p)
        if len(vistos) >= limite:
            break
    return ", ".join(vistos)


def _timestamp_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def fetch_reddit_sources() -> list[dict]:
    items: list[dict] = []
    for sub in REDDIT_SOURCES:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            r.raise_for_status()
            data = r.json().get("data", {}).get("children", [])
        except Exception as e:
            print(f"⚠️ Reddit r/{sub} falló: {e}")
            continue
        for child in data:
            p = child.get("data", {})
            titulo = (p.get("title") or "").strip()
            permalink = p.get("permalink") or ""
            if not titulo or not permalink:
                continue
            full_url = "https://reddit.com" + permalink
            preview_body = (p.get("selftext") or "")[:1600]
            ups = p.get("ups", 0)
            comments = p.get("num_comments", 0)
            preview = f"{preview_body}\n[↑{ups} votos | 💬{comments} comentarios]".strip()
            items.append({
                "content_hash": generar_hash(titulo, full_url),
                "fecha_detectado": _timestamp_now(),
                "fuente": f"r/{sub}",
                "titulo": titulo,
                "url": full_url,
                "autor": p.get("author") or "unknown",
                "preview": preview[:1800],
                "keywords": extraer_keywords(titulo),
                "notificado": "NO",
            })
        time.sleep(1.0)
    return items


def _parse_feed(url: str) -> Any:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    r.raise_for_status()
    return feedparser.parse(r.content)


def fetch_rss_blogs() -> list[dict]:
    items: list[dict] = []
    for blog in RSS_BLOGS:
        try:
            feed = _parse_feed(blog["url"])
        except Exception as e:
            print(f"⚠️ RSS {blog['fuente']} falló: {e}")
            continue
        for entry in feed.entries[:15]:
            titulo = (entry.get("title") or "").strip()
            link = entry.get("link") or ""
            if not titulo or not link:
                continue
            preview = (entry.get("summary") or entry.get("description") or "")[:1800]
            preview = re.sub(r"<[^>]+>", " ", preview)
            items.append({
                "content_hash": generar_hash(titulo, link),
                "fecha_detectado": _timestamp_now(),
                "fuente": blog["fuente"],
                "titulo": titulo,
                "url": link,
                "autor": blog["autor"],
                "preview": preview,
                "keywords": extraer_keywords(f"{titulo} {preview[:200]}"),
                "notificado": "NO",
            })
    return items


def fetch_youtube_channels() -> list[dict]:
    items: list[dict] = []
    for ch in YOUTUBE_CHANNELS:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
        try:
            feed = _parse_feed(url)
        except Exception as e:
            print(f"⚠️ YouTube {ch['fuente']} falló: {e}")
            continue
        autor = getattr(feed.feed, "title", ch["fuente"])
        for entry in feed.entries[:10]:
            titulo = (entry.get("title") or "").strip()
            link = entry.get("link") or ""
            if not titulo or not link:
                continue
            preview = ""
            media = entry.get("media_group") or entry.get("summary_detail")
            if isinstance(media, dict):
                preview = media.get("value", "")
            preview = (preview or entry.get("summary") or "")[:1800]
            items.append({
                "content_hash": generar_hash(titulo, link),
                "fecha_detectado": _timestamp_now(),
                "fuente": ch["fuente"],
                "titulo": titulo,
                "url": link,
                "autor": autor,
                "preview": preview,
                "keywords": extraer_keywords(f"{titulo} {preview[:200]}"),
                "notificado": "NO",
            })
    return items


def leer_hashes_conocidos(gc: gspread.Client) -> set[str]:
    hoja = gc.open_by_key(SHEETS_ID).worksheet("Hashes")
    valores = hoja.col_values(1)
    return {v.strip() for v in valores[1:] if v.strip()}


def escribir_hash(gc: gspread.Client, content_hash: str) -> None:
    hoja = gc.open_by_key(SHEETS_ID).worksheet("Hashes")
    hoja.append_row([content_hash, datetime.now(timezone.utc).isoformat()])


def es_duplicado(item: dict, conocidos: set[str], batch: set[str], titulos: set[str]) -> bool:
    h = item["content_hash"]
    titulo_norm = re.sub(r"[^a-z0-9áéíóúñü\s]", "", item["titulo"].lower()).strip()[:80]
    if h in conocidos or h in batch or titulo_norm in titulos:
        return True
    batch.add(h)
    titulos.add(titulo_norm)
    return False


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


def _defaults() -> dict:
    return {"vale": "NO", "formato": "ninguno", "puntuacion": 0, "gancho": "", "angulo": "Sin análisis"}


def parsear_respuesta_claude(texto: str) -> dict:
    d = _defaults()
    try:
        clean = texto.replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{[\s\S]*\}", clean)
        if not match:
            return d
        p = json.loads(match.group(0))
        vr = str(p.get("vale", "")).upper().strip()
        fr = str(p.get("formato", "")).lower().strip()
        return {
            "vale": "SI" if vr in ("SI", "YES", "TRUE") else "NO",
            "formato": fr if fr in ("short", "largo") else "ninguno",
            "puntuacion": min(10, max(0, int(float(p.get("puntuacion", 0))))),
            "gancho": str(p.get("gancho", "")).strip(),
            "angulo": str(p.get("angulo", "")).strip() or "Sin descripción",
        }
    except Exception as e:
        d["angulo"] = f"Error: {str(e)[:100]}"
        return d


_client = Anthropic(api_key=ANTHROPIC_API_KEY)


def analizar_con_claude(item: dict) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        fuente=item["fuente"],
        titulo=item["titulo"],
        autor=item["autor"],
        url=item["url"],
        preview=(item.get("preview") or "")[:1500],
        keywords=item.get("keywords", ""),
    )
    for attempt in range(3):
        try:
            resp = _client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            texto = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
            return parsear_respuesta_claude(texto)
        except Exception as e:
            if attempt == 2:
                d = _defaults()
                d["angulo"] = f"Claude error: {str(e)[:80]}"
                return d
            time.sleep(1.5 * (attempt + 1))
    return _defaults()


def guardar_en_sheets(gc: gspread.Client, item: dict, analisis: dict) -> None:
    hoja = gc.open_by_key(SHEETS_ID).worksheet("ScoutIA")
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


FUENTE_ICONS = {
    "r/notebooklm": "🔴", "r/PromptEngineering": "🔴",
    "r/ArtificialInteligence": "🔴", "r/ChatGPT": "🔴",
    "r/ClaudeAI": "🔴", "r/productivity": "🔴",
    "OneUsefulThing": "🔬", "SimonWillison": "🔬",
}


def formatear_mensaje_telegram(noticias_si: list[dict]) -> str:
    ahora = datetime.now().strftime("%d/%m %H:%M")
    total = len(noticias_si)
    largos = sorted([n for n in noticias_si if n["formato"] == "largo"], key=lambda x: -x["puntuacion"])
    shorts = sorted([n for n in noticias_si if n["formato"] == "short"], key=lambda x: -x["puntuacion"])
    resto = [n for n in noticias_si if n["formato"] not in ("largo", "short")]
    final = largos + shorts + resto
    plural = "s" if total != 1 else ""
    lines = [f"📊 <b>SCOUT — {total} propuesta{plural} nuevas</b> ({ahora})\n"]
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
        angulo = p.get("angulo", "")
        if len(angulo) > 160:
            recortado = angulo[:160]
            ultimo = max(recortado.rfind(". "), recortado.rfind(", "), recortado.rfind(" — "))
            angulo = (recortado[:ultimo + 1] + "…") if ultimo > 80 else (recortado + "…")
        lines.append(f'{i+1}. {fl} {estrellas} {icono} <b>{punt:.0f}/10</b> <i>{fecha}</i>')
        lines.append(f'<a href="{p["url"]}">{p["titulo"][:60]}</a>')
        lines.append(f'💡 {p.get("gancho") or "Sin gancho"}')
        if angulo:
            lines.append(f"📐 <i>{angulo}</i>")
        lines.append("")
    lines.append("─────────────────")
    lines.append('💬 Di "guion del 1" o "más info del 2" a Marius para continuar.')
    return "\n".join(lines)


def enviar_telegram(mensaje: str) -> None:
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={"chat_id": TG_CHAT_ID, "text": mensaje, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=15,
    )
    resp.raise_for_status()


def ejecutar_pipeline() -> None:
    print("🚀 IA Scout iniciando...")
    gc = get_sheets_client()
    conocidos = leer_hashes_conocidos(gc)
    print(f"📋 Hashes conocidos: {len(conocidos)}")

    items = fetch_reddit_sources() + fetch_rss_blogs() + fetch_youtube_channels()
    print(f"📥 Items crudos: {len(items)}")

    batch: set[str] = set()
    titulos: set[str] = set()
    nuevos = [it for it in items if not es_duplicado(it, conocidos, batch, titulos)]
    print(f"✅ Items nuevos: {len(nuevos)} de {len(items)}")

    if not nuevos:
        print("ℹ️ Sin novedades este ciclo")
        return

    noticias_si: list[dict] = []
    for item in nuevos:
        try:
            analisis = analizar_con_claude(item)
            escribir_hash(gc, item["content_hash"])
            guardar_en_sheets(gc, item, analisis)
            if analisis["vale"] == "SI":
                noticias_si.append({**item, **analisis})
            marca = "✅" if analisis["vale"] == "SI" else "❌"
            print(f'{marca} {analisis["puntuacion"]}/10 — {item["titulo"][:60]}')
            time.sleep(0.5)
        except Exception as e:
            print(f'⚠️ Error procesando {item["titulo"][:40]}: {e}')
            traceback.print_exc()

    if noticias_si:
        enviar_telegram(formatear_mensaje_telegram(noticias_si))
        print(f"📱 Telegram enviado: {len(noticias_si)} propuestas")
    else:
        print("ℹ️ Sin propuestas SI este ciclo, no se envía TG")


if __name__ == "__main__":
    ejecutar_pipeline()
