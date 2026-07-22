# IA Scout — Diario Vida IA

Pipeline de scouting de contenido: monitoriza Reddit, blogs RSS y canales YouTube,
deduplica, evalúa con Claude según el nicho del canal y publica un resumen en
Telegram + Google Sheets.

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # rellenar con tus credenciales
# colocar credentials.json (OAuth desktop client de Google Cloud) junto al script
```

## Primera ejecución

```bash
python ia_scout.py
```

Abrirá el navegador para autorizar acceso a Google Sheets. Genera `token.json`
que se reutiliza en ejecuciones posteriores (sin interacción).

## Programación (cron)

```
0 */6 * * * cd /ruta/ia_scout && ./.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Hojas de Google Sheets requeridas

- **Hashes** (2 columnas): `content_hash` | `timestamp_utc`
- **ScoutIA** (15 columnas): ver comentario en `guardar_en_sheets()`

## Nota sobre el entorno remoto

Este pipeline **no** puede ejecutarse dentro de Claude Code on the web:
- El contenedor es efímero → `token.json` se pierde entre ejecuciones.
- El flujo OAuth requiere navegador local, imposible en headless.
- Las credenciales no viajan al sandbox.

Despliégalo en un entorno persistente (tu portátil, un VPS, o un servicio
tipo Railway/Fly con un volumen persistente para `token.json`).
