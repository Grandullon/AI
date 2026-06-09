#!/usr/bin/env python3
"""IA Scout — pipeline de inteligencia de contenidos para Diario Vida IA."""

import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html import unescape

import feedparser
import gspread
import requests
from anthropic import Anthropic
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()

SHEETS_ID = os.getenv('GOOGLE_SHEETS_ID')
TG_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TG_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
CLAUDE_MODEL = 'claude-haiku-4-5-20251001'
REDDIT_UA = 'Mozilla/5.0 (compatible; n8n-rss-bot/2.0)'

REDDIT_SOURCES = [
    'notebooklm',
    'PromptEngineering',
    'ArtificialInteligence',
    'ChatGPT',
    'ClaudeAI',
    'productivity',
]

RSS_BLOGS = [
    {'url': 'https://www.oneusefulthing.org/feed', 'fuente': 'OneUsefulThing', 'autor': 'Ethan Mollick'},
    {'url': 'https://simonwillison.net/atom/everything/', 'fuente': 'SimonWillison', 'autor': 'Simon Willison'},
]

YOUTUBE_CHANNELS = [
    {'channel_id': 'UCj2zirDn1hkPKSARbARfeQw', 'fuente': 'YT:PaulJames'},
    {'channel_id': 'UCYdEAbC7JrC8fBt8OoDwoJQ', 'fuente': 'YT:JoaquinBarbera'},
    {'channel_id': 'UCmeU2DYiVy80wMBGZzEWnbw', 'fuente': 'YT:PaulLipsky'},
    {'channel_id': 'UChez6IIo3Z1g3HUezkr7jIA', 'fuente': 'YT:AnjanaGowtham'},
    {'channel_id': 'UCwT758Tjg0LPHSNmH0QqkhQ', 'fuente': 'YT:AndyLok'},
    {'channel_id': 'UC3KK7ENB_ierAXvrxVNnbZQ', 'fuente': 'YT:BenAI92'},
    {'channel_id': 'UCxcDzs-4quJV4QsairlFYNg', 'fuente': 'YT:AlejaviRivera'},
    {'channel_id': 'UCrB7UFnkosBjAhOg3a9NdWw', 'fuente': 'YT:GraceLeung'},
]

STOPWORDS = set("""the a an and or but in on at to for of with by is are was were be been
have has do does will would could should can this that these those i you he she it we they
my your its our their what which who how when where why not no so than very just also now""".split())


# ---------- Autenticación Google Sheets ----------

def get_sheets_client():
    creds = None
    token_file = os.getenv('GOOGLE_TOKEN_FILE', 'token.json')
    creds_file = os.getenv('GOOGLE_CREDENTIALS_FILE', 'credentials.json')

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, 'w') as f:
            f.write(creds.to_json())

    return gspread.authorize(creds)


# ---------- Helpers ----------

def now_iso() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def limpiar_html(texto: str) -> str:
    if not texto:
        return ''
    texto = re.sub(r'<[^>]+>', ' ', texto)
    texto = unescape(texto)
    return re.sub(r'\s+', ' ', texto).strip()


def extraer_keywords(titulo: str, preview: str = '') -> str:
    texto = f'{titulo} {preview}'.lower()
    palabras = re.findall(r'[a-záéíóúñü0-9]{4,}', texto)
    seleccionadas = []
    for p in palabras:
        if p in STOPWORDS:
            continue
        if p in seleccionadas:
            continue
        seleccionadas.append(p)
        if len(seleccionadas) >= 8:
            break
    return ','.join(seleccionadas)


def generar_hash(titulo: str, url: str) -> str:
    # Opción A (compat con hashes n8n ya almacenados en hoja "Hashes").
    hash_base = (titulo.lower()[:80] + '_' + url.lower()).strip()
    encoded = base64.b64encode(hash_base.encode('utf-8')).decode('ascii')[:20]
    return encoded.replace('+', 'x').replace('/', 'x').replace('=', 'x')


