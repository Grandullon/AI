"""IA Scout — pipeline de inteligencia de contenidos para "Diario Vida IA".

Monitoriza fuentes RSS y Reddit, deduplica, analiza con Claude, guarda en
Google Sheets y envia un resumen por Telegram.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import feedparser
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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
USER_AGENT = "Mozilla/5.0 (compatible; n8n-rss-bot/2.0)"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

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

CLAUDE_PROMPT_TEMPLATE = """Eres el editor de contenido de "Diario Vida IA", canal YouTube espanol con 15.200 suscriptores creciendo a +100/dia.

CONTEXTO DEL CANAL:
- PILAR PRINCIPAL (60% del contenido): NotebookLM. Cualquier novedad, truco, caso de uso, integracion o experiencia real con NotebookLM tiene prioridad maxima automatica.
- PILAR 2: IA practica para trabajadores del conocimiento (ChatGPT, Claude, Gemini, Perplexity). Casos de uso reales, no demos de laboratorio.
- PILAR 3: Automatizacion y productividad (n8n, flujos de trabajo, ahorrar tiempo real).
- DESCARTAR SIEMPRE: desarrollo de software, programacion pura, hardware, gaming, ciencia sin aplicacion practica, noticias corporativas sin impacto en el usuario.

AUDIENCIA: Profesionales 30-50 anos, trabajadores del conocimiento (medicos, RRHH, profesores, administrativos, gestores). Usan IA en su trabajo pero NO son programadores. Quieren resultados en menos de 10 minutos. Desconfian del hype. Valoran la honestidad sobre las limitaciones.

ESTILO DEL CANAL: Anti-guru. Directo. Sin "revolucionario", sin emojis de cohete. El presentador es Paco, trabaja en un hospital (RRHH), 500+ dias de constancia personal. Credibilidad por resultados reales, no por promesas.

---

NOTICIA A EVALUAR:
Fuente: {fuente}
Titulo: {titulo}
Autor: {autor}
URL: {url}
Contenido: {preview}
Keywords: {keywords}

---

TIPOS DE CONTENIDO QUE SI INTERESAN:

1. NOTEBOOKLM - cualquier cosa: update, truco, caso de uso, integracion, comparativa, experiencia real. PUNTUACION MINIMA 6 automatico si tiene angulo demostrable.

2. HILO REDDIT con experiencias reales - usuarios contando que les funciono o fallo. Angulo: "esto le pasa a tu audiencia tambien".

3. HERRAMIENTA NUEVA para no-devs - si se puede probar en menos de 5 minutos, vale.

4. ACTUALIDAD IA con impacto practico - funciones nuevas en ChatGPT, Claude, Gemini que cambien el flujo de trabajo diario.

5. COMPARATIVA practica - "X vs Y para hacer Z", "probe 3 formas de hacer esto".

6. ERROR O LIMITACION REAL - fallo, workaround o decepcion documentada. Angulo honesto.

---

ESCALA DE PUNTUACION:

1: Spam, irrelevante total
2: Fuera de nicho (hardware, gaming, ciencia pura, eventos)
3: IA generica sin angulo para trabajadores no-dev
4: Angulo debil o contenido escaso
5: Decente pero no urgente
6: Bueno - relevante + angulo claro + grabar esta semana
7: Muy bueno - busquedas activas + demostrable + util ahora
8: Excelente - alto potencial + aplicable hoy + diferenciador
9-10: Exclusiva o tendencia emergente con ventana corta

BONO NOTEBOOKLM: suma +1 punto a cualquier contenido sobre NotebookLM con puntuacion base >=5.

EJEMPLOS CALIBRADOS:
- "NotebookLM anade diapositivas editables" -> 9
- "Como uso NotebookLM para estudiar protocolos medicos" -> 8
- "Claude vs ChatGPT para redactar informes" -> 7
- "Hilo Reddit: NotebookLM me ha cambiado el trabajo" -> 7
- "Build an AI agent with Python" -> 2
- "OpenAI recauda 110B" -> 3

---

FORMATOS:
- SHORT: Un truco, comparativa visual, dato sorprendente, experiencia real resumida (<=60s)
- LARGO: Tutorial paso a paso, workflow completo, analisis con demo (8-15min)

---

Responde UNICAMENTE con este JSON sin texto antes ni despues:
{{
  "vale": "SI" o "NO",
  "formato": "short" o "largo" o "ninguno",
  "puntuacion": numero entero del 1 al 10,
  "gancho": "titulo en espanol de Espana, max 65 chars, sin emojis de cohete",
  "angulo": "2-3 frases sobre que contenido seria, a quien beneficia y por que encaja"
}}

