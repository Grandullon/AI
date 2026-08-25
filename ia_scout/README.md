# IA Scout — Diario Vida IA

Pipeline de inteligencia de contenidos para el canal **Diario Vida IA** ([@PacoVidaIA](https://youtube.com/@PacoVidaIA)).

Cada ejecución:

1. Descarga posts nuevos de Reddit, RSS y YouTube.
2. Deduplica contra la hoja `Hashes` de Google Sheets.
3. Puntúa cada item con Claude (`claude-haiku-4-5-20251001`) según el prompt editorial del canal.
4. Guarda todo en la hoja `ScoutIA`.
5. Envía un resumen Telegram con las propuestas que valen (`vale=SI`).

## Instalación

```bash
cd ia_scout
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Credenciales

1. Copia `.env.example` a `.env` y rellena:
   - `ANTHROPIC_API_KEY` — tu clave de Anthropic.
   - `TELEGRAM_BOT_TOKEN` — token del bot de Telegram.
   - `TELEGRAM_CHAT_ID` — chat destino (por defecto tu ID personal).
   - `GOOGLE_SHEETS_ID` — ID de la hoja destino (ya rellenado).
2. Descarga `credentials.json` desde Google Cloud Console (OAuth 2.0 Client → Desktop app) y colócalo en esta carpeta.
3. En la primera ejecución se abrirá el navegador para autorizar el acceso a Sheets. Se generará `token.json` para las siguientes ejecuciones (sin interacción).

## Google Sheets

La hoja necesita dos pestañas:

- **`Hashes`** — 2 columnas: `content_hash | timestamp`.
- **`ScoutIA`** — 15 columnas: `content_hash | fecha_detectado | fuente | titulo | url | autor | preview | keywords | notificado | vale | formato | puntuacion | gancho | angulo | estado`.

## Ejecución

```bash
python ia_scout.py
```

## Scheduling (cron)

Cada 6 horas:

```
0 */6 * * * cd /ruta/ia_scout && /ruta/ia_scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Estructura

```
ia_scout/
├── ia_scout.py          # Script principal
├── requirements.txt
├── .env.example         # Plantilla — copiar a .env y rellenar
├── .env                 # (ignorado por git) — tus credenciales
├── credentials.json     # (ignorado por git) — OAuth client secrets
├── token.json           # (ignorado por git) — generado en 1ª ejecución
├── .gitignore
└── logs/
    └── scout.log
```

## Notas

- Compatible con los hashes ya almacenados en la hoja `Hashes` (base64 + 20 chars).
- Rate limit Claude: 0.5s entre llamadas.
- Si un subreddit falla (429, timeout), continúa con el siguiente sin abortar el ciclo.