def normalizar_titulo(titulo: str) -> str:
    return re.sub(r'[^a-z0-9áéíóúñü\s]', '', titulo.lower()).strip()[:80]


# ---------- Fetchers ----------

def fetch_reddit_sources() -> list:
    items = []
    for sub in REDDIT_SOURCES:
        url = f'https://www.reddit.com/r/{sub}/new.json?limit=25'
        try:
            r = requests.get(url, headers={'User-Agent': REDDIT_UA}, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f'⚠️ Reddit r/{sub} fallo: {e}')
            continue

        for child in data.get('data', {}).get('children', []):
            post = child.get('data', {})
            titulo = (post.get('title') or '').strip()
            permalink = post.get('permalink', '')
            full_url = f'https://www.reddit.com{permalink}' if permalink else (post.get('url') or '')
            if not titulo or not full_url:
                continue

            selftext = (post.get('selftext') or '')[:1500]
            preview = (
                f"r/{sub} | ⬆{post.get('ups', 0)} | 💬{post.get('num_comments', 0)}\n"
                f"{selftext}"
            )[:1800]

            items.append({
                'content_hash': generar_hash(titulo, full_url),
                'fecha_detectado': now_iso(),
                'fuente': f'r/{sub}',
                'titulo': titulo,
                'url': full_url,
                'autor': post.get('author', 'unknown'),
                'preview': preview,
                'keywords': extraer_keywords(titulo, selftext),
                'notificado': 'NO',
            })
    return items


def fetch_rss_blogs() -> list:
    items = []
    for blog in RSS_BLOGS:
        try:
            feed = feedparser.parse(blog['url'])
        except Exception as e:
            print(f'⚠️ RSS {blog["fuente"]} fallo: {e}')
            continue
        for entry in feed.entries[:15]:
            titulo = (entry.get('title') or '').strip()
            url = entry.get('link') or ''
            if not titulo or not url:
                continue
            preview = limpiar_html(entry.get('summary') or entry.get('description') or '')[:1800]
            items.append({
                'content_hash': generar_hash(titulo, url),
                'fecha_detectado': now_iso(),
                'fuente': blog['fuente'],
                'titulo': titulo,
                'url': url,
                'autor': blog['autor'],
                'preview': preview,
                'keywords': extraer_keywords(titulo, preview),
                'notificado': 'NO',
            })
    return items


def fetch_youtube_channels() -> list:
    items = []
    for ch in YOUTUBE_CHANNELS:
        url = f'https://www.youtube.com/feeds/videos.xml?channel_id={ch["channel_id"]}'
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f'⚠️ YT {ch["fuente"]} fallo: {e}')
            continue
        for entry in feed.entries[:10]:
            titulo = (entry.get('title') or '').strip()
            link = entry.get('link') or ''
            if not titulo or not link:
                continue
            preview = limpiar_html(
                entry.get('summary') or entry.get('media_description') or ''
            )[:1800]
            items.append({
                'content_hash': generar_hash(titulo, link),
                'fecha_detectado': now_iso(),
                'fuente': ch['fuente'],
                'titulo': titulo,
                'url': link,
                'autor': entry.get('author', ch['fuente'].replace('YT:', '')),
                'preview': preview,
                'keywords': extraer_keywords(titulo, preview),
                'notificado': 'NO',
            })
    return items


# ---------- Deduplicación ----------

def leer_hashes_conocidos(gc, spreadsheet_id: str) -> set:
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet('Hashes')
    valores = hoja.col_values(1)
    return set(v.strip() for v in valores[1:] if v.strip())


def escribir_hash(gc, spreadsheet_id: str, content_hash: str):
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet('Hashes')
    hoja.append_row([content_hash, datetime.now(timezone.utc).isoformat()])


def es_duplicado(item, hashes_conocidos, hashes_batch, titulos_vistos) -> bool:
    h = item['content_hash']
    t = normalizar_titulo(item['titulo'])
    if h in hashes_conocidos:
        return True
    if h in hashes_batch:
        return True
    if t and t in titulos_vistos:
        return True
    hashes_batch.add(h)
    if t:
        titulos_vistos.add(t)
    return False


