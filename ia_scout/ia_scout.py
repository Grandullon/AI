#!/usr/bin/env python3
"""IA Scout pipeline for Diario Vida IA.

Monitoriza RSS y Reddit, deduplica, analiza con Claude,
guarda en Google Sheets y envia resumen por Telegram.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import feedparser
import requests
from dotenv import load_dotenv

from anthropic import Anthropic

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "714952561")
SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "1faHu7YYpBD3yg4ZCdOS3KNcJPnsuaRuuDVFqodrXDX8")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
GOOGLE_TOKEN_FILE = os.getenv("GOOGLE_TOKEN_FILE", "token.json")

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
CLAUDE_MAX_TOKENS = 800
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
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "is", "are", "was", "were", "be", "been", "have", "has", "do", "does",
    "will", "would", "could", "should", "can", "this", "that", "these", "those",
    "i", "you", "he", "she", "it", "we", "they", "my", "your", "its", "our", "their",
    "what", "which", "who", "how", "when", "where", "why", "not", "no", "so",
    "than", "very", "just", "also", "now",
}


def log(msg: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def generar_hash(titulo: str, url: str) -> str:
    """Base64 truncated hash — compatible con la hoja Hashes existente."""
    hash_base = (titulo.lower()[:80] + "_" + url.lower()).strip()
    encoded = base64.b64encode(hash_base.encode("utf-8", errors="ignore")).decode()[:20]
    return encoded.replace("+", "x").replace("/", "x").replace("=", "x")


def extraer_keywords(texto: str, max_kw: int = 8) -> str:
    if not texto:
        return ""
    limpio = re.sub(r"[^a-zA-Z0-9áéíóúñüÁÉÍÓÚÑÜ\s]", " ", texto).lower()
    palabras = [w for w in limpio.split() if len(w) > 3 and w not in STOPWORDS]
    vistas: list[str] = []
    for w in palabras:
        if w not in vistas:
            vistas.append(w)
        if len(vistas) >= max_kw:
            break
    return ", ".join(vistas)


def normalizar_item(
    *,
    fuente: str,
    titulo: str,
    url: str,
    autor: str,
    preview: str,
) -> dict[str, Any]:
    titulo = (titulo or "").strip()
    url = (url or "").strip()
    preview = (preview or "").strip()[:1800]
    return {
        "content_hash": generar_hash(titulo, url),
        "fecha_detectado": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "fuente": fuente,
        "titulo": titulo,
        "url": url,
        "autor": (autor or "").strip(),
        "preview": preview,
        "keywords": extraer_keywords(f"{titulo} {preview}"),
        "notificado": "NO",
    }


def strip_html(texto: str) -> str:
    if not texto:
        return ""
    sin_tags = re.sub(r"<[^>]+>", " ", texto)
    return html.unescape(re.sub(r"\s+", " ", sin_tags)).strip()


def fetch_reddit_sources() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    headers = {"User-Agent": USER_AGENT}
    for sub in REDDIT_SOURCES:
        url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
        try:
            resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            if resp.status_code != 200:
                log(f"reddit r/{sub} -> HTTP {resp.status_code}, skip")
                continue
            data = resp.json()
            for child in data.get("data", {}).get("children", []):
                p = child.get("data", {})
                if p.get("stickied") or p.get("over_18"):
                    continue
                titulo = p.get("title", "")
                permalink = p.get("permalink", "")
                url_post = f"https://www.reddit.com{permalink}" if permalink else p.get("url", "")
                selftext = p.get("selftext", "")
                score = p.get("score", 0)
                num_comments = p.get("num_comments", 0)
                preview = (
                    f"[{score}pts · {num_comments}c] {selftext[:1600]}"
                    if selftext
                    else f"[{score}pts · {num_comments}c]"
                )
                items.append(
                    normalizar_item(
                        fuente=f"r/{sub}",
                        titulo=titulo,
                        url=url_post,
                        autor=p.get("author", ""),
                        preview=preview,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log(f"reddit r/{sub} error: {exc}")
            continue
    return items


def fetch_rss_blogs() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for blog in RSS_BLOGS:
        try:
            feed = feedparser.parse(blog["url"])
            for entry in feed.entries[:20]:
                titulo = entry.get("title", "")
                url = entry.get("link", "")
                preview = strip_html(entry.get("summary", "") or entry.get("description", ""))
                items.append(
                    normalizar_item(
                        fuente=blog["fuente"],
                        titulo=titulo,
                        url=url,
                        autor=blog["autor"],
                        preview=preview,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log(f"rss {blog['fuente']} error: {exc}")
            continue
    return items


def fetch_youtube_channels() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ch in YOUTUBE_CHANNELS:
        try:
            url = f"https://www.youtube.com/feeds/videos.xml?channel_id={ch['channel_id']}"
            feed = feedparser.parse(url)
            autor = feed.feed.get("title", ch["fuente"])
            for entry in feed.entries[:15]:
                titulo = entry.get("title", "")
                video_url = entry.get("link", "")
                preview = strip_html(entry.get("summary", ""))
                items.append(
                    normalizar_item(
                        fuente=ch["fuente"],
                        titulo=titulo,
                        url=video_url,
                        autor=autor,
                        preview=preview,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log(f"yt {ch['fuente']} error: {exc}")
            continue
    return items


def get_sheets_client() -> gspread.Client:
    creds: Credentials | None = None
    if os.path.exists(GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Falta {GOOGLE_CREDENTIALS_FILE}. Descarga el OAuth client "
                    "secrets desde Google Cloud Console."
                )
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


def build_prompt(item: dict[str, Any]) -> str:
    return f"""Eres el editor de contenido de "Diario Vida IA", canal YouTube español con 15.200 suscriptores creciendo a +100/día.

