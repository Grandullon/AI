# IA Scout — Diario Vida IA

Pipeline de inteligencia de contenidos para el canal YouTube **Diario Vida IA** (@PacoVidaIA).

Monitoriza fuentes RSS, YouTube y Reddit, deduplica, analiza con Claude API,
guarda los resultados en Google Sheets y envía un resumen por Telegram.

## Instalación

```bash
cd ia_scout
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # editar con credenciales reales
```

Coloca el archivo `credentials.json` (OAuth client secrets desde Google Cloud
Console, tipo "Aplicación de escritorio") en este directorio.

## Primera ejecución

```bash
python ia_scout.py
```

Abrirá el navegador para autorizar acceso a Google Sheets. Tras confirmar se
guarda `token.json` y las siguientes ejecuciones son silenciosas.

## Programación con cron

```cron
0 */6 * * * cd /ruta/ia_scout && /ruta/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Estructura de la hoja

- **Hashes** (2 columnas): `content_hash | timestamp_iso`
- **ScoutIA** (15 columnas): `content_hash | fecha_detectado | fuente | titulo | url | autor | preview | keywords | notificado | vale | formato | puntuacion | gancho | angulo | estado`

Crea ambas pestañas con las cabeceras antes de la primera ejecución.

## Fuentes monitorizadas

- **Reddit**: r/notebooklm, r/PromptEngineering, r/ArtificialInteligence, r/ChatGPT, r/ClaudeAI, r/productivity
- **RSS**: One Useful Thing (Ethan Mollick), Simon Willison
- **YouTube**: 8 canales de referencia

Editar las constantes `REDDIT_SOURCES`, `RSS_BLOGS`, `YOUTUBE_CHANNELS` en
`ia_scout.py` para añadir o quitar fuentes.
