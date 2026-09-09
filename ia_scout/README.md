# IA Scout

Pipeline de inteligencia de contenidos para el canal YouTube "Diario Vida IA".

Monitoriza Reddit + RSS + YouTube, deduplica contra Google Sheets, analiza cada
item nuevo con Claude Haiku 4.5, guarda el resultado en la hoja y envía por
Telegram un resumen de las propuestas que "valen".

## Por qué se ejecuta en local, no en Claude Code remoto

La sesión de Claude Code en la web es un contenedor efímero y sin navegador:
no puede completar el `run_local_server` de OAuth de Google, no persiste
`token.json` entre ejecuciones y no lleva las credenciales de Anthropic o
Telegram. Este script está pensado para correr en tu propia máquina (o un
servidor tuyo) vía `cron`.

## Setup (una sola vez)

1. Descarga las credenciales OAuth de Google Cloud Console y guárdalas como
   `credentials.json` en esta carpeta.
2. Copia `.env.example` a `.env` y rellena:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   TELEGRAM_BOT_TOKEN=...
   TELEGRAM_CHAT_ID=714952561
   GOOGLE_SHEETS_ID=1faHu7YYpBD3yg4ZCdOS3KNcJPnsuaRuuDVFqodrXDX8
   ```
3. Instala dependencias:
   ```
   pip install -r requirements.txt
   ```
4. Primera ejecución (abre el navegador para autorizar):
   ```
   python ia_scout.py
   ```
   Aparecerá `token.json`. Las siguientes ejecuciones son silenciosas.

## Cron

```
0 */6 * * * cd /ruta/ia_scout && /usr/bin/python3 ia_scout.py >> logs/scout.log 2>&1
```

## Estructura de la hoja de Sheets

- Pestaña **Hashes**: 2 columnas (`content_hash`, `timestamp_iso`).
- Pestaña **ScoutIA**: 15 columnas
  `content_hash | fecha_detectado | fuente | titulo | url | autor | preview |
  keywords | notificado | vale | formato | puntuacion | gancho | angulo |
  estado`.

Crea ambas pestañas antes de la primera ejecución.

## Fuentes monitorizadas

- **Reddit** (`/new.json?limit=25`): `notebooklm`, `PromptEngineering`,
  `ArtificialInteligence`, `ChatGPT`, `ClaudeAI`, `productivity`.
- **RSS blogs**: One Useful Thing (Ethan Mollick), Simon Willison.
- **YouTube** (feed XML): 8 canales relevantes de IA/productividad.

Modificar en `ia_scout.py` (`REDDIT_SOURCES`, `RSS_BLOGS`, `YOUTUBE_CHANNELS`).

## Hash de deduplicación

Se usa la **Opción A** del spec (base64 truncado a 20 chars, con `+ / =`
sustituidos por `x`) para mantener compatibilidad con los hashes que ya
existen en la hoja "Hashes".
