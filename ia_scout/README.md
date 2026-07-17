# IA Scout — Diario Vida IA

Pipeline de inteligencia de contenidos. Cada ejecución:

1. Descarga posts nuevos de Reddit, blogs RSS y canales YouTube RSS.
2. Deduplica contra la hoja `Hashes` de Google Sheets.
3. Analiza cada novedad con Claude Haiku para puntuarla contra el canal.
4. Escribe resultados en la hoja `ScoutIA`.
5. Envía a Telegram (chat `714952561`) las propuestas `vale == "SI"`.

## Setup

```bash
cd ia_scout
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # rellenar valores reales
# Colocar credentials.json (OAuth desktop client de Google Cloud Console)
python ia_scout.py         # primera vez abre navegador para autorizar Google
```

## Credenciales necesarias

| Variable / archivo | Origen |
|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `TELEGRAM_BOT_TOKEN` | @BotFather |
| `TELEGRAM_CHAT_ID` | ID del chat/grupo destino |
| `GOOGLE_SHEETS_ID` | ID de la hoja de cálculo |
| `credentials.json` | OAuth 2.0 Client ID (Desktop) de Google Cloud Console |
| `token.json` | Se genera solo tras el primer OAuth |

La hoja debe tener dos pestañas: `Hashes` (2 columnas) y `ScoutIA` (15 columnas descritas en `ia_scout.py`).

## Scheduling

```
0 */6 * * * cd /ruta/ia_scout && ./.venv/bin/python ia_scout.py >> logs/scout.log 2>&1
```

## Estructura

```
ia_scout/
├── ia_scout.py       # Script principal
├── requirements.txt
├── .env.example
├── .env              # No commit
├── credentials.json  # No commit
├── token.json        # No commit
├── .gitignore
└── logs/
```
