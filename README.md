# IA Scout — Diario Vida IA

Pipeline de inteligencia de contenidos para el canal YouTube **Diario Vida IA**
(Paco, @PacoVidaIA). Monitoriza Reddit, RSS y YouTube, deduplica, analiza con
Claude, guarda en Google Sheets y notifica por Telegram.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # rellenar con las claves reales
# colocar credentials.json (OAuth client de Google Cloud Console) en la raíz
python ia_scout.py     # 1ª vez abre navegador para OAuth y crea token.json
```

## Cron sugerido

```cron
0 */6 * * * cd /ruta/scout && /ruta/scout/.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Hoja de cálculo

Necesita dos worksheets en el Sheet `GOOGLE_SHEETS_ID`:

- **Hashes**: cabecera `content_hash | timestamp`
- **ScoutIA**: 15 columnas A-O (ver `guardar_en_sheets` en `ia_scout.py`)

## Modelo Claude

`claude-haiku-4-5-20251001` con `max_tokens=800`.
