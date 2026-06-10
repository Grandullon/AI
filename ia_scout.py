#!/usr/bin/env python3
"""IA Scout — pipeline de inteligencia de contenidos para "Diario Vida IA"."""

import base64
import json
import os
import re
import time
from datetime import datetime, timezone
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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "714952561")
SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "1faHu7YYpBD3yg4ZCdOS3KNcJPnsuaRuuDVFqodrXDX8")
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
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


# ---------- AUTH ----------

def get_sheets_client():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return gspread.authorize(creds)


# ---------- HASHING / DEDUP ----------

def generar_hash(titulo: str, url: str) -> str:
    base = (titulo.lower()[:80] + "_" + url.lower()).strip()
    encoded = base64.b64encode(base.encode()).decode()[:20]
    return encoded.replace("+", "x").replace("/", "x").replace("=", "x")


def extraer_keywords(texto: str, maximo: int = 8) -> str:
    palabras = re.findall(r"[a-záéíóúñü0-9]{3,}", texto.lower())
    vistas = []
    for p in palabras:
        if p in STOPWORDS or p in vistas:
            continue
        vistas.append(p)
        if len(vistas) >= maximo:
            break
    return ", ".join(vistas)


def normalizar_titulo(titulo: str) -> str:
    return re.sub(r"[^a-z0-9áéíóúñü\s]", "", titulo.lower()).strip()[:80]


# ---------- FETCHERS ----------