REGLA FINAL: si dudas y puntuacion >=5, pon SI."""


# ---------------------------------------------------------------------------
# Auth Google Sheets (OAuth)
# ---------------------------------------------------------------------------

def get_sheets_client():
    creds = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(GOOGLE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return gspread.authorize(creds)


# ---------------------------------------------------------------------------
# Hashing (Opcion A: base64, compatible con n8n)
# ---------------------------------------------------------------------------

def generar_hash(titulo: str, url: str) -> str:
    hash_base = (titulo.lower()[:80] + "_" + url.lower()).strip()
    encoded = base64.b64encode(hash_base.encode()).decode()[:20]
    return encoded.replace("+", "x").replace("/", "x").replace("=", "x")


# ---------------------------------------------------------------------------
# Normalizacion
# ---------------------------------------------------------------------------

def extract_keywords(*texts: str, limit: int = 8) -> str:
    combined = " ".join(t for t in texts if t).lower()
    tokens = re.findall(r"[a-záéíóúñü0-9]{3,}", combined)
    filtered = [t for t in tokens if t not in STOPWORDS and not t.isdigit()]
    if not filtered:
        return ""
    counter = Counter(filtered)
    seen: list[str] = []
    for word, _ in counter.most_common():
        if word not in seen:
            seen.append(word)
        if len(seen) >= limit:
            break
    return ", ".join(seen)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def build_item(titulo: str, url: str, fuente: str, autor: str, preview: str) -> dict:
    titulo = (titulo or "").strip()
    url = (url or "").strip()
    preview_clean = (preview or "").strip()[:1800]
    return {
        "content_hash": generar_hash(titulo, url),
        "fecha_detectado": now_str(),
        "fuente": fuente,
        "titulo": titulo,
        "url": url,
        "autor": (autor or "").strip(),
        "preview": preview_clean,
        "keywords": extract_keywords(titulo, preview_clean),
        "notificado": "NO",
    }


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def fetch_reddit_sources() -> list[dict]:
    items: list[dict] = []
    headers = {"User-Agent": USER_AGENT}
    for sub in REDDIT_SOURCES:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
        try:
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                print(f"WARN reddit r/{sub}: HTTP {resp.status_code}")
                continue
            data = resp.json()
            posts = data.get("data", {}).get("children", [])
            for post in posts:
                d = post.get("data", {})
                titulo = d.get("title") or ""
                permalink = d.get("permalink") or ""
                full_url = f"https://www.reddit.com{permalink}" if permalink else d.get("url", "")
                selftext = (d.get("selftext") or "").strip()
                score = d.get("score", 0)
                num_comments = d.get("num_comments", 0)
                preview = f"[Votos: {score} | Comentarios: {num_comments}] {selftext}".strip()
                autor = d.get("author") or ""
                items.append(build_item(titulo, full_url, f"r/{sub}", autor, preview))
        except Exception as e:
            print(f"WARN reddit r/{sub}: {e}")
            continue
    return items


def fetch_rss_blogs() -> list[dict]:
    items: list[dict] = []
    for blog in RSS_BLOGS:
        try:
            feed = feedparser.parse(blog["url"])
            for entry in feed.entries[:25]:
                titulo = entry.get("title", "")
                url = entry.get("link", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                preview = re.sub(r"<[^>]+>", " ", summary)
                preview = re.sub(r"\s+", " ", preview).strip()
                items.append(build_item(titulo, url, blog["fuente"], blog["autor"], preview))
        except Exception as e:
            print(f"WARN rss {blog['fuente']}: {e}")
            continue
    return items


def fetch_youtube_channels() -> list[dict]:
    items: list[dict] = []
    for ch in YOUTUBE_CHANNELS:
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
        try:
            feed = feedparser.parse(rss_url)
            channel_author = feed.feed.get("title", ch["fuente"])
            for entry in feed.entries[:15]:
                titulo = entry.get("title", "")
                url = entry.get("link", "")
                summary = entry.get("summary", "") or ""
                preview = re.sub(r"<[^>]+>", " ", summary)
                preview = re.sub(r"\s+", " ", preview).strip()
                autor = entry.get("author", channel_author)
                items.append(build_item(titulo, url, ch["fuente"], autor, preview))
        except Exception as e:
            print(f"WARN youtube {ch['fuente']}: {e}")
            continue
    return items


# ---------------------------------------------------------------------------
# Dedup (sheet + memoria)
# ---------------------------------------------------------------------------

def leer_hashes_conocidos(gc, spreadsheet_id: str) -> set[str]:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    valores = hoja.col_values(1)
    return {v.strip() for v in valores[1:] if v.strip()}


def escribir_hash(gc, spreadsheet_id: str, content_hash: str) -> None:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    hoja.append_row([content_hash, datetime.now(timezone.utc).isoformat()])


def normalizar_titulo(titulo: str) -> str:
    return re.sub(r"[^a-z0-9áéíóúñü\s]", "", titulo.lower()).strip()[:80]


def es_duplicado(item: dict, hashes_conocidos: set[str], hashes_batch: set[str], titulos_vistos: set[str]) -> bool:
    h = item["content_hash"]
    titulo_norm = normalizar_titulo(item["titulo"])

    if not h or not titulo_norm:
        return True
    if h in hashes_conocidos:
        return True
    if h in hashes_batch:
        return True
    if titulo_norm in titulos_vistos:
        return True

    hashes_batch.add(h)
    titulos_vistos.add(titulo_norm)
    return False


# ---------------------------------------------------------------------------
# Analisis Claude
# ---------------------------------------------------------------------------

_anthropic_client: Anthropic | None = None


def _client() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def parsear_respuesta_claude(texto: str) -> dict:
    defaults = {"vale": "NO", "formato": "ninguno", "puntuacion": 0, "gancho": "", "angulo": "Sin analisis"}
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
            "angulo": str(p.get("angulo", "")).strip() or "Sin descripcion",
        }
    except Exception as e:
        defaults["angulo"] = f"Error: {str(e)[:100]}"
        return defaults


def analizar_con_claude(item: dict) -> dict:
    prompt = CLAUDE_PROMPT_TEMPLATE.format(
        fuente=item["fuente"],
        titulo=item["titulo"],
        autor=item["autor"] or "(desconocido)",
        url=item["url"],
        preview=item["preview"][:1200] or "(sin preview)",
        keywords=item.get("keywords", "") or "(sin keywords)",
    )
    try:
        resp = _client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = resp.content[0].text if resp.content else ""
        return parsear_respuesta_claude(texto)
    except Exception as e:
        return {
            "vale": "NO",
            "formato": "ninguno",
            "puntuacion": 0,
            "gancho": "",
            "angulo": f"Error API: {str(e)[:120]}",
        }


# ---------------------------------------------------------------------------
# Guardado en Sheets
# ---------------------------------------------------------------------------

def guardar_en_sheets(gc, spreadsheet_id: str, item: dict, analisis: dict) -> None:
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


def formatear_mensaje_telegram(noticias_si: list[dict]) -> str:
    ahora = datetime.now().strftime("%d/%m %H:%M")
    total = len(noticias_si)

    largos = sorted([n for n in noticias_si if n["formato"] == "largo"], key=lambda x: -float(x["puntuacion"]))
    shorts = sorted([n for n in noticias_si if n["formato"] == "short"], key=lambda x: -float(x["puntuacion"]))
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

        angulo = p.get("angulo", "")
        if len(angulo) > 160:
            recortado = angulo[:160]
            ultimo = max(recortado.rfind(". "), recortado.rfind(", "), recortado.rfind(" — "))
            angulo = (recortado[: ultimo + 1] + "…") if ultimo > 80 else (recortado + "…")

        lines.append(f"{i+1}. {fl} {estrellas} {icono} <b>{punt:.0f}/10</b> <i>{fecha}</i>")
        lines.append(f'<a href="{p["url"]}">{p["titulo"][:60]}</a>')
        lines.append(f'💡 {p.get("gancho") or "Sin gancho"}')
        if angulo:
            lines.append(f"📐 <i>{angulo}</i>")
        lines.append("")

    lines.append("─────────────────")
    lines.append('💬 Di "guion del 1" o "mas info del 2" a Marius para continuar.')

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

    faltan = [k for k, v in {
        "ANTHROPIC_API_KEY": ANTHROPIC_API_KEY,
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
        "GOOGLE_SHEETS_ID": SHEETS_ID,
    }.items() if not v]
    if faltan:
        print(f"❌ Faltan variables de entorno: {', '.join(faltan)}")
        sys.exit(1)

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
    nuevos = [item for item in items_raw if not es_duplicado(item, hashes_conocidos, hashes_batch, titulos_vistos)]
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
            print(f'{marca} {analisis["puntuacion"]:.0f}/10 [{item["fuente"]}] {item["titulo"][:60]}')
            time.sleep(0.5)
        except Exception as e:
            print(f'⚠️ Error procesando {item["titulo"][:40]}: {e}')
            continue

    if noticias_si:
        mensaje = formatear_mensaje_telegram(noticias_si)
        try:
            enviar_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, mensaje)
            print(f"📱 Telegram enviado: {len(noticias_si)} propuestas")
        except Exception as e:
            print(f"⚠️ Fallo Telegram: {e}")
    else:
        print("ℹ️ Sin propuestas SI este ciclo, no se envia TG")


if __name__ == "__main__":
    ejecutar_pipeline()