# ---------- Análisis Claude ----------

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


_anthropic_client = None


def get_anthropic_client() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _anthropic_client


def parsear_respuesta_claude(texto: str) -> dict:
    defaults = {
        'vale': 'NO',
        'formato': 'ninguno',
        'puntuacion': 0,
        'gancho': '',
        'angulo': 'Sin análisis',
    }
    try:
        clean = texto.replace('```json', '').replace('```', '').strip()
        match = re.search(r'\{[\s\S]*\}', clean)
        if not match:
            return defaults
        p = json.loads(match.group(0))
        vr = str(p.get('vale', '')).upper().strip()
        fr = str(p.get('formato', '')).lower().strip()
        return {
            'vale': 'SI' if vr in ('SI', 'YES', 'TRUE') else 'NO',
            'formato': fr if fr in ('short', 'largo') else 'ninguno',
            'puntuacion': min(10, max(0, float(p.get('puntuacion', 0)))),
            'gancho': str(p.get('gancho', '')).strip(),
            'angulo': str(p.get('angulo', '')).strip() or 'Sin descripción',
        }
    except Exception as e:
        defaults['angulo'] = f'Error: {str(e)[:100]}'
        return defaults


def analizar_con_claude(item: dict) -> dict:
    client = get_anthropic_client()
    prompt = PROMPT_TEMPLATE.format(
        fuente=item.get('fuente', ''),
        titulo=item.get('titulo', ''),
        autor=item.get('autor', ''),
        url=item.get('url', ''),
        preview=(item.get('preview') or '')[:1800],
        keywords=item.get('keywords', ''),
    )
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=800,
        messages=[{'role': 'user', 'content': prompt}],
    )
    texto = ''.join(b.text for b in resp.content if getattr(b, 'type', '') == 'text')
    time.sleep(0.5)
    return parsear_respuesta_claude(texto)


# ---------- Persistencia Sheets ----------

def guardar_en_sheets(gc, spreadsheet_id: str, item: dict, analisis: dict):
    sh = gc.open_by_key(spreadsheet_id)
    hoja = sh.worksheet('ScoutIA')
    fila = [
        item['content_hash'],
        item['fecha_detectado'],
        item['fuente'],
        item['titulo'],
        item['url'],
        item['autor'],
        (item.get('preview') or '')[:500],
        item.get('keywords', ''),
        'NO',
        analisis['vale'],
        analisis['formato'],
        analisis['puntuacion'],
        analisis.get('gancho', ''),
        analisis.get('angulo', ''),
        'pendiente',
    ]
    hoja.append_row(fila, value_input_option='USER_ENTERED')


# ---------- Telegram ----------

FUENTE_ICONS = {
    'r/notebooklm': '🔴',
    'r/PromptEngineering': '🔴',
    'r/ArtificialInteligence': '🔴',
    'r/ChatGPT': '🔴',
    'r/ClaudeAI': '🔴',
    'r/productivity': '🔴',
    'OneUsefulThing': '🔬',
    'SimonWillison': '🔬',
}