CONTEXTO DEL CANAL:
- PILAR PRINCIPAL (60% del contenido): NotebookLM. Cualquier novedad, truco, caso de uso, integración o experiencia real con NotebookLM tiene prioridad máxima automática.
- PILAR 2: IA práctica para trabajadores del conocimiento (ChatGPT, Claude, Gemini, Perplexity). Casos de uso reales, no demos de laboratorio.
- PILAR 3: Automatización y productividad (n8n, flujos de trabajo, ahorrar tiempo real).
- DESCARTAR SIEMPRE: desarrollo de software, programación pura, hardware, gaming, ciencia sin aplicación práctica, noticias corporativas sin impacto en el usuario.

AUDIENCIA: Profesionales 30-50 años, trabajadores del conocimiento (médicos, RRHH, profesores, administrativos, gestores). Usan IA en su trabajo pero NO son programadores. Quieren resultados en menos de 10 minutos. Desconfían del hype. Valoran la honestidad sobre las limitaciones.

ESTILO DEL CANAL: Anti-gurú. Directo. Sin "revolucionario", sin emojis de cohete. El presentador es Paco, trabaja en un hospital (RRHH), 500+ días de constancia personal. Credibilidad por resultados reales, no por promesas.

---

NOTICIA A EVALUAR:
Fuente: {item['fuente']}
Título: {item['titulo']}
Autor: {item['autor']}
URL: {item['url']}
Contenido: {item['preview']}
Keywords: {item['keywords']}

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
    except Exception as exc:  # noqa: BLE001
        defaults["angulo"] = f"Error: {str(exc)[:100]}"
        return defaults


def analizar_con_claude(client: Anthropic, item: dict[str, Any]) -> dict[str, Any]:
    prompt = build_prompt(item)
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    texto = "".join(
        block.text for block in resp.content if getattr(block, "type", None) == "text"
    )
    return parsear_respuesta_claude(texto)


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


