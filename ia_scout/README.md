# IA Scout

Pipeline de inteligencia de contenidos para el canal **Diario Vida IA** (Paco, @PacoVidaIA).

Monitoriza Reddit + RSS + YouTube, deduplica, evalúa cada item con Claude Haiku, guarda en Google Sheets y envía un resumen ordenado por Telegram.

## Setup

```bash
cd ia_scout
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # rellena tokens
# coloca credentials.json (OAuth Desktop de Google Cloud Console) en la carpeta
python ia_scout.py         # primera vez abre navegador para autorizar Google
```

Ejecuciones posteriores usan `token.json` sin interacción.

## Cron

```
0 */6 * * * cd /ruta/ia_scout && /ruta/ia_scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Google Sheets

Hoja `1faHu7YYpBD3yg4ZCdOS3KNcJPnsuaRuuDVFqodrXDX8` con dos pestañas:

- **Hashes** — `content_hash | timestamp` (deduplicación permanente).
- **ScoutIA** — 15 columnas por fila (ver `guardar_en_sheets` en `ia_scout.py`).

## Sobre este repositorio

Este repo está pensado como base de código: los secretos (`.env`, `credentials.json`, `token.json`) NO se versionan.
Si quieres correr esto como tarea programada en un entorno efímero (Claude Code on the web, GitHub Actions, etc.),
migra a **service account** de Google en lugar del flujo OAuth de escritorio — el `flow.run_local_server` requiere navegador y no funciona headless.
