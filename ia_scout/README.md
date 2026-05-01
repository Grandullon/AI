# IA Scout

Pipeline de inteligencia de contenidos para el canal **Diario Vida IA** (Paco, @PacoVidaIA).
Monitoriza fuentes RSS, Reddit y YouTube, deduplica, analiza con Claude y envía un resumen por Telegram.

## Setup

```bash
cd ia_scout
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # rellenar credenciales
```

Coloca el `credentials.json` (OAuth client secrets de Google Cloud Console) en esta carpeta.
La primera ejecución abre el navegador para autorizar y crea `token.json`.

## Hojas de cálculo requeridas

En el Google Sheet con ID `GOOGLE_SHEETS_ID`:

- **Hashes** (2 cols): `content_hash | timestamp`
- **ScoutIA** (15 cols): `content_hash | fecha_detectado | fuente | titulo | url | autor | preview | keywords | notificado | vale | formato | puntuacion | gancho | angulo | estado`

## Ejecutar

```bash
python ia_scout.py
```

## Programar

```cron
0 */6 * * * cd /ruta/scout && python ia_scout.py >> logs/scout.log 2>&1
```

## Fuentes

- **Reddit**: r/notebooklm, r/PromptEngineering, r/ArtificialInteligence, r/ChatGPT, r/ClaudeAI, r/productivity
- **Blogs RSS**: Ethan Mollick (OneUsefulThing), Simon Willison
- **YouTube**: 8 canales de creadores IA configurados en `YOUTUBE_CHANNELS`
