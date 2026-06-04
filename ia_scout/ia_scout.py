"""IA Scout — pipeline de monitorización de contenidos para Diario Vida IA."""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from html import unescape
from typing import Any, Iterable

import feedparser
import gspread
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# ──────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "714952561")
SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "1faHu7YYpBD3yg4ZCdOS3KNcJPnsuaRuuDVFqodrXDX8")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 800
CLAUDE_PAUSE_SECONDS = 0.5

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
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
    "our", "their", "what", "which", "who", "how", "when", "where", "why",
    "not", "no", "so", "than", "very", "just", "also", "now",
}

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

BONO NOTEBOOKLM: suma +1 punto a cualquier contenido sobre NotebookLM con puntuación base >=5.

EJEMPLOS CALIBRADOS:
- "NotebookLM añade diapositivas editables" -> 9
- "Cómo uso NotebookLM para estudiar protocolos médicos" -> 8
- "Claude vs ChatGPT para redactar informes" -> 7
- "Hilo Reddit: NotebookLM me ha cambiado el trabajo" -> 7
- "Build an AI agent with Python" -> 2
- "OpenAI recauda 110B" -> 3

---

FORMATOS:
- SHORT: Un truco, comparativa visual, dato sorprendente, experiencia real resumida (<=60s)
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