def formatear_mensaje_telegram(noticias_si: list[dict[str, Any]]) -> str:
    ahora = datetime.now().strftime("%d/%m %H:%M")
    total = len(noticias_si)

    largos = sorted([n for n in noticias_si if n["formato"] == "largo"], key=lambda x: -x["puntuacion"])
    shorts = sorted([n for n in noticias_si if n["formato"] == "short"], key=lambda x: -x["puntuacion"])
    resto = [n for n in noticias_si if n["formato"] not in ("largo", "short")]
    final = largos + shorts + resto

    fuente_icons = {
        "r/notebooklm": "🔴",
        "r/PromptEngineering": "🔴",
        "r/ArtificialInteligence": "🔴",
        "r/ChatGPT": "🔴",
        "r/ClaudeAI": "🔴",
        "r/productivity": "🔴",
        "OneUsefulThing": "🔬",
        "SimonWillison": "🔬",
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
            angulo = (recortado[: ultimo + 1] + "…") if ultimo > 80 else (recortado + "…")

        titulo_esc = html.escape(p["titulo"][:60])
        gancho_esc = html.escape(p.get("gancho") or "Sin gancho")
        angulo_esc = html.escape(angulo)

        lines.append(f'{i+1}. {fl} {estrellas} {icono} <b>{punt:.0f}/10</b> <i>{fecha}</i>')
        lines.append(f'<a href="{html.escape(p["url"])}">{titulo_esc}</a>')
        lines.append(f'💡 {gancho_esc}')
        if angulo_esc:
            lines.append(f'📐 <i>{angulo_esc}</i>')
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
    resp = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()


def check_credentials() -> list[str]:
    missing = []
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not TG_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not os.path.exists(GOOGLE_CREDENTIALS_FILE) and not os.path.exists(GOOGLE_TOKEN_FILE):
        missing.append(f"{GOOGLE_CREDENTIALS_FILE} o {GOOGLE_TOKEN_FILE}")
    return missing


def ejecutar_pipeline() -> None:
    log("🚀 IA Scout iniciando...")

    missing = check_credentials()
    if missing:
        log(f"❌ Faltan credenciales: {', '.join(missing)}")
        sys.exit(2)

    claude_client = Anthropic(api_key=ANTHROPIC_API_KEY)

    gc = get_sheets_client()
    hashes_conocidos = leer_hashes_conocidos(gc, SHEETS_ID)
    log(f"📋 Hashes conocidos: {len(hashes_conocidos)}")

    items_raw: list[dict[str, Any]] = []
    items_raw += fetch_reddit_sources()
    items_raw += fetch_rss_blogs()
    items_raw += fetch_youtube_channels()
    log(f"📥 Items crudos: {len(items_raw)}")

    hashes_batch: set[str] = set()
    titulos_vistos: set[str] = set()
    nuevos = [
        it
        for it in items_raw
        if not es_duplicado(it, hashes_conocidos, hashes_batch, titulos_vistos)
    ]
    log(f"✅ Items nuevos: {len(nuevos)} de {len(items_raw)}")

    if not nuevos:
        log("ℹ️ Sin novedades este ciclo")
        return

    noticias_si: list[dict[str, Any]] = []
    for item in nuevos:
        try:
            analisis = analizar_con_claude(claude_client, item)
            escribir_hash(gc, SHEETS_ID, item["content_hash"])
            guardar_en_sheets(gc, SHEETS_ID, item, analisis)

            if analisis["vale"] == "SI":
                noticias_si.append({**item, **analisis})

            marca = "✅" if analisis["vale"] == "SI" else "❌"
            log(f'{marca} {analisis["puntuacion"]}/10 — {item["titulo"][:50]}')
        except Exception as exc:  # noqa: BLE001
            log(f'⚠️ Error procesando {item["titulo"][:40]}: {exc}')
            continue
        time.sleep(0.5)

    if noticias_si:
        mensaje = formatear_mensaje_telegram(noticias_si)
        enviar_telegram(TG_TOKEN, TG_CHAT_ID, mensaje)
        log(f"📱 Telegram enviado: {len(noticias_si)} propuestas")
    else:
        log("ℹ️ Sin propuestas SI este ciclo, no se envía TG")


if __name__ == "__main__":
    ejecutar_pipeline()
