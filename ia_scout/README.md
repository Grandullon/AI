# IA Scout

Pipeline de inteligencia de contenidos para el canal **Diario Vida IA** (@PacoVidaIA).

Monitoriza Reddit, RSS de blogs y canales de YouTube, deduplica, puntua con Claude
y publica un resumen en Telegram + Google Sheets.

## Instalacion

```bash
cd ia_scout
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # y rellena los valores reales
```

Coloca en la misma carpeta:

- `credentials.json` — OAuth client (tipo Desktop) descargado de Google Cloud Console.
- `.env` — tokens de Anthropic y Telegram, IDs, y rutas.

## Primera ejecucion

```bash
python ia_scout.py
```

Se abrira el navegador para autorizar Google Sheets. Se genera `token.json`
automaticamente. Las siguientes ejecuciones son silenciosas.

## Cron

```
0 */6 * * * cd /ruta/ia_scout && /ruta/ia_scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Hojas requeridas en el spreadsheet

- **Hashes**: columna A `content_hash`, columna B `timestamp`.
- **ScoutIA**: 15 columnas — `content_hash | fecha_detectado | fuente | titulo | url | autor | preview | keywords | notificado | vale | formato | puntuacion | gancho | angulo | estado`.

## Modelo Claude

`claude-haiku-4-5-20251001`, 800 tokens max, con espera de 0.5s entre llamadas.