REGLA FINAL: si dudas y puntuación >=5, pon SI.
"""

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


# ──────────────────────────────────────────────────────────────────────────────
# UTILIDADES
# ──────────────────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def ahora_es() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def limpiar_html(texto: str) -> str:
    if not texto:
        return ""
    sin_tags = re.sub(r"<[^>]+>", " ", texto)
    sin_tags = unescape(sin_tags)
    return re.sub(r"\s+", " ", sin_tags).strip()


def truncar(texto: str, n: int) -> str:
    if not texto:
        return ""
    return texto if len(texto) <= n else texto[:n].rstrip() + "…"


def generar_hash(titulo: str, url: str) -> str:
    base = (titulo.lower()[:80] + "_" + url.lower()).strip()
    encoded = base64.b64encode(base.encode("utf-8")).decode("ascii")[:20]
    return encoded.replace("+", "x").replace("/", "x").replace("=", "x")


def extraer_keywords(texto: str, max_kw: int = 8) -> str:
    if not texto:
        return ""
    palabras = re.findall(r"[a-záéíóúñü0-9]+", texto.lower())
    vistos: dict[str, int] = {}
    for p in palabras:
        if len(p) < 4 or p in STOPWORDS:
            continue
        vistos[p] = vistos.get(p, 0) + 1
    ordenadas = sorted(vistos.items(), key=lambda kv: (-kv[1], kv[0]))
    return ", ".join(p for p, _ in ordenadas[:max_kw])


# ──────────────────────────────────────────────────────────────────────────────
# AUTENTICACIÓN GOOGLE SHEETS (OAuth desktop)
# ──────────────────────────────────────────────────────────────────────────────

def get_sheets_client() -> gspread.Client:
    creds = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Falta {GOOGLE_CREDENTIALS_FILE}. Descárgalo desde Google Cloud Console (OAuth Desktop)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(GOOGLE_TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return gspread.authorize(creds)


# ──────────────────────────────────────────────────────────────────────────────
# FETCHERS
# ──────────────────────────────────────────────────────────────────────────────

def fetch_reddit_sources() -> list[dict]:
    items: list[dict] = []
    headers = {"User-Agent": USER_AGENT}
    for sub in REDDIT_SOURCES:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
        try:
            r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            if r.status_code != 200:
                log(f"⚠️ Reddit r/{sub} HTTP {r.status_code}")
                continue
            data = r.json()
            children = data.get("data", {}).get("children", [])
            for child in children:
                d = child.get("data", {})
                titulo = (d.get("title") or "").strip()
                permalink = d.get("permalink") or ""
                url_post = f"https://www.reddit.com{permalink}" if permalink else (d.get("url") or "")
                if not titulo or not url_post:
                    continue

                selftext = (d.get("selftext") or "").strip()
                votos = d.get("ups", 0)
                comentarios = d.get("num_comments", 0)
                preview = f"[👍{votos} 💬{comentarios}] {selftext}"[:1800]

                autor = d.get("author") or "unknown"
                created_utc = d.get("created_utc")
                if created_utc:
                    fecha = datetime.fromtimestamp(created_utc, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
                else:
                    fecha = ahora_es()

                texto_kw = f"{titulo} {selftext}"
                items.append({
                    "content_hash": generar_hash(titulo, url_post),
                    "fecha_detectado": fecha,
                    "fuente": f"r/{sub}",
                    "titulo": titulo,
                    "url": url_post,
                    "autor": autor,
                    "preview": preview,
                    "keywords": extraer_keywords(texto_kw),
                    "notificado": "NO",
                })
            log(f"📥 Reddit r/{sub}: {len(children)} items")
        except Exception as e:
            log(f"⚠️ Reddit r/{sub} error: {e}")
            continue
    return items


def _parse_feed(url: str) -> Any:
    headers = {"User-Agent": USER_AGENT}
    try:
        r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return feedparser.parse(r.content)
    except Exception:
        return feedparser.parse(url)


def fetch_rss_blogs() -> list[dict]:
    items: list[dict] = []
    for blog in RSS_BLOGS:
        try:
            parsed = _parse_feed(blog["url"])
            entries = parsed.entries if hasattr(parsed, "entries") else []
            for e in entries[:25]:
                titulo = (getattr(e, "title", "") or "").strip()
                url = (getattr(e, "link", "") or "").strip()
                if not titulo or not url:
                    continue

                summary = getattr(e, "summary", "") or getattr(e, "description", "") or ""
                content_list = getattr(e, "content", None)
                if content_list:
                    try:
                        summary = content_list[0].get("value", summary)
                    except Exception:
                        pass
                preview = limpiar_html(summary)[:1800]

                published_parsed = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
                if published_parsed:
                    fecha = datetime(*published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
                else:
                    fecha = ahora_es()

                items.append({
                    "content_hash": generar_hash(titulo, url),
                    "fecha_detectado": fecha,
                    "fuente": blog["fuente"],
                    "titulo": titulo,
                    "url": url,
                    "autor": blog.get("autor") or getattr(e, "author", "") or "",
                    "preview": preview,
                    "keywords": extraer_keywords(f"{titulo} {preview}"),
                    "notificado": "NO",
                })
            log(f"📥 RSS {blog['fuente']}: {len(entries)} entries")
        except Exception as e:
            log(f"⚠️ RSS {blog['fuente']} error: {e}")
            continue
    return items


def fetch_youtube_channels() -> list[dict]:
    items: list[dict] = []
    for ch in YOUTUBE_CHANNELS:
        try:
            url_feed = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
            parsed = _parse_feed(url_feed)
            entries = parsed.entries if hasattr(parsed, "entries") else []
            for e in entries[:15]:
                titulo = (getattr(e, "title", "") or "").strip()
                url = (getattr(e, "link", "") or "").strip()
                if not titulo or not url:
                    continue

                autor = (getattr(e, "author", "") or ch["fuente"].replace("YT:", "")).strip()
                summary = getattr(e, "summary", "") or ""
                preview = limpiar_html(summary)[:1800]

                published_parsed = getattr(e, "published_parsed", None) or getattr(e, "updated_parsed", None)
                if published_parsed:
                    fecha = datetime(*published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
                else:
                    fecha = ahora_es()

                items.append({
                    "content_hash": generar_hash(titulo, url),
                    "fecha_detectado": fecha,
                    "fuente": ch["fuente"],
                    "titulo": titulo,
                    "url": url,
                    "autor": autor,
                    "preview": preview,
                    "keywords": extraer_keywords(f"{titulo} {preview}"),
                    "notificado": "NO",
                })
            log(f"📥 YouTube {ch['fuente']}: {len(entries)} videos")
        except Exception as e:
            log(f"⚠️ YouTube {ch['fuente']} error: {e}")
            continue
    return items


# ──────────────────────────────────────────────────────────────────────────────
# DEDUPLICACIÓN
# ──────────────────────────────────────────────────────────────────────────────

def leer_hashes_conocidos(gc: gspread.Client) -> set[str]:
    sh = gc.open_by_key(SHEETS_ID)
    hoja = sh.worksheet("Hashes")
    valores = hoja.col_values(1)
    return {v.strip() for v in valores[1:] if v.strip()}


def escribir_hash(gc: gspread.Client, content_hash: str) -> None:
    sh = gc.open_by_key(SHEETS_ID)
    hoja = sh.worksheet("Hashes")
    hoja.append_row([content_hash, datetime.now(timezone.utc).isoformat()])


def _titulo_normalizado(titulo: str) -> str:
    return re.sub(r"[^a-z0-9áéíóúñü\s]", "", titulo.lower()).strip()[:80]


def es_duplicado(item: dict, conocidos: set[str], batch: set[str], titulos: set[str]) -> bool:
    h = item["content_hash"]
    tn = _titulo_normalizado(item["titulo"])

    if h in conocidos:
        return True
    if h in batch:
        return True
    if tn and tn in titulos:
        return True

    batch.add(h)
    if tn:
        titulos.add(tn)
    return False


# ──────────────────────────────────────────────────────────────────────────────
# CLAUDE
# ──────────────────────────────────────────────────────────────────────────────

_claude_client: Anthropic | None = None


def get_claude_client() -> Anthropic:
    global _claude_client
    if _claude_client is None:
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("Falta ANTHROPIC_API_KEY en .env")
        _claude_client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _claude_client


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
    client = get_claude_client()
    prompt = PROMPT_TEMPLATE.format(
        fuente=item.get("fuente", ""),
        titulo=item.get("titulo", ""),
        autor=item.get("autor", ""),
        url=item.get("url", ""),
        preview=truncar(item.get("preview", ""), 1800),
        keywords=item.get("keywords", ""),
    )
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    texto = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    time.sleep(CLAUDE_PAUSE_SECONDS)
    return parsear_respuesta_claude(texto)


# ──────────────────────────────────────────────────────────────────────────────
# GOOGLE SHEETS — ScoutIA
# ──────────────────────────────────────────────────────────────────────────────

def guardar_en_sheets(gc: gspread.Client, item: dict, analisis: dict) -> None:
    sh = gc.open_by_key(SHEETS_ID)
    hoja = sh.worksheet("ScoutIA")
    fila = [
        item["content_hash"],
        item["fecha_detectado"],
        item["fuente"],
        item["titulo"],
        item["url"],
        item.get("autor", ""),
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


# ──────────────────────────────────────────────────────────────────────────────
# TELEGRAM
# ──────────────────────────────────────────────────────────────────────────────

def formatear_mensaje_telegram(noticias_si: list[dict]) -> str:
    ahora = datetime.now().strftime("%d/%m %H:%M")
    total = len(noticias_si)

    largos = sorted([n for n in noticias_si if n["formato"] == "largo"], key=lambda x: -float(x.get("puntuacion", 0)))
    shorts = sorted([n for n in noticias_si if n["formato"] == "short"], key=lambda x: -float(x.get("puntuacion", 0)))
    resto = [n for n in noticias_si if n["formato"] not in ("largo", "short")]
    final = largos + shorts + resto

    lines = [f'📊 <b>SCOUT — {total} propuesta{"s" if total != 1 else ""} nuevas</b> ({ahora})\n']

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

        angulo = p.get("angulo", "") or ""
        if len(angulo) > 160:
            recortado = angulo[:160]
            ultimo = max(recortado.rfind(". "), recortado.rfind(", "), recortado.rfind(" — "))
            angulo = (recortado[: ultimo + 1] + "…") if ultimo > 80 else (recortado + "…")

        titulo_corto = p["titulo"][:60].replace("<", "&lt;").replace(">", "&gt;")

        lines.append(f"{i+1}. {fl} {estrellas} {icono} <b>{punt:.0f}/10</b> <i>{fecha}</i>")
        lines.append(f'<a href="{p["url"]}">{titulo_corto}</a>')
        lines.append(f'💡 {p.get("gancho") or "Sin gancho"}')
        if angulo:
            lines.append(f"📐 <i>{angulo}</i>")
        lines.append("")

    lines.append("─────────────────")
    lines.append('💬 Di "guion del 1" o "más info del 2" a Marius para continuar.')

    return "\n".join(lines)


def enviar_telegram(mensaje: str) -> None:
    if not TELEGRAM_BOT_TOKEN:
        log("⚠️ Falta TELEGRAM_BOT_TOKEN: no se envía Telegram")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code != 200:
        log(f"⚠️ Telegram HTTP {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()


# ──────────────────────────────────────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ──────────────────────────────────────────────────────────────────────────────

def ejecutar_pipeline() -> None:
    log("🚀 IA Scout iniciando...")

    gc = get_sheets_client()
    hashes_conocidos = leer_hashes_conocidos(gc)
    log(f"📋 Hashes conocidos: {len(hashes_conocidos)}")

    items_raw: list[dict] = []
    items_raw += fetch_reddit_sources()
    items_raw += fetch_rss_blogs()
    items_raw += fetch_youtube_channels()
    log(f"📥 Items crudos: {len(items_raw)}")

    hashes_batch: set[str] = set()
    titulos_vistos: set[str] = set()
    nuevos = [it for it in items_raw if not es_duplicado(it, hashes_conocidos, hashes_batch, titulos_vistos)]
    log(f"✅ Items nuevos: {len(nuevos)} de {len(items_raw)}")

    if not nuevos:
        log("ℹ️ Sin novedades este ciclo")
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
            log(f'{marca} {analisis["puntuacion"]:.0f}/10 — {item["titulo"][:50]}')
        except Exception as e:
            log(f'⚠️ Error procesando "{item["titulo"][:40]}": {e}')
            traceback.print_exc()
            continue

    if noticias_si:
        mensaje = formatear_mensaje_telegram(noticias_si)
        try:
            enviar_telegram(mensaje)
            log(f"📱 Telegram enviado: {len(noticias_si)} propuestas")
        except Exception as e:
            log(f"⚠️ Error enviando Telegram: {e}")
    else:
        log("ℹ️ Sin propuestas SI este ciclo, no se envía TG")


if __name__ == "__main__":
    try:
        ejecutar_pipeline()
    except KeyboardInterrupt:
        log("⏹ Interrumpido por usuario")
        sys.exit(130)
    except Exception as e:
        log(f"💥 Error fatal: {e}")
        traceback.print_exc()
        sys.exit(1)
