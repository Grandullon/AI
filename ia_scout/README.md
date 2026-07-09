# IA Scout

Pipeline de inteligencia de contenidos para el canal **Diario Vida IA**.
Monitoriza fuentes RSS, Reddit y YouTube, deduplica, analiza cada item con Claude, guarda en Google Sheets y envía un resumen por Telegram con las propuestas relevantes.

## Instalación

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuración

1. Copia `.env.example` a `.env` y rellena las variables.
2. Descarga `credentials.json` (OAuth client secrets tipo "Desktop") desde Google Cloud Console y déjalo junto al script.
3. La hoja de cálculo debe tener dos pestañas: `Hashes` (cabecera `hash | timestamp`) y `ScoutIA` (15 columnas A–O como se detalla abajo).

## Ejecución

```bash
python ia_scout.py
```

La primera ejecución abrirá el navegador para autorizar el acceso a Sheets y generará `token.json`. Las siguientes son silenciosas.

## Programación

```cron
0 */6 * * * cd /ruta/ia_scout && python ia_scout.py >> logs/scout.log 2>&1
```

## Esquema `ScoutIA` (columnas)

| Col | Campo |
| --- | --- |
| A | content_hash |
| B | fecha_detectado |
| C | fuente |
| D | titulo |
| E | url |
| F | autor |
| G | preview |
| H | keywords |
| I | notificado |
| J | vale |
| K | formato |
| L | puntuacion |
| M | gancho |
| N | angulo |
| O | estado |