def fetch_reddit_sources() -> list:
    items = []
    headers = {"User-Agent": USER_AGENT}
    for sub in REDDIT_SOURCES:
        try:
            url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
            r = requests.get(url, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
            for child in data.get("data", {}).get("children", []):
                d = child.get("data", {})
                titulo = d.get("title", "").strip()
                permalink = d.get("permalink", "")
                if not titulo or not permalink:
                    continue
                url_post = f"https://www.reddit.com{permalink}"
                autor = d.get("author", "anon")
                ups = d.get("ups", 0)
                num_comments = d.get("num_comments", 0)
                selftext = (d.get("selftext", "") or "")[:1500]
                preview = f"[{ups}↑ {num_comments}💬] {selftext}".strip()[:1800]
                items.append({
                    "content_hash": generar_hash(titulo, url_post),
                    "fecha_detectado": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "fuente": f"r/{sub}",
                    "titulo": titulo,
                    "url": url_post,
                    "autor": autor,
                    "preview": preview,
                    "keywords": extraer_keywords(titulo + " " + selftext),
                    "notificado": "NO",
                })
        except Exception as e:
            print(f"⚠️ Reddit r/{sub} error: {e}")
            continue
    return items


def fetch_rss_blogs() -> list:
    items = []
    for blog in RSS_BLOGS:
        try:
            feed = feedparser.parse(blog["url"])
            for entry in feed.entries[:15]:
                titulo = (entry.get("title") or "").strip()
                url = entry.get("link") or ""
                if not titulo or not url:
                    continue
                resumen = (entry.get("summary") or entry.get("description") or "")[:1800]
                resumen = re.sub(r"<[^>]+>", "", resumen)
                items.append({
                    "content_hash": generar_hash(titulo, url),
                    "fecha_detectado": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "fuente": blog["fuente"],
                    "titulo": titulo,
                    "url": url,
                    "autor": blog["autor"],
                    "preview": resumen.strip(),
                    "keywords": extraer_keywords(titulo + " " + resumen),
                    "notificado": "NO",
                })
        except Exception as e:
            print(f"⚠️ RSS {blog['fuente']} error: {e}")
            continue
    return items


def fetch_youtube_channels() -> list:
    items = []
    for ch in YOUTUBE_CHANNELS:
        try:
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            ns = {"atom": "http://www.w3.org/2005/Atom", "media": "http://search.yahoo.com/mrss/"}
            for entry in root.findall("atom:entry", ns)[:10]:
                titulo = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
                link_el = entry.find("atom:link", ns)
                video_url = link_el.get("href") if link_el is not None else ""
                autor = entry.findtext("atom:author/atom:name", default="", namespaces=ns) or ch["fuente"]
                desc_el = entry.find("media:group/media:description", ns)
                desc = (desc_el.text if desc_el is not None and desc_el.text else "")[:1800]
                if not titulo or not video_url:
                    continue
                items.append({
                    "content_hash": generar_hash(titulo, video_url),
                    "fecha_detectado": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "fuente": ch["fuente"],
                    "titulo": titulo,
                    "url": video_url,
                    "autor": autor,
                    "preview": desc.strip(),
                    "keywords": extraer_keywords(titulo + " " + desc),
                    "notificado": "NO",
                })
        except Exception as e:
            print(f"⚠️ YouTube {ch['fuente']} error: {e}")
            continue
    return items


# ---------- DEDUP ----------

def leer_hashes_conocidos(gc, spreadsheet_id: str) -> set:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    valores = hoja.col_values(1)
    return set(v.strip() for v in valores[1:] if v.strip())


def escribir_hash(gc, spreadsheet_id: str, content_hash: str):
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet("Hashes")
    hoja.append_row([content_hash, datetime.now(timezone.utc).isoformat()])


def es_duplicado(item: dict, hashes_conocidos: set, hashes_batch: set, titulos_vistos: set) -> bool:
    h = item["content_hash"]
    titulo_norm = normalizar_titulo(item["titulo"])
    if h in hashes_conocidos or h in hashes_batch or titulo_norm in titulos_vistos:
        return True
    hashes_batch.add(h)
    titulos_vistos.add(titulo_norm)
    return False


# ---------- CLAUDE ----------

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
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
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
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    texto = resp.content[0].text if resp.content else ""
    time.sleep(0.5)
    return parsear_respuesta_claude(texto)


# ---------- SHEETS WRITE ----------

def guardar_en_sheets(gc, spreadsheet_id: str, item: dict, analisis: dict):
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


# ---------- TELEGRAM ----------

def formatear_mensaje_telegram(noticias_si: list) -> str:
    ahora = datetime.now().strftime("%d/%m %H:%M")
    total = len(noticias_si)

    largos = sorted([n for n in noticias_si if n["formato"] == "largo"], key=lambda x: -x["puntuacion"])
    shorts = sorted([n for n in noticias_si if n["formato"] == "short"], key=lambda x: -x["puntuacion"])
    resto = [n for n in noticias_si if n["formato"] not in ("largo", "short")]
    final = largos + shorts + resto

    fuente_icons = {
        "r/notebooklm": "🔴", "r/PromptEngineering": "🔴",
        "r/ArtificialInteligence": "🔴", "r/ChatGPT": "🔴",
        "r/ClaudeAI": "🔴", "r/productivity": "🔴",
        "OneUsefulThing": "🔬", "SimonWillison": "🔬",
    }

    lines = [f'📊 <b>SCOUT — {total} propuesta{"s" if total != 1 else ""} nuevas</b> ({ahora})\n']

    en_shorts = False
    for i, p in enumerate(final):
        fl = "🎬 LARGO" if p["formato"] == "largo" else "⚡ SHORT" if p["formato"] == "short" else "📄"
        punt = float(p.get("puntuacion", 0))
        estrellas = "⭐" * min(round(punt / 2), 5)
        icono = fuente_icons.get(p["fuente"]) or ("📺" if p["fuente"].startswith("YT:") else "🌐")

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
            lines.append(f'📐 <i>{angulo}</i>')
        lines.append("")

    lines.append("─────────────────")
    lines.append('💬 Di "guion del 1" o "más info del 2" a Marius para continuar.')

    return "\n".join(lines)


def enviar_telegram(token: str, chat_id: str, mensaje: str):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": mensaje, "parse_mode": "HTML"}
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()


# ---------- MAIN ----------

def ejecutar_pipeline():
    print("🚀 IA Scout iniciando...")

    missing = [name for name, val in [
        ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
        ("TELEGRAM_BOT_TOKEN", TG_TOKEN),
    ] if not val]
    if missing:
        raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")
    if not os.path.exists(CREDENTIALS_FILE) and not os.path.exists(TOKEN_FILE):
        raise RuntimeError(f"Falta {CREDENTIALS_FILE} o {TOKEN_FILE} para Google Sheets")

    gc = get_sheets_client()
    hashes_conocidos = leer_hashes_conocidos(gc, SHEETS_ID)
    print(f"📋 Hashes conocidos: {len(hashes_conocidos)}")

    items_raw = []
    items_raw += fetch_reddit_sources()
    items_raw += fetch_rss_blogs()
    items_raw += fetch_youtube_channels()
    print(f"📥 Items crudos: {len(items_raw)}")

    hashes_batch = set()
    titulos_vistos = set()
    nuevos = [it for it in items_raw if not es_duplicado(it, hashes_conocidos, hashes_batch, titulos_vistos)]
    print(f"✅ Items nuevos: {len(nuevos)} de {len(items_raw)}")

    if not nuevos:
        print("ℹ️ Sin novedades este ciclo")
        return

    noticias_si = []
    for item in nuevos:
        try:
            analisis = analizar_con_claude(item)
            escribir_hash(gc, SHEETS_ID, item["content_hash"])
            guardar_en_sheets(gc, SHEETS_ID, item, analisis)
            if analisis["vale"] == "SI":
                noticias_si.append({**item, **analisis})
            tick = "✅" if analisis["vale"] == "SI" else "❌"
            print(f'{tick} {analisis["puntuacion"]}/10 — {item["titulo"][:50]}')
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