def formatear_mensaje_telegram(noticias_si: list) -> str:
    ahora = datetime.now().strftime('%d/%m %H:%M')
    total = len(noticias_si)

    largos = sorted([n for n in noticias_si if n['formato'] == 'largo'], key=lambda x: -float(x['puntuacion']))
    shorts = sorted([n for n in noticias_si if n['formato'] == 'short'], key=lambda x: -float(x['puntuacion']))
    resto = [n for n in noticias_si if n['formato'] not in ('largo', 'short')]
    final = largos + shorts + resto

    lines = [f'📊 <b>SCOUT — {total} propuesta{"s" if total != 1 else ""} nuevas</b> ({ahora})\n']

    en_shorts = False
    for i, p in enumerate(final):
        fl = '🎬 LARGO' if p['formato'] == 'largo' else '⚡ SHORT' if p['formato'] == 'short' else '📄'
        punt = float(p.get('puntuacion', 0))
        estrellas = '⭐' * min(round(punt / 2), 5)
        icono = FUENTE_ICONS.get(p['fuente']) or ('📺' if p['fuente'].startswith('YT:') else '🌐')

        if p['formato'] == 'short' and not en_shorts and largos:
            lines.append('· · · · · · · · ·')
            en_shorts = True

        fecha = (p.get('fecha_detectado') or '')[:16].replace('T', ' ')[5:]

        angulo = p.get('angulo', '')
        if len(angulo) > 160:
            recortado = angulo[:160]
            ultimo = max(recortado.rfind('. '), recortado.rfind(', '), recortado.rfind(' — '))
            angulo = (recortado[:ultimo + 1] + '…') if ultimo > 80 else (recortado + '…')

        lines.append(f'{i+1}. {fl} {estrellas} {icono} <b>{punt:.0f}/10</b> <i>{fecha}</i>')
        lines.append(f'<a href="{p["url"]}">{p["titulo"][:60]}</a>')
        lines.append(f'💡 {p.get("gancho") or "Sin gancho"}')
        if angulo:
            lines.append(f'📐 <i>{angulo}</i>')
        lines.append('')

    lines.append('─────────────────')
    lines.append('💬 Di "guion del 1" o "más info del 2" a Marius para continuar.')

    return '\n'.join(lines)


def enviar_telegram(token: str, chat_id: str, mensaje: str):
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': mensaje,
        'parse_mode': 'HTML',
        'disable_web_page_preview': False,
    }
    resp = requests.post(url, json=payload, timeout=15)
    resp.raise_for_status()


# ---------- Pipeline ----------

def ejecutar_pipeline():
    print('🚀 IA Scout iniciando...')

    faltan = [name for name, val in [
        ('ANTHROPIC_API_KEY', ANTHROPIC_API_KEY),
        ('TELEGRAM_BOT_TOKEN', TG_TOKEN),
        ('TELEGRAM_CHAT_ID', TG_CHAT_ID),
        ('GOOGLE_SHEETS_ID', SHEETS_ID),
    ] if not val]
    if faltan:
        print(f'❌ Faltan variables de entorno: {", ".join(faltan)}')
        sys.exit(1)

    gc = get_sheets_client()
    hashes_conocidos = leer_hashes_conocidos(gc, SHEETS_ID)
    print(f'📋 Hashes conocidos: {len(hashes_conocidos)}')

    items_raw = []
    items_raw += fetch_reddit_sources()
    items_raw += fetch_rss_blogs()
    items_raw += fetch_youtube_channels()
    print(f'📥 Items crudos: {len(items_raw)}')

    hashes_batch = set()
    titulos_vistos = set()
    nuevos = []
    for item in items_raw:
        if not es_duplicado(item, hashes_conocidos, hashes_batch, titulos_vistos):
            nuevos.append(item)
    print(f'✅ Items nuevos: {len(nuevos)} de {len(items_raw)}')

    if not nuevos:
        print('ℹ️ Sin novedades este ciclo')
        return

    noticias_si = []
    for item in nuevos:
        try:
            analisis = analizar_con_claude(item)
            escribir_hash(gc, SHEETS_ID, item['content_hash'])
            guardar_en_sheets(gc, SHEETS_ID, item, analisis)
            if analisis['vale'] == 'SI':
                noticias_si.append({**item, **analisis})
            marker = '✅' if analisis['vale'] == 'SI' else '❌'
            print(f'{marker} {analisis["puntuacion"]}/10 — {item["titulo"][:50]}')
        except Exception as e:
            print(f'⚠️ Error procesando {item["titulo"][:40]}: {e}')
            continue

    if noticias_si:
        mensaje = formatear_mensaje_telegram(noticias_si)
        enviar_telegram(TG_TOKEN, TG_CHAT_ID, mensaje)
        print(f'📱 Telegram enviado: {len(noticias_si)} propuestas')
    else:
        print('ℹ️ Sin propuestas SI este ciclo, no se envía TG')


if __name__ == '__main__':
    ejecutar_pipeline()
